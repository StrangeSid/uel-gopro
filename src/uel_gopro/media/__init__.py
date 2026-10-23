"""Media ingest, chapter stitching, and metadata engine for GoPro cameras."""

from uel_gopro.media.downloader import download_file, get_remote_file_size
from uel_gopro.media.exif import (
    extract_creation_time,
    extract_mp4_creation_time,
    sync_file_time,
)
from uel_gopro.media.stitcher import (
    GoProChapterInfo,
    detect_chapters,
    parse_gopro_filename,
    stitch_chapters,
)

__all__ = [
    "download_file",
    "get_remote_file_size",
    "extract_creation_time",
    "extract_mp4_creation_time",
    "sync_file_time",
    "GoProChapterInfo",
    "detect_chapters",
    "parse_gopro_filename",
    "stitch_chapters",
]
