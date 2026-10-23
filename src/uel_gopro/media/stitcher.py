from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Optional

from uel_gopro.core.exceptions import StitchError

logger = logging.getLogger(__name__)

# Modern GoPro naming (HERO6 through HERO13):
# GX<chap><base>.MP4 (HEVC) or GH<chap><base>.MP4 (AVC)
# GL<chap><base>.LRV (Low-res preview) or GS<chap><base>.360 (MAX 360)
# chap is 2 digits (01, 02, ...), base is 4 digits.
MODERN_PATTERN = re.compile(
    r"^(?P<prefix>G[XHSL])(?P<chap>\d{2})(?P<base>\d{4})\.(?P<ext>mp4|lrv|360)$",
    re.IGNORECASE,
)

# Legacy GoPro naming (HERO5 and older):
# Chapter 1: GOPR<base>.MP4
LEGACY_CHAP1_PATTERN = re.compile(
    r"^GOPR(?P<base>\d{4})\.(?P<ext>mp4|lrv|360)$",
    re.IGNORECASE,
)

# Chapter 2+: GP<chap><base>.MP4 where chap is 01, 02, ... (corresponding to chapter 2, 3...)
LEGACY_CHAPN_PATTERN = re.compile(
    r"^GP(?P<chap>\d{2})(?P<base>\d{4})\.(?P<ext>mp4|lrv|360)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GoProChapterInfo:
    """Parsed GoPro filename metadata."""
    base_id: str
    chapter_num: int
    prefix: str
    extension: str


def parse_gopro_filename(filename: str | Path) -> Optional[GoProChapterInfo]:
    """Parse GoPro video filename to extract base ID, chapter number, and format.

    Supports:
        - Modern HEVC: GX010123.MP4 (chap 1, base 0123)
        - Modern AVC:  GH010456.MP4 (chap 1, base 0456)
        - Modern LRV:  GL010123.LRV (chap 1, base 0123)
        - Modern 360:  GS010123.360 (chap 1, base 0123)
        - Legacy ch 1: GOPR0789.MP4 (chap 1, base 0789)
        - Legacy ch 2+: GP010789.MP4 (chap 2, base 0789)
    """
    name = Path(filename).name

    # Check modern naming
    match_mod = MODERN_PATTERN.match(name)
    if match_mod:
        return GoProChapterInfo(
            base_id=match_mod.group("base"),
            chapter_num=int(match_mod.group("chap")),
            prefix=match_mod.group("prefix").upper(),
            extension=match_mod.group("ext").lower(),
        )

    # Check legacy chapter 1
    match_leg1 = LEGACY_CHAP1_PATTERN.match(name)
    if match_leg1:
        return GoProChapterInfo(
            base_id=match_leg1.group("base"),
            chapter_num=1,
            prefix="GOPR",
            extension=match_leg1.group("ext").lower(),
        )

    # Check legacy chapter 2+
    match_leg2 = LEGACY_CHAPN_PATTERN.match(name)
    if match_leg2:
        return GoProChapterInfo(
            base_id=match_leg2.group("base"),
            chapter_num=int(match_leg2.group("chap")) + 1,
            prefix="GP",
            extension=match_leg2.group("ext").lower(),
        )

    return None


def detect_chapters(file_paths: list[Path | str]) -> dict[str, list[Path]]:
    """Group file paths by GoPro base ID, sorted in chronological chapter order.

    Non-GoPro or unparseable files are ignored.

    Args:
        file_paths: List of file paths or filenames.

    Returns:
        Dictionary mapping base ID (str) to ordered list of Path objects.
    """
    grouped: dict[str, list[tuple[int, Path]]] = defaultdict(list)

    for item in file_paths:
        path = Path(item)
        info = parse_gopro_filename(path.name)
        if info is not None:
            grouped[info.base_id].append((info.chapter_num, path))

    result: dict[str, list[Path]] = {}
    for base_id, items in grouped.items():
        # Sort by chapter number, then filename for determinism
        sorted_paths = [p for _, p in sorted(items, key=lambda x: (x[0], x[1].name))]
        result[base_id] = sorted_paths

    return result


def stitch_chapters(
    chapter_files: list[Path | str],
    output_path: Path | str,
    ffmpeg_path: str = "ffmpeg",
) -> Path:
    """Concatenate GoPro video chapters into a single file without re-encoding.

    Creates an FFmpeg concat demuxer manifest and executes:
        ffmpeg -f concat -safe 0 -i <manifest> -map 0 -c copy <output_path>

    Preserves all tracks (video, audio, timecode, and GPMF telemetry).

    Args:
        chapter_files: List of chapter paths in desired chronological order.
        output_path: Target destination path for concatenated video.
        ffmpeg_path: Path to FFmpeg binary (default 'ffmpeg').

    Returns:
        Path to the stitched output file.

    Raises:
        StitchError: If inputs are invalid or FFmpeg execution fails.
    """
    if not chapter_files:
        raise StitchError("No chapter files provided for stitching.")

    resolved_files: list[Path] = []
    for f in chapter_files:
        p = Path(f).resolve()
        if not p.is_file():
            raise StitchError(f"Chapter file not found: {p}")
        resolved_files.append(p)

    out_p = Path(output_path).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)

    manifest_fd, manifest_path = tempfile.mkstemp(prefix="gopro_concat_", suffix=".txt")
    try:
        with open(manifest_fd, "w", encoding="utf-8") as manifest:
            for f in resolved_files:
                # Concat demuxer expects lines: file '/escaped/path'
                escaped = str(f).replace("'", "'\\''")
                manifest.write(f"file '{escaped}'\n")

        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            manifest_path,
            "-map",
            "0",
            "-c",
            "copy",
            str(out_p),
        ]

        logger.debug(f"Running stitch command: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as e:
            raise StitchError(
                f"FFmpeg binary not found at '{ffmpeg_path}'. Ensure FFmpeg is installed."
            ) from e
        except OSError as e:
            raise StitchError(f"Failed to execute FFmpeg: {e}") from e

        if result.returncode != 0:
            err_msg = result.stderr.strip() or result.stdout.strip()
            raise StitchError(f"FFmpeg failed with exit code {result.returncode}:\n{err_msg}")

        if not out_p.exists() or out_p.stat().st_size == 0:
            raise StitchError(f"Stitched output file was not created or is empty: {out_p}")

        return out_p

    finally:
        if os.path.exists(manifest_path):
            try:
                os.unlink(manifest_path)
            except OSError:
                pass
