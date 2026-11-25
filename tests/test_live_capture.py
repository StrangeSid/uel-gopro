from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from uel_gopro.api.rest import SETTING_ALIASES, GoProRestClient, resolve_setting_id
from uel_gopro.core.exceptions import CommandError, MediaError, TransportError
from uel_gopro.core.models import CameraInfo, CameraStatus, MediaItem, MediaType
from uel_gopro.stream.capture import (
    PRIMARY_MEDIA_TYPES,
    CaptureManager,
    CaptureRecord,
    TransferProgress,
    default_downloads_dir,
    unique_destination_path,
)


# ---------------------------------------------------------------------------
# Setting aliases & resolve_setting_id
# ---------------------------------------------------------------------------


def test_setting_aliases_contains_expected_mappings():
    assert SETTING_ALIASES == {
        "resolution": 2,
        "res": 2,
        "fps": 3,
        "framerate": 3,
        "fov": 121,
        "lens": 121,
        "bitrate": 182,
        "anti_flicker": 134,
        "hypersmooth": 135,
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("resolution", 2),
        ("RES", 2),
        ("Fps", 3),
        ("  Framerate ", 3),
        ("FOV", 121),
        ("lens", 121),
        ("BiTrAtE", 182),
        ("anti_flicker", 134),
        ("  ANTI_FLICKER ", 134),
        ("HyperSmooth", 135),
        (2, 2),
        (0, 0),
        (182, 182),
        ("2", 2),
        (" 121 ", 121),
    ],
)
def test_resolve_setting_id_valid(raw, expected):
    assert resolve_setting_id(raw) == expected


@pytest.mark.parametrize(
    "invalid",
    [True, False, "", "   ", "unknown", "-1", -1, "1.5", None],
)
def test_resolve_setting_id_rejects_invalid(invalid):
    with pytest.raises(CommandError):
        resolve_setting_id(invalid)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_default_downloads_dir(monkeypatch, tmp_path: Path):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert default_downloads_dir() == fake_home / "Downloads"


def test_unique_destination_path_handles_collisions(tmp_path: Path):
    first = unique_destination_path(tmp_path, "GX010001.MP4")
    assert first == tmp_path / "GX010001.MP4"
    first.write_bytes(b"video1")

    second = unique_destination_path(tmp_path, "GX010001.MP4")
    assert second == tmp_path / "GX010001_1.MP4"
    second.write_bytes(b"video2")

    third = unique_destination_path(tmp_path, "GX010001.MP4")
    assert third == tmp_path / "GX010001_2.MP4"

    # Extensionless file collision
    no_ext = tmp_path / "README"
    no_ext.write_text("hi", encoding="utf-8")
    assert unique_destination_path(tmp_path, "README") == tmp_path / "README_1"


def test_unique_destination_path_extracts_basename_safely(tmp_path: Path):
    assert unique_destination_path(tmp_path, "100GOPRO/GX010001.MP4") == tmp_path / "GX010001.MP4"
    assert unique_destination_path(tmp_path, "../escape.mp4") == tmp_path / "escape.mp4"
    assert unique_destination_path(tmp_path, r"100GOPRO\GOPR0002.JPG") == tmp_path / "GOPR0002.JPG"


@pytest.mark.parametrize(
    "unsafe",
    ["", "   ", ".", "..", "foo/..", "foo/.", r"foo\..", "bad\x00.jpg"],
)
def test_unique_destination_path_rejects_unsafe_filenames(tmp_path: Path, unsafe: str):
    with pytest.raises(MediaError, match="Refusing unsafe filename"):
        unique_destination_path(tmp_path, unsafe)


# ---------------------------------------------------------------------------
# Snapshots & capture history
# ---------------------------------------------------------------------------


def test_save_frame_snapshot_atomic_and_history_capped(tmp_path: Path):
    manager = CaptureManager(downloads_dir=tmp_path / "dl", max_history=3)
    try:
        with pytest.raises(MediaError, match="empty"):
            manager.save_frame_snapshot(b"")

        records: list[CaptureRecord] = []
        for idx in range(5):
            rec = manager.save_frame_snapshot(f"jpeg-{idx}".encode(), prefix="frame")
            records.append(rec)
            assert Path(rec.local_path).exists()
            assert Path(rec.local_path).read_bytes() == f"jpeg-{idx}".encode()
            assert not (Path(rec.local_path).with_name(f"{rec.filename}.partial")).exists()
            assert rec.media_type == "photo"
            assert rec.source == "snapshot"
            assert rec.camera_directory is None
            # Verify ISO 8601 UTC timestamp parses cleanly
            parsed = datetime.fromisoformat(rec.captured_at)
            assert parsed.tzinfo == timezone.utc

        history = manager.list_captures()
        assert len(history) == 3
        # Newest first
        assert [item["id"] for item in history] == [
            records[4].id,
            records[3].id,
            records[2].id,
        ]
        # Collisions within the same second yield distinct filenames
        assert len({r.filename for r in records}) == 5
    finally:
        manager.shutdown()


