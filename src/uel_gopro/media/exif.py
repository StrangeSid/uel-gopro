from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import shutil
import struct
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Seconds between 1904-01-01 (MP4 / QuickTime epoch) and 1970-01-01 (Unix epoch)
MP4_EPOCH_OFFSET = 2082844800


def extract_mp4_creation_time(file_path: Path | str) -> Optional[datetime]:
    """Extract creation time directly from MP4 container metadata (moov -> mvhd atom).

    Pure Python ISO Base Media File Format (ISO/IEC 14496-12) parser.
    Zero external dependencies, fast seek past large mdat payloads.

    Args:
        file_path: Path to MP4 file.

    Returns:
        UTC datetime if found, None otherwise.
    """
    path = Path(file_path)
    if not path.is_file():
        return None

    try:
        file_size = path.stat().st_size
        with open(path, "rb") as f:
            while f.tell() < file_size:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break

                box_size, box_type = struct.unpack(">I4s", hdr)
                hdr_len = 8

                if box_size == 1:
                    ext_hdr = f.read(8)
                    if len(ext_hdr) < 8:
                        break
                    box_size = struct.unpack(">Q", ext_hdr)[0]
                    hdr_len = 16
                elif box_size == 0:
                    box_size = file_size - (f.tell() - 8)

                if box_size < hdr_len:
                    break

                payload_size = box_size - hdr_len

                if box_type == b"moov":
                    # Scan child atoms inside moov for mvhd
                    moov_end = f.tell() + payload_size
                    while f.tell() < moov_end:
                        sub_hdr = f.read(8)
                        if len(sub_hdr) < 8:
                            break

                        sub_size, sub_type = struct.unpack(">I4s", sub_hdr)
                        sub_hdr_len = 8
                        if sub_size == 1:
                            sub_ext = f.read(8)
                            if len(sub_ext) < 8:
                                break
                            sub_size = struct.unpack(">Q", sub_ext)[0]
                            sub_hdr_len = 16
                        elif sub_size == 0:
                            sub_size = moov_end - (f.tell() - 8)

                        if sub_size < sub_hdr_len:
                            break

                        sub_payload = sub_size - sub_hdr_len

                        if sub_type == b"mvhd":
                            # mvhd atom structure:
                            # 1 byte version, 3 bytes flags
                            vf = f.read(4)
                            if len(vf) < 4:
                                return None
                            version = vf[0]

                            if version == 0:
                                # 4 bytes creation_time, 4 bytes mod_time
                                times = f.read(8)
                                if len(times) < 8:
                                    return None
                                c_time, m_time = struct.unpack(">II", times)
                            elif version == 1:
                                # 8 bytes creation_time, 8 bytes mod_time
                                times = f.read(16)
                                if len(times) < 16:
                                    return None
                                c_time, m_time = struct.unpack(">QQ", times)
                            else:
                                return None

                            chosen_time = c_time if c_time > 0 else m_time
                            if chosen_time > MP4_EPOCH_OFFSET:
                                unix_ts = chosen_time - MP4_EPOCH_OFFSET
                                return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
                            return None
                        else:
                            f.seek(sub_payload, os.SEEK_CUR)

                    return None
                else:
                    # Skip non-moov top-level atom (e.g. ftyp, mdat)
                    f.seek(payload_size, os.SEEK_CUR)

    except (OSError, struct.error, ValueError) as e:
        logger.debug(f"Failed parsing MP4 atom metadata in {path}: {e}")
        return None

    return None


def extract_creation_time_ffprobe(
    file_path: Path | str,
    ffprobe_path: str = "ffprobe",
) -> Optional[datetime]:
    """Fallback creation time extraction using ffprobe."""
    path = Path(file_path)
    if not path.is_file() or not shutil.which(ffprobe_path):
        return None

    cmd = [
        ffprobe_path,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_entries",
        "format_tags=creation_time",
        str(path),
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            return None
        data = json.loads(res.stdout)
        ct_str = data.get("format", {}).get("tags", {}).get("creation_time")
        if ct_str:
            # Typically ISO format: "2026-10-23T14:30:00.000000Z"
            clean_str = ct_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_str)
    except Exception as e:
        logger.debug(f"ffprobe extraction failed for {path}: {e}")

    return None


def extract_creation_time(file_path: Path | str) -> Optional[datetime]:
    """Extract creation time from video file.

    Tries pure Python MP4 box parser first, then falls back to ffprobe.

    Args:
        file_path: Video file path.

    Returns:
        Parsed datetime (UTC) if found, else None.
    """
    dt = extract_mp4_creation_time(file_path)
    if dt is not None:
        return dt
    return extract_creation_time_ffprobe(file_path)


def sync_file_time(
    file_path: Path | str,
    timestamp: Optional[datetime | float | int] = None,
) -> bool:
    """Synchronize file access and modification times (os.utime).

    If timestamp is provided, applies it directly. Otherwise, attempts to
    extract creation time from the file's container metadata.

    Args:
        file_path: Target file path.
        timestamp: Explicit datetime, Unix epoch float/int, or None to auto-extract.

    Returns:
        True if modification time was successfully synchronized, False otherwise.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found for time sync: {path}")

    epoch_sec: Optional[float] = None
    if timestamp is not None:
        if isinstance(timestamp, datetime):
            epoch_sec = timestamp.timestamp()
        else:
            epoch_sec = float(timestamp)
    else:
        extracted = extract_creation_time(path)
        if extracted is not None:
            epoch_sec = extracted.timestamp()

    if epoch_sec is None:
        return False

    os.utime(path, (epoch_sec, epoch_sec))
    return True
