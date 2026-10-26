from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import struct
from unittest.mock import MagicMock, patch
import httpx
import pytest

from uel_gopro.core.exceptions import MediaError, StitchError
from uel_gopro.media.downloader import download_file, get_remote_file_size
from uel_gopro.media.exif import (
    MP4_EPOCH_OFFSET,
    extract_creation_time,
    extract_mp4_creation_time,
    sync_file_time,
)
from uel_gopro.media.stitcher import (
    detect_chapters,
    parse_gopro_filename,
    stitch_chapters,
)


# =============================================================================
# Helper to create synthetic MP4 file with moov/mvhd
# =============================================================================

def create_synthetic_mp4(
    dt: datetime,
    version: int = 0,
    mdat_before_moov: bool = True,
    mdat_size: int = 64,
) -> bytes:
    """Constructs a minimal valid MP4 byte structure containing moov -> mvhd."""
    mp4_ts = int(dt.timestamp()) + MP4_EPOCH_OFFSET

    # Build mvhd body
    # version (1 byte) + flags (3 bytes)
    flags = b"\x00\x00\x00"
    if version == 0:
        times = struct.pack(">II", mp4_ts, mp4_ts)
        rest = struct.pack(">II", 1000, 5000)  # timescale, duration
    else:
        times = struct.pack(">QQ", mp4_ts, mp4_ts)
        rest = struct.pack(">IQ", 1000, 5000)  # timescale, duration

    mvhd_body = bytes([version]) + flags + times + rest
    mvhd_box = struct.pack(">I4s", len(mvhd_body) + 8, b"mvhd") + mvhd_body

    # Build moov box
    moov_box = struct.pack(">I4s", len(mvhd_box) + 8, b"moov") + mvhd_box

    # Build ftyp box
    ftyp_body = b"isom\x00\x00\x02\x00mp41isom"
    ftyp_box = struct.pack(">I4s", len(ftyp_body) + 8, b"ftyp") + ftyp_body

    if mdat_before_moov:
        # mdat box
        mdat_payload = b"\x00" * mdat_size
        mdat_box = struct.pack(">I4s", len(mdat_payload) + 8, b"mdat") + mdat_payload
        return ftyp_box + mdat_box + moov_box
    else:
        return ftyp_box + moov_box


# =============================================================================
# Chapter Detection & Parsing Tests
# =============================================================================

class TestChapterDetection:
    def test_parse_modern_hevc(self):
        info1 = parse_gopro_filename("GX010123.MP4")
        assert info1 is not None
        assert info1.prefix == "GX"
        assert info1.chapter_num == 1
        assert info1.base_id == "0123"
        assert info1.extension == "mp4"

        info2 = parse_gopro_filename("gx020123.mp4")
        assert info2 is not None
        assert info2.prefix == "GX"
        assert info2.chapter_num == 2
        assert info2.base_id == "0123"

    def test_parse_modern_avc(self):
        info = parse_gopro_filename("GH010456.MP4")
        assert info is not None
        assert info.prefix == "GH"
        assert info.chapter_num == 1
        assert info.base_id == "0456"

        info2 = parse_gopro_filename("GH030456.mp4")
        assert info2 is not None
        assert info2.chapter_num == 3
        assert info2.base_id == "0456"

    def test_parse_modern_lrv_and_360(self):
        lrv = parse_gopro_filename("GL010123.LRV")
        assert lrv is not None
        assert lrv.prefix == "GL"
        assert lrv.chapter_num == 1
        assert lrv.base_id == "0123"
        assert lrv.extension == "lrv"

        s360 = parse_gopro_filename("GS020123.360")
        assert s360 is not None
        assert s360.prefix == "GS"
        assert s360.chapter_num == 2
        assert s360.base_id == "0123"
        assert s360.extension == "360"

    def test_parse_legacy_naming(self):
        # Legacy Chapter 1: GOPR<base>.MP4
        leg1 = parse_gopro_filename("GOPR0789.MP4")
        assert leg1 is not None
        assert leg1.prefix == "GOPR"
        assert leg1.chapter_num == 1
        assert leg1.base_id == "0789"

        # Legacy Chapter 2+: GP<chap><base>.MP4 (GP01 is chapter 2, GP02 is chapter 3)
        leg2 = parse_gopro_filename("GP010789.MP4")
        assert leg2 is not None
        assert leg2.prefix == "GP"
        assert leg2.chapter_num == 2
        assert leg2.base_id == "0789"

        leg3 = parse_gopro_filename("GP020789.MP4")
        assert leg3 is not None
        assert leg3.prefix == "GP"
        assert leg3.chapter_num == 3
        assert leg3.base_id == "0789"

    def test_parse_invalid_filenames(self):
        assert parse_gopro_filename("not_gopro.mp4") is None
        assert parse_gopro_filename("IMG_0001.MOV") is None
        assert parse_gopro_filename("GOPR.MP4") is None
        assert parse_gopro_filename("GX1234.MP4") is None
        assert parse_gopro_filename(".DS_Store") is None

    def test_detect_chapters_sorting_and_grouping(self):
        # Pass files out of order and across multiple recordings
        input_files = [
            "GX030123.MP4",
            "GP020789.MP4",
            "GH020456.MP4",
            "GX010123.MP4",
            "GOPR0789.MP4",
            "GH010456.MP4",
            "GP010789.MP4",
            "GX020123.MP4",
            "random_notes.txt",
        ]

        result = detect_chapters(input_files)

        assert set(result.keys()) == {"0123", "0456", "0789"}

        # Verify HEVC "0123" sorted chapter 1 -> 2 -> 3
        assert [p.name for p in result["0123"]] == [
            "GX010123.MP4",
            "GX020123.MP4",
            "GX030123.MP4",
        ]

        # Verify AVC "0456" sorted chapter 1 -> 2
        assert [p.name for p in result["0456"]] == [
            "GH010456.MP4",
            "GH020456.MP4",
        ]

        # Verify Legacy "0789" sorted GOPR -> GP01 -> GP02
        assert [p.name for p in result["0789"]] == [
            "GOPR0789.MP4",
            "GP010789.MP4",
            "GP020789.MP4",
        ]