# ---------------------------------------------------------------------------
# Camera media polling
# ---------------------------------------------------------------------------


def test_wait_for_new_media_waits_for_busy_encoding_transient_errors_and_filters_sidecars(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr("uel_gopro.stream.capture.time.sleep", lambda _: None)

    baseline_item = MediaItem(
        directory="100GOPRO",
        filename="GX010001.MP4",
        size_bytes=100,
        media_type=MediaType.VIDEO,
    )
    sidecar_thm = MediaItem(
        directory="100GOPRO",
        filename="GX010002.THM",
        size_bytes=20,
        media_type=MediaType.THUMBNAIL,
    )
    sidecar_lrv = MediaItem(
        directory="100GOPRO",
        filename="GX010002.LRV",
        size_bytes=50,
        media_type=MediaType.SIDECAR,
    )
    sidecar_wav = MediaItem(
        directory="100GOPRO",
        filename="GX010002.WAV",
        size_bytes=30,
        media_type=MediaType.AUDIO,
    )
    new_video = MediaItem(
        directory="101GOPRO",
        filename="GX010003.MP4",
        size_bytes=2048,
        media_type=MediaType.VIDEO,
    )
    new_photo = MediaItem(
        directory="100GOPRO",
        filename="GOPR0002.JPG",
        size_bytes=1024,
        media_type=MediaType.PHOTO,
    )

    assert PRIMARY_MEDIA_TYPES == frozenset({MediaType.VIDEO, MediaType.PHOTO})

    client = MagicMock(spec=GoProRestClient)
    client.get_media_list.side_effect = [
        [baseline_item],  # initial snapshot
        TransportError("camera restarting wifi"),  # transient media error
        [baseline_item, sidecar_thm, sidecar_lrv, sidecar_wav],  # only sidecars so far
        [baseline_item, sidecar_thm, sidecar_lrv, sidecar_wav, new_video, new_photo],
    ]
    client.get_status.side_effect = [
        CameraStatus(encoding_active=True),
        CameraStatus(encoding_active=False, raw_status={"8": "1"}),
        TransportError("transient status timeout"),
        CameraStatus(encoding_active=False, raw_status={"8": 0}),
        CameraStatus(encoding_active=False, raw_status={"8": 0}),
        CameraStatus(encoding_active=False, raw_status={"8": 0}),
    ]

    manager = CaptureManager(downloads_dir=tmp_path)
    try:
        baseline = manager.snapshot_camera_media(client)
        assert baseline == {("100GOPRO", "GX010001.MP4")}

        found = manager.wait_for_new_media(
            client,
            baseline,
            timeout_sec=5.0,
            poll_interval=0.01,
        )
        assert [(m.directory, m.filename) for m in found] == [
            ("100GOPRO", "GOPR0002.JPG"),
            ("101GOPRO", "GX010003.MP4"),
        ]
    finally:
        manager.shutdown()


def test_wait_for_new_media_timeout_returns_empty(tmp_path: Path):
    client = MagicMock(spec=GoProRestClient)
    client.get_status.return_value = CameraStatus(encoding_active=True)

    manager = CaptureManager(downloads_dir=tmp_path)
    try:
        result = manager.wait_for_new_media(
            client,
            baseline=set(),
            timeout_sec=0.02,
            poll_interval=0.005,
        )
        assert result == []
    finally:
        manager.shutdown()


# ---------------------------------------------------------------------------
# Download & background sync
# ---------------------------------------------------------------------------


def test_download_camera_item_tracks_progress_and_syncs_mtime(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    mod_ts = 1700000123
    item = MediaItem(
        directory="100GOPRO",
        filename="GX010010.MP4",
        size_bytes=12,
        mod_time=mod_ts,
        media_type=MediaType.VIDEO,
    )

    seen_urls: list[str] = []
    progress_snapshots: list[dict[str, Any]] = []

    def fake_download(
        url: str,
        target_path: Path,
        *,
        progress_callback=None,
        expected_size=None,
    ) -> Path:
        seen_urls.append(url)
        assert expected_size == 12
        if progress_callback:
            progress_callback(6, 12)
            progress_snapshots.extend(manager.list_transfers())
            progress_callback(12, 12)
        target_path.write_bytes(b"0123456789ab")
        return target_path

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=fake_download)
    try:
        record = manager.download_camera_item(info, item)
        assert seen_urls == ["http://172.20.150.51:8080/videos/DCIM/100GOPRO/GX010010.MP4"]
        assert record.filename == "GX010010.MP4"
        assert record.size_bytes == 12
        assert record.source == "camera"
        assert record.media_type == "video"
        assert record.camera_directory == "100GOPRO"

        dest = Path(record.local_path)
        assert dest.exists()
        assert int(dest.stat().st_mtime) == mod_ts

        # Mid-download progress snapshot recorded 50%
        assert any(
            t["status"] == "downloading" and t["bytes_downloaded"] == 6 and t["percent"] == 50.0
            for t in progress_snapshots
        )

        transfers = manager.list_transfers()
        assert len(transfers) == 1
        final_transfer = TransferProgress(**transfers[0])
        assert final_transfer.status == "completed"
        assert final_transfer.percent == 100.0
        assert final_transfer.local_path == str(dest)
        assert final_transfer.error is None
    finally:
        manager.shutdown()


def test_download_camera_item_failure_marks_transfer_failed(tmp_path: Path):
    info = CameraInfo(ip_address="10.5.5.9", port=8080)
    item = MediaItem(
        directory="100GOPRO",
        filename="GOPR0005.JPG",
        size_bytes=512,
        media_type=MediaType.PHOTO,
    )

    def failing_download(url: str, target_path: Path, **kwargs: Any) -> Path:
        raise RuntimeError("socket reset")

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=failing_download)
    try:
        with pytest.raises(MediaError, match="socket reset"):
            manager.download_camera_item(info, item, job_id="job-err")

        transfers = manager.list_transfers()
        assert len(transfers) == 1
        assert transfers[0]["job_id"] == "job-err"
        assert transfers[0]["status"] == "failed"
        assert "socket reset" in (transfers[0]["error"] or "")
        assert manager.list_captures() == []
    finally:
        manager.shutdown()


