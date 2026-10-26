from __future__ import annotations

import logging
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

from uel_gopro.core.exceptions import TelemetryError
from uel_gopro.core.models import GpsPoint, TelemetryTrack

logger = logging.getLogger(__name__)

# GoPro's GPS streams are sampled at approximately 18 Hz.  The sample index
# is used only when a stream does not carry its own days/seconds fields.
GPS_NOMINAL_HZ = 18.0


@dataclass
class KLV:
    """Represents a single GPMF Key-Length-Value packet."""

    fourcc: str
    type_char: bytes
    type_size: int
    repeat: int
    raw_payload: bytes
    children: List[KLV] = field(default_factory=list)
    parsed_value: Any = None


def _parse_gpsu(val: str) -> Optional[datetime]:
    """Parse a GPSU timestamp string into a UTC datetime."""
    val = val.strip().strip("\x00")
    if not val:
        return None

    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        pass

    try:
        if "." in val:
            base, frac = val.split(".", 1)
        else:
            base, frac = val, "0"
        if len(base) == 12:
            dt = datetime.strptime(base, "%y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            micro = int(float(f"0.{frac}") * 1_000_000)
            return dt + timedelta(microseconds=micro)
        if len(base) == 14:
            dt = datetime.strptime(base, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            micro = int(float(f"0.{frac}") * 1_000_000)
            return dt + timedelta(microseconds=micro)
    except Exception:
        pass

    return None


def unpack_value(type_byte: int, type_size: int, repeat: int, raw_payload: bytes) -> Any:
    """Unpack a raw KLV payload into Python native data structures."""
    if not raw_payload:
        return None

    type_char = bytes([type_byte])

    if type_char in (b"c", b"U"):
        return raw_payload.decode("utf-8", errors="replace").rstrip("\x00")

    if type_char == b"F":
        return raw_payload.decode("ascii", errors="replace").rstrip("\x00")

    fmt_map = {
        b"b": (1, "b"),
        b"B": (1, "B"),
        b"s": (2, "h"),
        b"S": (2, "H"),
        b"l": (4, "i"),
        b"L": (4, "I"),
        b"f": (4, "f"),
        b"d": (8, "d"),
        b"j": (8, "q"),
        b"J": (8, "Q"),
    }

    if type_char in fmt_map:
        size, code = fmt_map[type_char]
        count = len(raw_payload) // size
        if count == 0:
            return None
        unpacked = list(struct.unpack(f">{count}{code}", raw_payload[: count * size]))
        if repeat == 1 and len(unpacked) == 1:
            return unpacked[0]
        return unpacked

    return raw_payload


def unpack_klv_stream(data: bytes) -> List[KLV]:
    """Parse raw GPMF bytes into a hierarchical list of KLV nodes."""
    elements: List[KLV] = []
    offset = 0
    total = len(data)

    while offset + 8 <= total:
        fourcc_bytes = data[offset : offset + 4]
        fourcc = fourcc_bytes.decode("ascii", errors="replace")

        type_byte = data[offset + 4]
        type_size = data[offset + 5]
        (repeat,) = struct.unpack(">H", data[offset + 6 : offset + 8])

        payload_size = type_size * repeat
        padded_size = (payload_size + 3) & ~3
        payload_start = offset + 8
        payload_end = payload_start + payload_size
        next_offset = payload_start + padded_size

        if payload_end > total:
            break

        raw_payload = data[payload_start:payload_end]
        is_container = type_byte == 0 or fourcc in ("DEVC", "STRM")

        children: List[KLV] = []
        parsed_val: Any = None
        if is_container:
            children = unpack_klv_stream(raw_payload)
        else:
            parsed_val = unpack_value(type_byte, type_size, repeat, raw_payload)

        elements.append(
            KLV(
                fourcc=fourcc,
                type_char=bytes([type_byte]),
                type_size=type_size,
                repeat=repeat,
                raw_payload=raw_payload,
                children=children,
                parsed_value=parsed_val,
            )
        )
        offset = next_offset

    return elements


def _extract_scal(val: Any) -> List[float]:
    """Extract a list of scale factors from a parsed SCAL value."""
    if val is None:
        return []
    if isinstance(val, (int, float)):
        return [float(val)]
    if isinstance(val, (list, tuple)):
        return [float(x) for x in val]
    return []


def _determine_stride(klv: KLV, total_vals: int, val_size: int) -> int:
    """Determine values-per-sample for a GPS KLV node.

    The fourcc is authoritative: GPS5 carries 5 values per sample and GPS9
    carries 9.  Synthetic/legacy streams sometimes encode the per-sample size
    in the KLV type-size field; honour that when it is consistent.  Only
    unknown stream types fall back to divisibility heuristics.
    """
    if klv.fourcc in ("GPS5", "GPS9"):
        expected = 5 if klv.fourcc == "GPS5" else 9
        if klv.type_size >= expected * val_size and klv.type_size % val_size == 0:
            stride = klv.type_size // val_size
            if stride in (5, 7, 9) and total_vals % stride == 0:
                return stride
        return expected

    if klv.type_size >= 20 and klv.type_size % val_size == 0:
        return klv.type_size // val_size
    for candidate in (9, 7, 5):
        if total_vals % candidate == 0:
            return candidate
    return 5


def _parse_gps_payload(
    klv: KLV,
    scal_list: List[float],
    current_gpsu: Optional[datetime],
    start_index: int = 0,
) -> List[GpsPoint]:
    """Parse GPS5/GPS9 samples into scaled GpsPoint models."""
    raw = klv.raw_payload
    if not raw:
        return []

    type_char = klv.type_char
    if type_char in (b"l", b"L"):
        val_size = 4
        fmt_char = "i" if type_char == b"l" else "I"
    elif type_char in (b"s", b"S"):
        val_size = 2
        fmt_char = "h" if type_char == b"s" else "H"
    elif type_char == b"f":
        val_size = 4
        fmt_char = "f"
    elif type_char == b"d":
        val_size = 8
        fmt_char = "d"
    else:
        val_size = 4
        fmt_char = "i"

    total_vals = len(raw) // val_size
    if total_vals == 0:
        return []

    unpacked = struct.unpack(f">{total_vals}{fmt_char}", raw[: total_vals * val_size])
    stride = _determine_stride(klv, total_vals, val_size)
    num_samples = total_vals // stride
    points: List[GpsPoint] = []

    def get_scale(idx: int) -> float:
        if not scal_list:
            return 1.0
        val = scal_list[idx] if idx < len(scal_list) else scal_list[0]
        try:
            return float(val) if val != 0 else 1.0
        except (TypeError, ValueError):
            return 1.0

    for sample_idx in range(num_samples):
        chunk = unpacked[sample_idx * stride : (sample_idx + 1) * stride]
        if len(chunk) < 3:
            continue

        raw_lat = chunk[0]
        raw_lon = chunk[1]
        raw_alt = chunk[2]
        raw_s2d = chunk[3] if len(chunk) > 3 else 0.0
        raw_s3d = chunk[4] if len(chunk) > 4 else 0.0

        if scal_list:
            lat = float(raw_lat) / get_scale(0)
            lon = float(raw_lon) / get_scale(1)
            alt = float(raw_alt) / get_scale(2)
            s2d = float(raw_s2d) / get_scale(3) if len(chunk) > 3 else None
            s3d = float(raw_s3d) / get_scale(4) if len(chunk) > 4 else None
        elif abs(raw_lat) > 360:
            lat = float(raw_lat) / 10_000_000.0
            lon = float(raw_lon) / 10_000_000.0
            alt = float(raw_alt) / 1000.0
            s2d = float(raw_s2d) / 1000.0 if len(chunk) > 3 else None
            s3d = float(raw_s3d) / 1000.0 if len(chunk) > 4 else None
        else:
            lat = float(raw_lat)
            lon = float(raw_lon)
            alt = float(raw_alt)
            s2d = float(raw_s2d) if len(chunk) > 3 else None
            s3d = float(raw_s3d) if len(chunk) > 4 else None

        ts_utc: Optional[str] = None
        if len(chunk) >= 7:
            raw_days = chunk[5]
            raw_secs = chunk[6]
            scale_secs = get_scale(6) if len(scal_list) > 6 else (1000.0 if raw_secs > 86400 else 1.0)
            secs = float(raw_secs) / scale_secs
            dt = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc) + timedelta(
                days=int(raw_days), seconds=secs
            )
            ts_utc = dt.isoformat()
        elif current_gpsu:
            # GPSP (precision time) is not parsed yet, so this is approximate.
            sample_number = start_index + sample_idx
            dt = current_gpsu + timedelta(seconds=sample_number / GPS_NOMINAL_HZ)
            ts_utc = dt.isoformat()

        points.append(
            GpsPoint(
                timestamp_utc=ts_utc,
                lat=round(lat, 7),
                lon=round(lon, 7),
                alt=round(alt, 3),
                speed_2d=round(s2d, 3) if s2d is not None else None,
                speed_3d=round(s3d, 3) if s3d is not None else None,
            )
        )

    return points


def _process_strm(strm_klv: KLV, track: TelemetryTrack) -> None:
    """Process a STRM container sequentially, tracking GPSU second resets."""
    scal_list: List[float] = []
    for child in strm_klv.children:
        if child.fourcc == "SCAL":
            scal_list = _extract_scal(child.parsed_value)
            break

    current_gpsu: Optional[datetime] = None
    sample_index = 0
    for child in strm_klv.children:
        if child.fourcc == "SCAL":
            continue
        if child.fourcc == "GPSU":
            current_gpsu = _parse_gpsu(str(child.parsed_value))
            sample_index = 0
        elif child.fourcc in ("GPS5", "GPS9"):
            points = _parse_gps_payload(child, scal_list, current_gpsu, sample_index)
            sample_index += len(points)
            track.gps_points.extend(points)
        elif child.fourcc == "ACCL":
            track.has_accel = True
        elif child.fourcc == "GYRO":
            track.has_gyro = True
        elif child.fourcc == "DVNM" and child.parsed_value:
            track.device_name = str(child.parsed_value)
        elif child.children:
            _process_strm(child, track)


def _process_klv(klv: KLV, track: TelemetryTrack) -> None:
    """Traverse and process any KLV node."""
    if klv.fourcc == "DEVC":
        for child in klv.children:
            if child.fourcc == "DVNM" and child.parsed_value:
                track.device_name = str(child.parsed_value)
            elif child.fourcc == "STRM":
                _process_strm(child, track)
            else:
                _process_klv(child, track)
    elif klv.fourcc == "STRM":
        _process_strm(klv, track)
    elif klv.fourcc in ("GPS5", "GPS9"):
        track.gps_points.extend(_parse_gps_payload(klv, [], None))
    elif klv.fourcc == "ACCL":
        track.has_accel = True
    elif klv.fourcc == "GYRO":
        track.has_gyro = True
    elif klv.fourcc == "DVNM" and klv.parsed_value:
        track.device_name = str(klv.parsed_value)
    elif klv.children:
        for child in klv.children:
            _process_klv(child, track)


def parse_gpmf_stream(raw_bytes: bytes) -> TelemetryTrack:
    """Parse raw GPMF binary bytes and return a populated TelemetryTrack."""
    track = TelemetryTrack(device_name="GoPro")
    if not raw_bytes:
        return track
    for klv in unpack_klv_stream(raw_bytes):
        _process_klv(klv, track)
    return track


def extract_gpmf_from_mp4(file_path: Path | str) -> bytes:
    """Extract raw GPMF telemetry bytes from an MP4 file using ffmpeg."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Telemetry video file not found: {path}")

    if path.suffix.lower() in (".bin", ".raw", ".gpmf"):
        return path.read_bytes()

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        commands = [
            # Standard GoPro MET track handler
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:m:handler_name:GoPro MET",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # First data stream fallback
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:d:0",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # Alternative handler name
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:m:handler_name:GoPro gpmd",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # Raw data muxer fallback
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:m:handler_name:GoPro MET",
                "-f", "data",
                str(tmp_path),
            ],
        ]

        last_err = ""
        for cmd in commands:
            try:
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if result.returncode == 0 and tmp_path.stat().st_size > 0:
                    return tmp_path.read_bytes()
                last_err = result.stderr.decode("utf-8", errors="replace")
            except FileNotFoundError as exc:
                raise TelemetryError("ffmpeg executable not found in PATH") from exc
            except Exception as exc:
                last_err = str(exc)

        raise TelemetryError(f"Failed to extract GPMF telemetry track from {path}: {last_err}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