# =============================================================================
# Downloader Tests
# =============================================================================

class TestDownloader:
    def test_head_query_64bit_size(self):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010123.MP4"
        # 5 GB file size > 32-bit uint max (4,294,967,295)
        file_size_64bit = 5_368_709_120

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(
                    200,
                    headers={"Content-Length": str(file_size_64bit)},
                )
            return httpx.Response(405)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            size = get_remote_file_size(url, client=client)
            assert size == file_size_64bit

    def test_head_rejected_falls_back_to_ranged_get(self):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010123.MP4"
        file_size_64bit = 5_368_709_120

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(405)
            if request.method == "GET":
                assert request.headers.get("Range") == "bytes=0-0"
                return httpx.Response(
                    206,
                    headers={
                        "Content-Range": f"bytes 0-0/{file_size_64bit}",
                        "Content-Length": "1",
                    },
                    content=b"x",
                )
            return httpx.Response(400)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            assert get_remote_file_size(url, client=client) == file_size_64bit

    def test_download_file_complete_flow(self, tmp_path: Path):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010001.MP4"
        content = b"GoPro Video Payload Simulation 12345" * 100
        total_len = len(content)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": str(total_len)})
            elif request.method == "GET":
                return httpx.Response(
                    200,
                    headers={"Content-Length": str(total_len)},
                    content=content,
                )
            return httpx.Response(400)

        target = tmp_path / "GX010001.MP4"
        progress_records = []

        def on_progress(downloaded: int, total: int):
            progress_records.append((downloaded, total))

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            result_path = download_file(
                url,
                target,
                client=client,
                chunk_size=128,
                progress_callback=on_progress,
            )

        assert result_path == target
        assert target.is_file()
        assert target.read_bytes() == content
        # Partial file must be cleaned up / renamed
        assert not target.with_name("GX010001.MP4.partial").exists()
        assert len(progress_records) > 0
        assert progress_records[-1] == (total_len, total_len)

    def test_download_file_resume_partial(self, tmp_path: Path):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010002.MP4"
        full_content = b"0123456789abcdef" * 100  # 1600 bytes
        split_point = 600

        target = tmp_path / "GX010002.MP4"
        partial_file = target.with_name("GX010002.MP4.partial")

        # Pre-create partial file with first 600 bytes
        partial_file.write_bytes(full_content[:split_point])

        requested_range_header = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal requested_range_header
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": str(len(full_content))})
            elif request.method == "GET":
                requested_range_header = request.headers.get("Range")
                if requested_range_header == f"bytes={split_point}-":
                    remaining = full_content[split_point:]
                    return httpx.Response(
                        206,
                        headers={
                            "Content-Range": f"bytes {split_point}-{len(full_content)-1}/{len(full_content)}",
                            "Content-Length": str(len(remaining)),
                        },
                        content=remaining,
                    )
                return httpx.Response(200, content=full_content)
            return httpx.Response(400)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            download_file(url, target, client=client, chunk_size=128)

        assert requested_range_header == f"bytes={split_point}-"
        assert target.is_file()
        assert target.read_bytes() == full_content
        assert not partial_file.exists()

    def test_download_partial_already_complete(self, tmp_path: Path):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010003.MP4"
        content = b"AllBytesAlreadyDownloaded"
        target = tmp_path / "GX010003.MP4"
        partial = target.with_name("GX010003.MP4.partial")
        partial.write_bytes(content)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": str(len(content))})
            # GET should not even be called
            return httpx.Response(500)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            res = download_file(url, target, client=client)

        assert res == target
        assert target.read_bytes() == content
        assert not partial.exists()

    def test_download_size_mismatch_raises_error(self, tmp_path: Path):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/GX010004.MP4"

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(200, headers={"Content-Length": "1000"})
            elif request.method == "GET":
                # Returns fewer bytes than advertised in Content-Length
                return httpx.Response(200, content=b"Only 20 bytes!!")
            return httpx.Response(400)

        target = tmp_path / "GX010004.MP4"
        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            with pytest.raises(MediaError, match="size mismatch"):
                download_file(url, target, client=client)

    def test_download_http_error(self, tmp_path: Path):
        url = "http://172.24.162.51:8080/videos/DCIM/100GOPRO/NOTFOUND.MP4"

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            with pytest.raises(MediaError, match="HTTP 404"):
                download_file(url, tmp_path / "NOTFOUND.MP4", client=client)