def test_enqueue_post_capture_sync_completes_in_background(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    new_photo = MediaItem(
        directory="100GOPRO",
        filename="GOPR0100.JPG",
        size_bytes=5,
        media_type=MediaType.PHOTO,
    )
    client = MagicMock(spec=GoProRestClient)
    client.get_status.return_value = CameraStatus(encoding_active=False, raw_status={"8": "0"})
    client.get_media_list.return_value = [new_photo]

    def fake_download(url: str, target_path: Path, **kwargs: Any) -> Path:
        target_path.write_bytes(b"hello")
        return target_path

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=fake_download)
    try:
        job_id = manager.enqueue_post_capture_sync(
            client,
            info,
            baseline=set(),
            timeout_sec=2.0,
            poll_interval=0.01,
        )
        assert manager.wait_idle(timeout=5.0) is True

        transfers = {t["job_id"]: t for t in manager.list_transfers()}
        assert transfers[job_id]["status"] == "completed"
        assert transfers[job_id]["filename"] == "GOPR0100.JPG"
        assert transfers[job_id]["percent"] == 100.0

        captures = manager.list_captures()
        assert len(captures) == 1
        assert captures[0]["filename"] == "GOPR0100.JPG"
        assert captures[0]["source"] == "camera"
    finally:
        manager.shutdown()


