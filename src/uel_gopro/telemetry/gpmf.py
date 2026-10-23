from __future__ import annotations

import logging
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, List, Optional, Union

from uel_gopro.core.models import GpsPoint, TelemetryTrack

logger = logging.getLogger(__name__)


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
    """Parse GPSU timestamp string into UTC datetime."""
    val = val.strip().strip("\x00")
    if not val:
        return None

    # Try ISO format
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except Exception:
        pass

    # Try YYMMDDHHMMSS.sss format (GoPro GPSU standard)
    try:
        if "." in val:
            base, frac = val.split(".", 1)
        else:
            base, frac = val, "0"
        if len(base) == 12:
            dt = datetime.strptime(base, "%y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            micro = int(float(f"0.{frac}") * 1_000_000)
            return dt + timedelta(microseconds=micro)
        elif len(base) == 14:
            dt = datetime.strptime(base, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            micro = int(float(f"0.{frac}") * 1_000_000)
            return dt + timedelta(microseconds=micro)
    except Exception:
        pass

    return None


def unpack_value(type_byte: int, type_size: int, repeat: int, raw_payload: bytes) -> Any:
    """Unpack raw KLV payload into Python native data structures."""
    if not raw_payload:
        return None

    type_char = bytes([type_byte])
    total_len = len(raw_payload)

    # String types
    if type_char in (b"c", b"U"):
        return raw_payload.decode("utf-8", errors="replace").rstrip("\x00")

    # FourCC
    if type_char == b"F":
        return raw_payload.decode("ascii", errors="replace").rstrip("\x00")

    # Numeric unpacking
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
        count = total_len // size
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
        try:
            fourcc = fourcc_bytes.decode("ascii", errors="replace")
        except Exception:
            fourcc = str(fourcc_bytes)

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
        is_container = (type_byte == 0) or (fourcc in ("DEVC", "STRM"))

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
    """Extract a list of scale factors from parsed SCAL value."""
    if val is None:
        return []
    if isinstance(val, (int, float)):
        return [float(val)]
    if isinstance(val, (list, tuple)):
        return [float(x) for x in val]
    return []


def _parse_gps_payload(
    klv: KLV,
    scal_list: List[float],
    current_gpsu: Optional[datetime],
) -> List[GpsPoint]:
    """Parse GPS5 or GPS9 sensor samples into scaled GpsPoint models."""
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

    # Determine stride per sample
    if klv.type_size >= 20 and klv.type_size % val_size == 0:
        stride = klv.type_size // val_size
    elif total_vals % 9 == 0 and total_vals % 5 != 0:
        stride = 9
    elif total_vals % 7 == 0 and total_vals % 5 != 0:
        stride = 7
    elif total_vals % 5 == 0:
        stride = 5
    elif total_vals % 7 == 0:
        stride = 7
    elif total_vals % 9 == 0:
        stride = 9
    else:
        stride = 5

    num_samples = total_vals // stride
    points: List[GpsPoint] = []

    def get_scale(idx: int) -> float:
        if not scal_list:
            return 1.0
        val = scal_list[idx] if idx < len(scal_list) else scal_list[0]
        return float(val) if val != 0 else 1.0

    for i in range(num_samples):
        chunk = unpacked[i * stride : (i + 1) * stride]
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
        else:
            if abs(raw_lat) > 360:
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

        # Calculate timestamp
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
            # 18Hz approximate sample delta
            dt = current_gpsu + timedelta(seconds=i * (1.0 / 18.0))
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
    """Process a STRM container node."""
    scal_list: List[float] = []
    current_gpsu: Optional[datetime] = None

    # First pass: find SCAL and GPSU
    for child in strm_klv.children:
        if child.fourcc == "SCAL":
            scal_list = _extract_scal(child.parsed_value)
        elif child.fourcc == "GPSU":
            current_gpsu = _parse_gpsu(str(child.parsed_value))

    # Second pass: process sensors
    for child in strm_klv.children:
        if child.fourcc in ("GPS5", "GPS9"):
            points = _parse_gps_payload(child, scal_list, current_gpsu)
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
        points = _parse_gps_payload(klv, [], None)
        track.gps_points.extend(points)
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
    """Parse raw GPMF binary bytes and return populated TelemetryTrack."""
    track = TelemetryTrack(device_name="GoPro")
    if not raw_bytes:
        return track

    top_klvs = unpack_klv_stream(raw_bytes)
    for klv in top_klvs:
        _process_klv(klv, track)

    return track


def extract_gpmf_from_mp4(file_path: Union[Path, str]) -> bytes:
    """Extract raw GPMF telemetry bytes from an MP4 file using ffmpeg."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Telemetry video file not found: {path}")

    # Directly return raw payloads if given a binary file
    if path.suffix.lower() in (".bin", ".raw", ".gpmf"):
        return path.read_bytes()

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        commands = [
            # 1. Standard GoPro MET track handler
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:m:handler_name:GoPro MET",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # 2. First data stream
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:d:0",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # 3. Alternative handler name
            [
                "ffmpeg", "-y", "-i", str(path),
                "-codec", "copy",
                "-map", "0:m:handler_name:GoPro gpmd",
                "-f", "rawvideo",
                str(tmp_path),
            ],
            # 4. Fallback to raw data muxer
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
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and tmp_path.stat().st_size > 0:
                    return tmp_path.read_bytes()
                last_err = res.stderr.decode("utf-8", errors="replace")
            except FileNotFoundError:
                raise RuntimeError("ffmpeg executable not found in PATH")
            except Exception as e:
                last_err = str(e)

        raise RuntimeError(f"Failed to extract GPMF telemetry track from {path}: {last_err}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