# =============================================================================
# Stitcher Tests
# =============================================================================

class TestStitcher:
    def test_stitch_chapters_invalid_input(self, tmp_path: Path):
        # Empty input
        with pytest.raises(StitchError, match="No chapter files"):
            stitch_chapters([], tmp_path / "out.mp4")

        # Non-existent file
        with pytest.raises(StitchError, match="Chapter file not found"):
            stitch_chapters([tmp_path / "nonexistent.mp4"], tmp_path / "out.mp4")

    @patch("subprocess.run")
    def test_stitch_chapters_manifest_and_cmd(self, mock_run: MagicMock, tmp_path: Path):
        ch1 = tmp_path / "GX010123.MP4"
        ch2 = tmp_path / "GX020123.MP4"
        ch1.write_bytes(b"dummy1")
        ch2.write_bytes(b"dummy2")

        out = tmp_path / "stitched.mp4"

        manifest_content = ""

        def side_effect(cmd, **kwargs):
            nonlocal manifest_content
            # Locate manifest path in cmd
            manifest_idx = cmd.index("-i") + 1
            manifest_path = cmd[manifest_idx]
            # Read manifest while it still exists
            manifest_content = Path(manifest_path).read_text()
            # Simulate FFmpeg producing the temporary output
            Path(cmd[-1]).write_bytes(b"stitched_video_content")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        result = stitch_chapters([ch1, ch2], out, ffmpeg_path="ffmpeg")
        assert result == out
        assert out.is_file()

        # Verify command arguments
        called_cmd = mock_run.call_args[0][0]
        assert called_cmd[0] == "ffmpeg"
        assert "-f" in called_cmd and called_cmd[called_cmd.index("-f") + 1] == "concat"
        assert "-safe" in called_cmd and called_cmd[called_cmd.index("-safe") + 1] == "0"
        assert "-map" in called_cmd and called_cmd[called_cmd.index("-map") + 1] == "0"
        assert "-c" in called_cmd and called_cmd[called_cmd.index("-c") + 1] == "copy"
        assert called_cmd[-1] == str(tmp_path / "stitched.partial.mp4")

        # Verify manifest content
        assert f"file '{ch1}'" in manifest_content
        assert f"file '{ch2}'" in manifest_content

    @patch("subprocess.run")
    def test_stitch_chapters_ffmpeg_error(self, mock_run: MagicMock, tmp_path: Path):
        ch1 = tmp_path / "GX010123.MP4"
        ch1.write_bytes(b"dummy")
        out = tmp_path / "out.mp4"

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Invalid data found when processing input",
        )

        with pytest.raises(StitchError, match="FFmpeg failed with exit code 1"):
            stitch_chapters([ch1], out)

    @patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found"))
    def test_stitch_chapters_binary_missing(self, mock_run: MagicMock, tmp_path: Path):
        ch1 = tmp_path / "GX010123.MP4"
        ch1.write_bytes(b"dummy")
        out = tmp_path / "out.mp4"

        with pytest.raises(StitchError, match="FFmpeg binary not found"):
            stitch_chapters([ch1], out, ffmpeg_path="invalid_ffmpeg")


# =============================================================================
# EXIF & Timestamp Sync Tests
# =============================================================================