def test_enqueue_post_capture_sync_timeout_marks_failed(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    client = MagicMock(spec=GoProRestClient)
    client.get_status.return_value = CameraStatus(encoding_active=False, raw_status={"8": "0"})
    client.get_media_list.return_value = []

    manager = CaptureManager(downloads_dir=tmp_path)
    try:
        job_id = manager.enqueue_post_capture_sync(
            client,
            info,
            baseline=set(),
            timeout_sec=0.02,
            poll_interval=0.005,
        )
        assert manager.wait_idle(timeout=5.0) is True

        transfers = {t["job_id"]: t for t in manager.list_transfers()}
        assert transfers[job_id]["status"] == "failed"
        assert "timeout" in (transfers[job_id]["error"] or "").lower()
    finally:
        manager.shutdown()


def test_shutdown_interrupts_active_post_capture_sync_poll(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    poll_started = threading.Event()
    client = MagicMock(spec=GoProRestClient)

    def fake_get_status() -> CameraStatus:
        poll_started.set()
        return CameraStatus(encoding_active=True)

    client.get_status.side_effect = fake_get_status

    manager = CaptureManager(downloads_dir=tmp_path)
    try:
        job_id = manager.enqueue_post_capture_sync(
            client,
            info,
            baseline=set(),
            timeout_sec=15.0,
            poll_interval=1.0,
        )
        assert poll_started.wait(timeout=2.0) is True
        time.sleep(0.05)

        start = time.monotonic()
        manager.shutdown(wait=True)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0
        assert manager.wait_idle(timeout=1.0) is True
        transfers = {t["job_id"]: t for t in manager.list_transfers()}
        assert transfers[job_id]["status"] == "failed"
        assert transfers[job_id]["error"]
    finally:
        manager.shutdown(wait=True)



def test_unique_destination_path_avoids_existing_partial(tmp_path: Path):
    (tmp_path / "GX010001.MP4.partial").write_bytes(b"in-progress")
    assert unique_destination_path(tmp_path, "GX010001.MP4") == tmp_path / "GX010001_1.MP4"


@pytest.mark.parametrize(
    "bad_prefix",
    ["", "   ", ".", "..", "foo/bar", r"foo\bar", "bad\x00prefix", None],
)
def test_save_frame_snapshot_rejects_unsafe_prefix(tmp_path: Path, bad_prefix):
    manager = CaptureManager(downloads_dir=tmp_path)
    try:
        with pytest.raises(MediaError, match="Refusing unsafe snapshot prefix"):
            manager.save_frame_snapshot(b"jpegdata", prefix=bad_prefix)  # type: ignore[arg-type]
    finally:
        manager.shutdown()


def test_save_frame_snapshot_cleans_partial_on_write_or_replace_error(
    monkeypatch,
    tmp_path: Path,
):
    manager = CaptureManager(downloads_dir=tmp_path)

    def failing_replace(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", failing_replace)
    try:
        with pytest.raises(MediaError, match="disk full"):
            manager.save_frame_snapshot(b"jpegdata", prefix="snap")
        assert list(tmp_path.glob("*.partial")) == []
        assert manager.list_captures() == []
    finally:
        manager.shutdown()


def test_save_frame_snapshot_concurrent_calls_produce_distinct_files(tmp_path: Path):
    manager = CaptureManager(downloads_dir=tmp_path, max_history=20)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [
                pool.submit(manager.save_frame_snapshot, f"frame-{i}".encode(), "burst")
                for i in range(12)
            ]
            records = [f.result() for f in futures]

        paths = {Path(r.local_path) for r in records}
        assert len(paths) == 12
        for rec in records:
            assert Path(rec.local_path).read_bytes().startswith(b"frame-")
        assert list(tmp_path.glob("*.partial")) == []
    finally:
        manager.shutdown()


def test_download_camera_item_logs_warning_when_sync_file_time_fails(
    monkeypatch,
    tmp_path: Path,
    caplog,
):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    item = MediaItem(
        directory="100GOPRO",
        filename="GX010011.MP4",
        size_bytes=4,
        mod_time=1700000123,
        media_type=MediaType.VIDEO,
    )

    def fake_download(url: str, target_path: Path, **kwargs: Any) -> Path:
        target_path.write_bytes(b"data")
        return target_path

    def broken_sync(*args: Any, **kwargs: Any) -> bool:
        raise OSError("utime denied")

    monkeypatch.setattr("uel_gopro.stream.capture.sync_file_time", broken_sync)
    manager = CaptureManager(downloads_dir=tmp_path, download_fn=fake_download)
    try:
        record = manager.download_camera_item(info, item)
        assert Path(record.local_path).exists()
        assert manager.list_transfers()[0]["status"] == "completed"
        assert "Failed to sync file time" in caplog.text
    finally:
        manager.shutdown()


def test_enqueue_post_capture_sync_multi_item_does_not_regress_status(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    jpg_item = MediaItem(
        directory="100GOPRO",
        filename="GOPR0200.JPG",
        size_bytes=4,
        media_type=MediaType.PHOTO,
    )
    gpr_item = MediaItem(
        directory="100GOPRO",
        filename="GOPR0200.GPR",
        size_bytes=6,
        media_type=MediaType.PHOTO,
    )
    client = MagicMock(spec=GoProRestClient)
    client.get_status.return_value = CameraStatus(encoding_active=False, raw_status={"8": "0"})
    client.get_media_list.return_value = [gpr_item, jpg_item]

    observed_statuses: list[str] = []

    def fake_download(
        url: str,
        target_path: Path,
        *,
        progress_callback=None,
        expected_size=None,
    ) -> Path:
        payload = b"1234" if target_path.name.endswith(".JPG") else b"123456"
        if progress_callback:
            progress_callback(len(payload) // 2, len(payload))
            observed_statuses.extend(t["status"] for t in manager.list_transfers())
            progress_callback(len(payload), len(payload))
        target_path.write_bytes(payload)
        return target_path

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=fake_download)
    try:
        job_id = manager.enqueue_post_capture_sync(
            client,
            info,
            baseline=set(),
            timeout_sec=2.0,
            poll_interval=0.01,
        )
        assert manager.wait_idle(timeout=5.0) is True

        # During both downloads, parent job_id must stay in "downloading" and never regress from "completed"
        assert observed_statuses
        assert set(observed_statuses) == {"downloading"}

        transfers = {t["job_id"]: t for t in manager.list_transfers()}
        assert len(transfers) == 1
        assert transfers[job_id]["status"] == "completed"
        assert transfers[job_id]["bytes_downloaded"] == 10
        assert transfers[job_id]["total_bytes"] == 10
        assert transfers[job_id]["percent"] == 100.0

        captures = manager.list_captures()
        assert {c["filename"] for c in captures} == {"GOPR0200.GPR", "GOPR0200.JPG"}
        assert (tmp_path / "GOPR0200.GPR").exists()
        assert (tmp_path / "GOPR0200.JPG").exists()
    finally:
        manager.shutdown()


def test_wait_idle_timeout_and_enqueue_after_shutdown(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)
    gate = threading.Event()
    started = threading.Event()
    item = MediaItem(
        directory="100GOPRO",
        filename="GOPR0300.JPG",
        size_bytes=3,
        media_type=MediaType.PHOTO,
    )
    client = MagicMock(spec=GoProRestClient)
    client.get_status.return_value = CameraStatus(encoding_active=False, raw_status={"8": "0"})
    client.get_media_list.return_value = [item]

    def blocking_download(url: str, target_path: Path, **kwargs: Any) -> Path:
        started.set()
        gate.wait(timeout=2.0)
        target_path.write_bytes(b"abc")
        return target_path

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=blocking_download)
    job_id = manager.enqueue_post_capture_sync(
        client,
        info,
        baseline=set(),
        timeout_sec=2.0,
        poll_interval=0.01,
    )
    assert started.wait(timeout=2.0) is True
    assert manager.wait_idle(timeout=0.02) is False

    gate.set()
    assert manager.wait_idle(timeout=5.0) is True
    assert manager.list_transfers()[0]["job_id"] == job_id
    assert manager.list_transfers()[0]["status"] == "completed"

    manager.shutdown(wait=True)
    with pytest.raises(MediaError, match="shut down"):
        manager.enqueue_post_capture_sync(client, info, baseline=set())
    # No orphaned "waiting" transfer entry left behind
    assert len(manager.list_transfers()) == 1


def test_transfers_history_is_capped_and_zero_max_history_skips_captures(tmp_path: Path):
    info = CameraInfo(ip_address="172.20.150.51", port=8080)

    def fake_download(url: str, target_path: Path, **kwargs: Any) -> Path:
        target_path.write_bytes(b"ok")
        return target_path

    manager = CaptureManager(downloads_dir=tmp_path, download_fn=fake_download, max_history=2)
    try:
        for i in range(4):
            item = MediaItem(
                directory="100GOPRO",
                filename=f"GOPR000{i}.JPG",
                size_bytes=2,
                media_type=MediaType.PHOTO,
            )
            manager.download_camera_item(info, item, job_id=f"job-{i}")

        assert [t["job_id"] for t in manager.list_transfers()] == ["job-2", "job-3"]
        assert [c["filename"] for c in manager.list_captures()] == ["GOPR0003.JPG", "GOPR0002.JPG"]
    finally:
        manager.shutdown()

    zero_mgr = CaptureManager(downloads_dir=tmp_path / "zero", max_history=0)
    try:
        zero_mgr.save_frame_snapshot(b"jpeg")
        assert zero_mgr.list_captures() == []
    finally:
        zero_mgr.shutdown()