class TestExifAndSync:
    def test_extract_mp4_creation_time_version_0(self, tmp_path: Path):
        target_dt = datetime(2026, 10, 23, 14, 30, 0, tzinfo=timezone.utc)
        mp4_bytes = create_synthetic_mp4(target_dt, version=0, mdat_before_moov=True)

        test_file = tmp_path / "GX010001.MP4"
        test_file.write_bytes(mp4_bytes)

        extracted = extract_mp4_creation_time(test_file)
        assert extracted == target_dt

    def test_extract_mp4_creation_time_version_1(self, tmp_path: Path):
        target_dt = datetime(2026, 10, 23, 15, 45, 12, tzinfo=timezone.utc)
        mp4_bytes = create_synthetic_mp4(target_dt, version=1, mdat_before_moov=True)

        test_file = tmp_path / "GX010002.MP4"
        test_file.write_bytes(mp4_bytes)

        extracted = extract_mp4_creation_time(test_file)
        assert extracted == target_dt

    def test_extract_creation_time_invalid_file(self, tmp_path: Path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Not an MP4 file")

        assert extract_mp4_creation_time(txt_file) is None
        assert extract_creation_time(txt_file) is None

    def test_sync_file_time_with_explicit_timestamp(self, tmp_path: Path):
        f = tmp_path / "test.mp4"
        f.write_bytes(b"dummy")

        dt = datetime(2026, 5, 10, 10, 0, 0, tzinfo=timezone.utc)
        success = sync_file_time(f, timestamp=dt)
        assert success is True
        assert abs(f.stat().st_mtime - dt.timestamp()) < 1.0

        # Sync with int epoch timestamp
        epoch_ts = 1700000000
        success2 = sync_file_time(f, timestamp=epoch_ts)
        assert success2 is True
        assert abs(f.stat().st_mtime - epoch_ts) < 1.0

    def test_sync_file_time_auto_from_mp4(self, tmp_path: Path):
        target_dt = datetime(2026, 8, 15, 12, 0, 0, tzinfo=timezone.utc)
        mp4_bytes = create_synthetic_mp4(target_dt, version=0)

        f = tmp_path / "GX010003.MP4"
        f.write_bytes(mp4_bytes)

        # Set mtime to 0 first
        os.utime(f, (0, 0))
        assert f.stat().st_mtime != target_dt.timestamp()

        # Auto-extract and sync
        synced = sync_file_time(f)
        assert synced is True
        assert abs(f.stat().st_mtime - target_dt.timestamp()) < 1.0

    def test_sync_file_time_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            sync_file_time(tmp_path / "nonexistent.mp4")


# =============================================================================
# CLI Media & Process Command Tests
# =============================================================================

class TestMediaCLI:
    def test_cli_media_list(self):
        from typer.testing import CliRunner
        from uel_gopro.cli.main import app
        from uel_gopro.core.models import CameraInfo, MediaItem, MediaType

        runner = CliRunner()
        mock_info = CameraInfo(model_name="HERO11 Black")
        mock_client = MagicMock()
        mock_client.get_media_list.return_value = [
            MediaItem(
                directory="100GOPRO",
                filename="GX010001.MP4",
                size_bytes=500_000_000,
                mod_time=1700000000,
                media_type=MediaType.VIDEO,
                is_chapter=False,
                chapter_num=1,
                base_id="0001",
            )
        ]

        with patch("uel_gopro.cli.main.resolve_camera", return_value=(mock_info, mock_client)):
            res = runner.invoke(app, ["media", "list"])
            assert res.exit_code == 0
            assert "GX010001.MP4" in res.output

            # JSON format
            res_json = runner.invoke(app, ["media", "list", "--json"])
            assert res_json.exit_code == 0
            assert "GX010001.MP4" in res_json.output

    def test_cli_process_sync_dates(self, tmp_path: Path):
        from typer.testing import CliRunner
        from uel_gopro.cli.main import app

        target_dt = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
        mp4_bytes = create_synthetic_mp4(target_dt, version=0)
        f = tmp_path / "GX010055.MP4"
        f.write_bytes(mp4_bytes)

        runner = CliRunner()
        res = runner.invoke(app, ["process", "sync-dates", str(f)])
        assert res.exit_code == 0
        assert "Synced GX010055.MP4" in res.output
        assert abs(f.stat().st_mtime - target_dt.timestamp()) < 1.0

    @patch("uel_gopro.cli.main.stitch_chapters")
    def test_cli_process_stitch(self, mock_stitch: MagicMock, tmp_path: Path):
        from typer.testing import CliRunner
        from uel_gopro.cli.main import app

        ch1 = tmp_path / "GX010123.MP4"
        ch2 = tmp_path / "GX020123.MP4"
        ch1.write_bytes(b"dummy1")
        ch2.write_bytes(b"dummy2")

        out = tmp_path / "out_stitched.mp4"
        out.write_bytes(create_synthetic_mp4(datetime.now(timezone.utc)))
        mock_stitch.return_value = out

        runner = CliRunner()
        res = runner.invoke(app, ["process", "stitch", str(ch1), str(ch2), "-o", str(out)])
        assert res.exit_code == 0
        assert "Stitched successfully" in res.output
        assert mock_stitch.called

