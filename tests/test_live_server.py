from __future__ import annotations

import io
import os
from pathlib import Path
import socket
import threading
import time
from typing import Any, Optional
from unittest.mock import MagicMock

import httpx
import pytest

import uel_gopro.stream as stream_pkg
from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError, TransportError
from uel_gopro.core.models import CameraInfo, CameraStatus, MediaItem, MediaType
from uel_gopro.stream.capture import CaptureManager
from uel_gopro.stream.live import (
    MAX_JSON_BODY_BYTES,
    LiveCameraController,
    LiveFeedServer,
    find_photo_preset_id,
    parse_preset_groups,
)
from uel_gopro.stream.transcoder import JPEG_EOI, JPEG_SOI, MjpegStreamTranscoder


def _make_jpeg(payload: bytes) -> bytes:
    return JPEG_SOI + payload + JPEG_EOI


class _PipeFakeProcess:
    """Fake FFmpeg subprocess backed by an OS pipe for real MJPEG streaming tests."""

    def __init__(self, initial_frames: list[bytes] | None = None) -> None:
        r_fd, w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb")
        self._write_fd: Optional[int] = w_fd
        self._write_lock = threading.Lock()
        self.stderr = io.BytesIO(b"")
        self.stdin = None
        self.returncode: Optional[int] = None
        for frame in initial_frames or []:
            self.write_chunk(frame)

    def write_chunk(self, data: bytes) -> None:
        with self._write_lock:
            if self._write_fd is not None:
                os.write(self._write_fd, data)

    def close_stdout(self, returncode: Optional[int] = 0) -> None:
        with self._write_lock:
            if self._write_fd is not None:
                os.close(self._write_fd)
                self._write_fd = None
            if self.returncode is None:
                self.returncode = returncode

    def poll(self) -> Optional[int]:
        return self.returncode

    def terminate(self) -> None:
        self.close_stdout(0)

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


def _sample_presets() -> dict[str, Any]:
    return {
        "presetGroupArray": [
            {
                "id": "PRESET_GROUP_ID_VIDEO",
                "presetArray": [
                    {
                        "id": 0,
                        "titleId": "PRESET_TITLE_STANDARD",
                        "userDefined": False,
                    },
                    {
                        "id": 42,
                        "customName": "Action_Clip",
                        "userDefined": True,
                    },
                ],
            },
            {
                "id": "PRESET_GROUP_ID_PHOTO",
                "presetArray": [
                    {
                        "id": 65536,
                        "title": "PRESET_TITLE_PHOTO",
                        "userDefined": False,
                    }
                ],
            },
        ]
    }


def _make_fake_download_fn():
    def _download(
        url: str,
        dest: Path,
        *,
        progress_callback=None,
        expected_size: Optional[int] = None,
    ) -> Path:
        payload = f"downloaded:{url}".encode("utf-8")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        if progress_callback is not None:
            progress_callback(len(payload), len(payload))
        return dest

    return _download


def _build_harness(
    tmp_path: Path,
    *,
    cors_origin: Optional[str] = None,
    start_stream: bool = True,
    initial_frames: Optional[list[bytes]] = None,
    keep_alive_interval: float = 0.0,
):
    client = MagicMock(spec=GoProRestClient)
    client.get_camera_info.return_value = {
        "model_name": "HERO12 Black",
        "firmware_version": "H23.01.01.10.00",
        "serial_number": "C3501324645504",
    }
    state_box: dict[str, Any] = {
        "status": CameraStatus(
            connected=True,
            battery_percent=85,
            battery_bars=3,
            is_recording=False,
            encoding_active=False,
            sd_status="OK",
            sd_remaining_mb=12000,
            current_mode="Video",
            current_preset="0",
        ),
        "raw_state": {"status": {"10": 0}, "settings": {"2": 12, "3": 5}},
        "presets": _sample_presets(),
        "media": [
            MediaItem(
                directory="100GOPRO",
                filename="GX010001.MP4",
                size_bytes=1024,
                mod_time=1700000001,
                media_type=MediaType.VIDEO,
            ),
            MediaItem(
                directory="100GOPRO",
                filename="GOPR0002.JPG",
                size_bytes=512,
                mod_time=1700000002,
                media_type=MediaType.PHOTO,
            ),
            MediaItem(
                directory="100GOPRO",
                filename="GX010001.THM",
                size_bytes=64,
                mod_time=1700000099,
                media_type=MediaType.THUMBNAIL,
            ),
        ],
    }

    client.get_status.side_effect = lambda: state_box["status"]
    client.get_raw_state.side_effect = lambda: state_box["raw_state"]
    client.get_presets.side_effect = lambda: state_box["presets"]
    client.get_media_list.side_effect = lambda: list(state_box["media"])

    procs: list[_PipeFakeProcess] = []

    def popen_factory(cmd, **kwargs):
        proc = _PipeFakeProcess(initial_frames=initial_frames)
        procs.append(proc)
        return proc

    transcoder = MjpegStreamTranscoder(
        stream_url="udp://@0.0.0.0:8554",
        popen_factory=popen_factory,
        restart_delay_sec=0.05,
    )
    downloads_dir = tmp_path / "Downloads"
    captures = CaptureManager(
        downloads_dir=downloads_dir,
        download_fn=_make_fake_download_fn(),
    )
    info = CameraInfo(model_name="GoPro (USB)", ip_address="172.20.150.51", port=8080)
    controller = LiveCameraController(
        client=client,
        info=info,
        downloads_dir=downloads_dir,
        keep_alive_interval=keep_alive_interval,
        transcoder=transcoder,
        capture_manager=captures,
    )
    server = LiveFeedServer(
        controller=controller,
        host="127.0.0.1",
        port=0,
        cors_origin=cors_origin,
        start_stream=start_stream,
    )
    return server, controller, client, state_box, procs, downloads_dir


# ---------------------------------------------------------------------------
# Exports & Preset Helpers
# ---------------------------------------------------------------------------


def test_stream_package_exports():
    expected = {
        "CaptureManager",
        "CaptureRecord",
        "DEFAULT_STREAM_URL",
        "LiveCameraController",
        "LiveFeedServer",
        "MjpegStreamTranscoder",
        "TransferProgress",
        "default_downloads_dir",
        "get_webcam_status",
        "launch_preview_stream",
        "start_webcam",
        "stop_webcam",
    }
    assert expected.issubset(set(stream_pkg.__all__))
    for name in expected:
        assert hasattr(stream_pkg, name)


def test_parse_preset_groups_and_find_photo_preset_id():
    parsed = parse_preset_groups(_sample_presets())
    assert len(parsed) == 2
    assert parsed[0]["id"] == "PRESET_GROUP_ID_VIDEO"
    assert parsed[0]["name"] == "Video"
    assert parsed[0]["presets"] == [
        {"id": 0, "name": "Standard", "user_defined": False},
        {"id": 42, "name": "Action Clip", "user_defined": True},
    ]
    assert parsed[1]["name"] == "Photo"
    assert parsed[1]["presets"] == [
        {"id": 65536, "name": "Photo", "user_defined": False},
    ]

    assert find_photo_preset_id(_sample_presets()) == 65536
    assert (
        find_photo_preset_id(
            {
                "presetGroupArray": [
                    {"id": 1001, "presets": [{"id": True}, {"id": "77"}]},
                ]
            }
        )
        == 77
    )
    assert find_photo_preset_id({"presetGroupArray": [{"id": "1000", "presetArray": [{"id": 1}]}]}) is None


# ---------------------------------------------------------------------------
# UI, Widget, and MJPEG Stream Endpoints
# ---------------------------------------------------------------------------


def test_live_server_ui_and_mjpeg_stream(tmp_path: Path):
    frame1 = _make_jpeg(b"frame-one")
    frame2 = _make_jpeg(b"frame-two")
    server, controller, client, _, procs, _ = _build_harness(
        tmp_path,
        initial_frames=[frame1],
    )

    with server:
        assert server.port > 0
        assert server.url == f"http://127.0.0.1:{server.port}"
        assert server.embed_url == f"{server.url}/embed"
        assert server.widget_url == f"{server.url}/widget.js"
        assert server.stream_url == f"{server.url}/stream.mjpeg"

        # Camera info enriched on start
        assert controller.info.model_name == "HERO12 Black"
        assert controller.info.firmware_version == "H23.01.01.10.00"
        assert controller.info.serial_number == "C3501324645504"
        client.enable_wired_usb.assert_called_with(True)

        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            r_root = http.get("/")
            assert r_root.status_code == 200
            assert "text/html" in r_root.headers["content-type"]
            assert "/stream.mjpeg" in r_root.text

            r_embed = http.get("/embed")
            assert r_embed.status_code == 200
            assert "text/html" in r_embed.headers["content-type"]
            assert 'class="embed"' in r_embed.text

            r_widget = http.get("/widget.js")
            assert r_widget.status_code == 200
            assert "application/javascript" in r_widget.headers["content-type"]
            assert "uel-gopro-live" in r_widget.text
            assert "UelGoproLiveElement" in r_widget.text

            # Read real multipart frames from /stream.mjpeg (including cache-buster query)
            received = bytearray()
            with http.stream("GET", "/stream.mjpeg?t=12345") as stream_resp:
                assert stream_resp.status_code == 200
                assert "multipart/x-mixed-replace" in stream_resp.headers["content-type"]
                assert "boundary=frame" in stream_resp.headers["content-type"]

                # Push a second frame after first is available
                deadline = time.monotonic() + 3.0
                pushed_second = False
                for chunk in stream_resp.iter_bytes():
                    received.extend(chunk)
                    if frame1 in received and not pushed_second:
                        procs[-1].write_chunk(frame2)
                        pushed_second = True
                    if frame1 in received and frame2 in received:
                        break
                    assert time.monotonic() < deadline

            assert b"--frame\r\n" in received
            assert b"Content-Type: image/jpeg\r\n" in received
            assert frame1 in received
            assert frame2 in received


# ---------------------------------------------------------------------------
# Status, Presets, Settings, Media, Fallback
# ---------------------------------------------------------------------------


def test_api_read_endpoints_and_status_fallback(tmp_path: Path):
    server, _, client, _, _, downloads_dir = _build_harness(tmp_path, start_stream=False)

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            r_status = http.get("/api/status")
            assert r_status.status_code == 200
            payload = r_status.json()
            assert payload["ok"] is True
            assert payload["camera"]["model_name"] == "HERO12 Black"
            assert payload["status"]["connected"] is True
            assert payload["settings"] == {"2": 12, "3": 5}
            assert payload["downloads_dir"] == str(downloads_dir)
            assert payload["recording_elapsed_sec"] == 0.0
            assert payload["capabilities"]["model"] == "HERO12 Black"
            assert payload["capabilities"]["source"] == "model_matrix"
            assert payload["capabilities"]["settings"]["resolution"]["current"] == 12

            r_presets = http.get("/api/presets")
            assert r_presets.status_code == 200
            assert len(r_presets.json()["groups"]) == 2

            r_settings = http.get("/api/settings")
            assert r_settings.status_code == 200
            assert r_settings.json()["settings"] == {"2": 12, "3": 5}
            assert r_settings.json()["aliases"]["fps"] == 3
            assert r_settings.json()["capabilities"]["model"] == "HERO12 Black"

            r_caps_api = http.get("/api/capabilities")
            assert r_caps_api.status_code == 200
            caps_payload = r_caps_api.json()
            assert caps_payload["ok"] is True
            assert caps_payload["model"] == "HERO12 Black"
            assert caps_payload["settings"]["fps"]["current"] == 5

            r_media = http.get("/api/media")
            assert r_media.status_code == 200
            assert len(r_media.json()["items"]) == 3

            r_caps = http.get("/api/captures")
            assert r_caps.status_code == 200
            assert r_caps.json()["downloads_dir"] == str(downloads_dir)
            assert r_caps.json()["captures"] == []
            assert r_caps.json()["transfers"] == []

            # Status fallback when camera read raises TransportError
            client.get_status.side_effect = TransportError("camera unreachable")
            r_fallback = http.get("/api/status")
            assert r_fallback.status_code == 200
            fb = r_fallback.json()
            assert fb["ok"] is True
            assert fb["status"]["connected"] is False
            assert "camera unreachable" in fb["status_error"]
            assert fb["capabilities"]["model"] == "HERO12 Black"


# ---------------------------------------------------------------------------
# Recording, Photo, Snapshot, Media Pull
# ---------------------------------------------------------------------------


def test_shutter_record_and_auto_download(tmp_path: Path):
    server, controller, client, state_box, _, downloads_dir = _build_harness(
        tmp_path, start_stream=True
    )

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            r_start = http.post("/api/shutter/start", json={})
            assert r_start.status_code == 200
            assert r_start.json() == {"ok": True, "recording": True}
            client.shutter_start.assert_called_once()

            state_box["status"] = state_box["status"].model_copy(
                update={"is_recording": True, "encoding_active": True}
            )
            r_rec_status = http.get("/api/status")
            assert r_rec_status.json()["recording_elapsed_sec"] >= 0.0

            # Simulate new MP4 appearing after shutter stop
            state_box["status"] = state_box["status"].model_copy(
                update={"is_recording": False, "encoding_active": False}
            )
            state_box["media"].append(
                MediaItem(
                    directory="100GOPRO",
                    filename="GX010099.MP4",
                    size_bytes=2048,
                    mod_time=1700000100,
                    media_type=MediaType.VIDEO,
                )
            )

            r_stop = http.post("/api/shutter/stop", json={"auto_download": True})
            assert r_stop.status_code == 200
            stop_data = r_stop.json()
            assert stop_data["ok"] is True
            assert stop_data["recording"] is False
            assert stop_data["download_queued"] is True
            assert stop_data["job_id"]

            assert controller.captures.wait_idle(timeout=5.0)
            saved_file = downloads_dir / "GX010099.MP4"
            assert saved_file.exists()

            r_caps = http.get("/api/captures")
            assert any(c["filename"] == "GX010099.MP4" for c in r_caps.json()["captures"])
            # Preview re-armed after stop
            assert client.start_preview_stream.call_count >= 2


def test_photo_capture_modes_and_auto_download(tmp_path: Path):
    server, controller, client, state_box, _, downloads_dir = _build_harness(
        tmp_path, start_stream=False
    )

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            # Video mode without auto_switch or force -> 400
            r_err = http.post("/api/photo", json={})
            assert r_err.status_code == 400
            assert r_err.json()["ok"] is False
            assert "Photo preset" in r_err.json()["error"]

            # auto_switch=True loads photo preset 65536 and triggers shutter
            def _new_photo_after_shutter():
                state_box["media"].append(
                    MediaItem(
                        directory="100GOPRO",
                        filename="GOPR0100.JPG",
                        size_bytes=500,
                        mod_time=1700000200,
                        media_type=MediaType.PHOTO,
                    )
                )

            client.shutter_start.side_effect = _new_photo_after_shutter
            r_auto = http.post(
                "/api/photo",
                json={"auto_switch": True, "auto_download": True},
            )
            assert r_auto.status_code == 200
            data = r_auto.json()
            assert data["ok"] is True
            assert data["captured"] is True
            assert data["switched_preset"] == 65536
            assert data["download_queued"] is True
            client.load_preset.assert_called_with(65536)

            assert controller.captures.wait_idle(timeout=5.0)
            assert (downloads_dir / "GOPR0100.JPG").exists()

            # force=True works without switching preset
            client.load_preset.reset_mock()
            client.shutter_start.side_effect = None
            r_force = http.post(
                "/api/photo",
                json={"force": True, "auto_download": False},
            )
            assert r_force.status_code == 200
            assert r_force.json()["switched_preset"] is None
            assert r_force.json()["download_queued"] is False
            client.load_preset.assert_not_called()


def test_snapshot_and_media_pull(tmp_path: Path):
    frame = _make_jpeg(b"snap-bytes")
    server, controller, _, _, procs, downloads_dir = _build_harness(
        tmp_path, start_stream=False
    )

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            # No frame yet -> 400
            r_no_frame = http.post("/api/snapshot", json={})
            assert r_no_frame.status_code == 400
            assert r_no_frame.json()["ok"] is False

            # Start preview so frame arrives through the fake FFmpeg pipe
            r_prev_start = http.post("/api/preview/start", json={})
            assert r_prev_start.status_code == 200

            deadline = time.monotonic() + 3.0
            while not procs and time.monotonic() < deadline:
                time.sleep(0.01)
            assert procs, "transcoder did not spawn process"
            procs[-1].write_chunk(frame)

            while not controller.transcoder.status()["has_frame"] and time.monotonic() < deadline:
                time.sleep(0.01)
            assert controller.transcoder.status()["has_frame"] is True

            r_snap = http.post("/api/snapshot", json={})
            assert r_snap.status_code == 200
            snap_cap = r_snap.json()["capture"]
            snap_path = Path(snap_cap["local_path"])
            assert snap_path.parent == downloads_dir
            assert snap_path.read_bytes() == frame

            # Pull latest primary item (ignores GX010001.THM even though its mod_time is higher)
            r_latest = http.post("/api/media/pull", json={})
            assert r_latest.status_code == 200
            assert r_latest.json()["capture"]["filename"] == "GOPR0002.JPG"
            assert (downloads_dir / "GOPR0002.JPG").exists()

            # Pull named item
            r_named = http.post("/api/media/pull", json={"filename": "gx010001.mp4"})
            assert r_named.status_code == 200
            assert r_named.json()["capture"]["filename"] == "GX010001.MP4"
            assert (downloads_dir / "GX010001.MP4").exists()

            # Missing named item -> 400
            r_missing = http.post("/api/media/pull", json={"filename": "DOES_NOT_EXIST.MP4"})
            assert r_missing.status_code == 400
            assert r_missing.json()["ok"] is False


# ---------------------------------------------------------------------------
# Presets, Settings, Preview Controls, Validation, Errors, CORS
# ---------------------------------------------------------------------------


def test_presets_settings_and_preview_controls(tmp_path: Path):
    server, controller, client, _, _, _ = _build_harness(tmp_path, start_stream=False)

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            # Valid preset load
            r_preset = http.post("/api/preset/load", json={"preset_id": 42})
            assert r_preset.status_code == 200
            assert r_preset.json() == {"ok": True, "preset_id": 42}
            client.load_preset.assert_called_with(42)

            # Invalid preset load bodies
            for bad in [{}, {"preset_id": True}, {"preset_id": "42"}]:
                r_bad = http.post("/api/preset/load", json=bad)
                assert r_bad.status_code == 400

            # Setting by alias & numeric
            r_alias = http.post("/api/setting", json={"setting": "fps", "value": 8})
            assert r_alias.status_code == 200
            alias_payload = r_alias.json()
            assert alias_payload["ok"] is True
            assert alias_payload["setting_id"] == 3
            assert alias_payload["value"] == 8
            assert alias_payload["capabilities"]["model"] == "HERO12 Black"
            assert alias_payload["capabilities"]["settings"]["fps"]["current"] == 8
            client.set_setting.assert_called_with(3, 8)

            r_num = http.post("/api/setting", json={"setting": 121, "value": 4})
            assert r_num.status_code == 200
            num_payload = r_num.json()
            assert num_payload["ok"] is True
            assert num_payload["setting_id"] == 121
            assert num_payload["value"] == 4
            assert num_payload["capabilities"]["settings"]["fov"]["current"] == 4

            for bad in [
                {},
                {"setting": "fps"},
                {"value": 5},
                {"setting": "unknown_key", "value": 5},
                {"setting": "fps", "value": True},
                {"setting": "fps", "value": "8"},
            ]:
                r_bad = http.post("/api/setting", json=bad)
                assert r_bad.status_code == 400

            # Preview start & stop
            r_start = http.post("/api/preview/start", json={})
            assert r_start.status_code == 200
            assert r_start.json()["running"] is True
            assert controller._stream_enabled is True

            r_stop = http.post("/api/preview/stop", json={})
            assert r_stop.status_code == 200
            assert r_stop.json()["running"] is False
            assert controller._stream_enabled is False
            client.stop_preview_stream.assert_called()


def test_request_validation_404_and_error_mapping(tmp_path: Path):
    server, controller, client, state_box, _, _ = _build_harness(
        tmp_path, start_stream=False
    )

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            # Unknown routes -> 404
            assert http.get("/nonexistent").status_code == 404
            assert http.post("/api/nonexistent", json={}).status_code == 404

            # Malformed JSON -> 400
            r_malformed = http.post(
                "/api/shutter/start",
                content=b"{not-valid-json",
                headers={"Content-Type": "application/json"},
            )
            assert r_malformed.status_code == 400

            # Non-object JSON -> 400
            r_array = http.post("/api/shutter/start", json=[1, 2, 3])
            assert r_array.status_code == 400

            # Body > 64KB -> 400
            oversized = b'{"x":"' + (b"a" * (MAX_JSON_BODY_BYTES + 100)) + b'"}'
            r_huge = http.post(
                "/api/shutter/start",
                content=oversized,
                headers={"Content-Type": "application/json"},
            )
            assert r_huge.status_code == 400

            # TransportError -> 502
            client.shutter_start.side_effect = TransportError("USB disconnected")
            r_502 = http.post("/api/shutter/start", json={})
            assert r_502.status_code == 502
            assert "USB disconnected" in r_502.json()["error"]

            # MediaError I/O failure -> 500
            state_box["media"] = [
                MediaItem(
                    directory="100GOPRO",
                    filename="GX010001.MP4",
                    size_bytes=100,
                    media_type=MediaType.VIDEO,
                )
            ]
            controller.captures._download_fn = MagicMock(
                side_effect=OSError("disk full")
            )
            r_500 = http.post("/api/media/pull", json={})
            assert r_500.status_code == 500
            assert r_500.json()["ok"] is False


def test_cors_headers_enabled_vs_disabled(tmp_path: Path):
    srv_no_cors, _, _, _, _, _ = _build_harness(
        tmp_path / "nocors", cors_origin=None, start_stream=False
    )
    with srv_no_cors:
        with httpx.Client(base_url=srv_no_cors.url, timeout=5.0) as http:
            r_get = http.get("/api/status")
            assert "access-control-allow-origin" not in r_get.headers
            r_opt = http.options("/api/status")
            assert r_opt.status_code == 204
            assert "access-control-allow-origin" not in r_opt.headers

    srv_cors, _, _, _, _, _ = _build_harness(
        tmp_path / "cors", cors_origin="http://localhost:3000", start_stream=False
    )
    with srv_cors:
        with httpx.Client(base_url=srv_cors.url, timeout=5.0) as http:
            r_get = http.get("/api/status")
            assert r_get.headers["access-control-allow-origin"] == "http://localhost:3000"

            r_post = http.post("/api/shutter/start", json={})
            assert r_post.headers["access-control-allow-origin"] == "http://localhost:3000"

            r_opt = http.options("/api/preset/load")
            assert r_opt.status_code == 204
            assert r_opt.headers["access-control-allow-origin"] == "http://localhost:3000"
            assert "POST" in r_opt.headers["access-control-allow-methods"]
            assert "Content-Type" in r_opt.headers["access-control-allow-headers"]


# ---------------------------------------------------------------------------
# Lifecycle & Non-hanging Shutdown During Active MJPEG Stream
# ---------------------------------------------------------------------------


def test_shutdown_does_not_hang_with_active_mjpeg_consumer(tmp_path: Path):
    frame = _make_jpeg(b"live-frame")
    server, _, _, _, _, _ = _build_harness(
        tmp_path,
        start_stream=True,
        initial_frames=[frame],
    )
    server.start_in_thread()

    first_frame_seen = threading.Event()
    client_done = threading.Event()
    client_errors: list[Exception] = []

    def _consume_stream() -> None:
        try:
            with httpx.Client(base_url=server.url, timeout=5.0) as http:
                with http.stream("GET", "/stream.mjpeg") as resp:
                    buf = bytearray()
                    for chunk in resp.iter_bytes():
                        buf.extend(chunk)
                        if frame in buf:
                            first_frame_seen.set()
        except Exception as exc:
            client_errors.append(exc)
        finally:
            client_done.set()

    try:
        reader = threading.Thread(target=_consume_stream, daemon=True)
        reader.start()
        assert first_frame_seen.wait(timeout=3.0)

        t0 = time.monotonic()
        server.shutdown()
        elapsed = time.monotonic() - t0
        assert elapsed < 3.0

        # Idempotent second shutdown also returns immediately
        server.shutdown()
        assert client_done.wait(timeout=3.0)
        assert not client_errors
    finally:
        server.shutdown()


def test_shutdown_without_start_and_keep_alive_loop(tmp_path: Path):
    server, controller, client, _, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
        keep_alive_interval=0.05,
    )
    # Unstarted shutdown does not hang
    srv_unstarted, _, _, _, _, _ = _build_harness(
        tmp_path / "unused", start_stream=False
    )
    srv_unstarted.shutdown()

    with server:
        deadline = time.monotonic() + 2.0
        while client.keep_alive.call_count < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert client.keep_alive.call_count >= 2
    assert controller._keep_alive_thread is None


def test_start_in_thread_cleans_up_socket_on_controller_start_failure(tmp_path: Path):
    server, controller, _, _, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
        keep_alive_interval=0.05,
    )
    controller.start = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    controller.stop = MagicMock(wraps=controller.stop)  # type: ignore[method-assign]
    server._httpd.server_close = MagicMock(wraps=server._httpd.server_close)  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom"):
        server.start_in_thread()

    controller.stop.assert_called_once()
    server._httpd.server_close.assert_called_once()
    server.shutdown()


def test_serve_forever_cleans_up_on_controller_start_failure(tmp_path: Path):
    server, controller, _, _, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
    )
    controller.start = MagicMock(side_effect=RuntimeError("boom-forever"))  # type: ignore[method-assign]
    controller.stop = MagicMock(wraps=controller.stop)  # type: ignore[method-assign]
    server._httpd.server_close = MagicMock(wraps=server._httpd.server_close)  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boom-forever"):
        server.serve_forever()

    controller.stop.assert_called_once()
    server._httpd.server_close.assert_called_once()
    server.shutdown()


def test_get_state_stale_status_and_status_error_do_not_clobber_recording_timer(tmp_path: Path):
    server, controller, client, state_box, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
    )

    try:
        # 1. Stale not-recording status fetched before start_recording() must not wipe timer
        in_poll = threading.Event()
        release_poll = threading.Event()

        def _slow_status():
            in_poll.set()
            assert release_poll.wait(timeout=3.0)
            return CameraStatus(connected=True, is_recording=False)

        client.get_status.side_effect = _slow_status
        poll_result: list[dict[str, Any]] = []

        t = threading.Thread(target=lambda: poll_result.append(controller.get_state()), daemon=True)
        t.start()
        assert in_poll.wait(timeout=3.0)

        controller.start_recording()
        started_at = controller._recording_started_at
        assert started_at is not None

        release_poll.set()
        t.join(timeout=3.0)
        assert len(poll_result) == 1
        assert poll_result[0]["recording_elapsed_sec"] == 0.0
        assert controller._recording_started_at == started_at

        # 2. Transient status_error while recording must not wipe timer
        client.get_status.side_effect = TransportError("blip")
        err_state = controller.get_state()
        assert err_state["status"]["connected"] is False
        assert "blip" in err_state["status_error"]
        assert controller._recording_started_at == started_at

        # 3. Once status succeeds again with is_recording=True, elapsed continues counting
        state_box["status"] = CameraStatus(connected=True, is_recording=True)
        client.get_status.side_effect = lambda: state_box["status"]
        ok_state = controller.get_state()
        assert ok_state["recording_elapsed_sec"] >= 0.0
        assert controller._recording_started_at == started_at
    finally:
        server.shutdown()


def test_concurrent_get_state_and_recording_toggles_no_race(tmp_path: Path):
    server, controller, client, state_box, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
    )

    errors: list[BaseException] = []
    stop_flag = threading.Event()

    def _poller() -> None:
        try:
            while not stop_flag.is_set():
                res = controller.get_state()
                assert isinstance(res["recording_elapsed_sec"], float)
                assert res["recording_elapsed_sec"] >= 0.0
        except BaseException as exc:
            errors.append(exc)

    def _toggler() -> None:
        try:
            for _ in range(40):
                state_box["status"] = CameraStatus(connected=True, is_recording=True)
                controller.start_recording()
                state_box["status"] = CameraStatus(connected=True, is_recording=False)
                controller.stop_recording(auto_download=False)
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop_flag.set()

    try:
        pollers = [threading.Thread(target=_poller, daemon=True) for _ in range(3)]
        for p in pollers:
            p.start()
        toggler = threading.Thread(target=_toggler, daemon=True)
        toggler.start()
        toggler.join(timeout=5.0)
        for p in pollers:
            p.join(timeout=5.0)
        assert not errors
    finally:
        server.shutdown()


@pytest.mark.parametrize(
    "bad_origin",
    ["", "   ", "http://localhost\r\nX-Injected: 1", "http://bad\norigin", "http://bad\x00origin"],
)
def test_cors_origin_validation_rejects_invalid_values(tmp_path: Path, bad_origin: str):
    with pytest.raises(ValueError, match="Invalid cors_origin"):
        _build_harness(tmp_path, cors_origin=bad_origin, start_stream=False)


def test_serve_forever_normal_run_and_double_start_guards(tmp_path: Path):
    server, _, _, _, _, _ = _build_harness(tmp_path, start_stream=False)
    thread_errors: list[BaseException] = []

    def _run_forever() -> None:
        try:
            server.serve_forever()
        except BaseException as exc:
            thread_errors.append(exc)

    t = threading.Thread(target=_run_forever, daemon=True)
    try:
        t.start()
        deadline = time.monotonic() + 3.0
        while not server._serving and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server._serving is True

        # Serving requests while serve_forever() is active
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            resp = http.get("/api/status")
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

        # Double-start guards while serve_forever() is running
        with pytest.raises(RuntimeError, match="already running"):
            server.serve_forever()
        with pytest.raises(RuntimeError, match="already running"):
            server.start_in_thread()

        server.shutdown()
        t.join(timeout=3.0)
        assert not t.is_alive()
        assert not thread_errors

        # Closed guard after shutdown
        with pytest.raises(RuntimeError, match="already been shut down"):
            server.serve_forever()
    finally:
        server.shutdown()

    # serve_forever() also rejects when start_in_thread() is active
    srv2, _, _, _, _, _ = _build_harness(tmp_path / "srv2", start_stream=False)
    with srv2:
        with pytest.raises(RuntimeError, match="already running"):
            srv2.serve_forever()


def test_truncated_body_and_transfer_encoding_return_400(tmp_path: Path):
    server, _, _, _, _, _ = _build_harness(tmp_path, start_stream=False)

    def _send_raw(raw_request: bytes) -> bytes:
        with socket.create_connection((server.host, server.port), timeout=5.0) as sock:
            sock.sendall(raw_request)
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
            return b"".join(chunks)

    with server:
        truncated_req = (
            b"POST /api/shutter/start HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 50\r\n"
            b"Connection: close\r\n\r\n"
            b"{}"
        )
        truncated_resp = _send_raw(truncated_req).decode("utf-8", errors="replace")
        assert truncated_resp.startswith("HTTP/1.1 400 ")
        assert "Incomplete request body" in truncated_resp

        te_req = (
            b"POST /api/shutter/start HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json\r\n"
            b"Transfer-Encoding: gzip\r\n"
            b"Connection: close\r\n\r\n"
            b"{}"
        )
        te_resp = _send_raw(te_req).decode("utf-8", errors="replace")
        assert te_resp.startswith("HTTP/1.1 400 ")
        assert "Transfer-Encoding without Content-Length" in te_resp


def test_stop_recording_auto_download_false_skips_baseline_snapshot(tmp_path: Path):
    server, controller, client, _, _, _ = _build_harness(tmp_path, start_stream=False)

    try:
        client.get_media_list.reset_mock()
        result = controller.stop_recording(auto_download=False)
        assert result == {
            "ok": True,
            "recording": False,
            "download_queued": False,
            "job_id": None,
        }
        client.shutter_stop.assert_called_once()
        client.get_media_list.assert_not_called()
    finally:
        server.shutdown()


def test_pull_latest_media_empty_sd_and_capture_photo_errors(tmp_path: Path):
    server, controller, client, state_box, _, _ = _build_harness(tmp_path, start_stream=False)

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            # Empty SD card -> 400
            state_box["media"] = []
            r_empty = http.post("/api/media/pull", json={})
            assert r_empty.status_code == 400
            assert r_empty.json()["ok"] is False
            assert "No photo or video media" in r_empty.json()["error"]

            # No photo preset when auto_switch=True -> 400
            state_box["presets"] = {
                "presetGroupArray": [
                    {"id": "PRESET_GROUP_ID_VIDEO", "presetArray": [{"id": 0}]}
                ]
            }
            r_no_preset = http.post("/api/photo", json={"auto_switch": True})
            assert r_no_preset.status_code == 400
            assert r_no_preset.json()["ok"] is False
            assert "No Photo preset available" in r_no_preset.json()["error"]

            # Post-preset-switch shutter_start failure still re-arms preview if stream enabled
            state_box["presets"] = _sample_presets()
            assert http.post("/api/preview/start", json={}).status_code == 200
            client.start_preview_stream.reset_mock()
            client.shutter_start.side_effect = TransportError("shutter failed")
            r_fail = http.post("/api/photo", json={"auto_switch": True})
            assert r_fail.status_code == 502
            client.load_preset.assert_called_with(65536)
            client.start_preview_stream.assert_called_once()


def test_controller_stop_prevents_subsequent_start_and_start_preview(tmp_path: Path):
    server, controller, client, _, _, _ = _build_harness(
        tmp_path,
        start_stream=False,
        keep_alive_interval=0.05,
    )

    try:
        controller.start(start_stream=False)
        controller.stop()

        with pytest.raises(CommandError, match="stopped"):
            controller.start(start_stream=True)

        with pytest.raises(CommandError, match="stopped"):
            controller.start_preview()

        assert controller._keep_alive_thread is None
        assert controller.transcoder.status()["running"] is False
        client.start_preview_stream.assert_not_called()
    finally:
        server.shutdown()


def test_live_controller_model_override_and_dependent_capabilities(tmp_path: Path):
    client = MagicMock(spec=GoProRestClient)
    client.get_camera_info.side_effect = TransportError("404 on HERO10")
    state_box: dict[str, Any] = {
        "status": CameraStatus(connected=True, current_mode="Video"),
        "raw_state": {"settings": {"2": 1, "3": 6, "121": 3, "134": 3, "135": 100}},
        "presets": _sample_presets(),
        "media": [],
    }
    client.get_status.side_effect = lambda: state_box["status"]
    client.get_raw_state.side_effect = lambda: state_box["raw_state"]
    client.get_presets.side_effect = lambda: state_box["presets"]
    client.get_media_list.side_effect = lambda: list(state_box["media"])

    def fake_set_setting(sid: int, val: int) -> None:
        state_box["raw_state"]["settings"][str(sid)] = val
        if sid == 134 and val == 2 and state_box["raw_state"]["settings"].get("3") == 6:
            state_box["raw_state"]["settings"]["3"] = 5

    client.set_setting.side_effect = fake_set_setting

    transcoder = MjpegStreamTranscoder(
        stream_url="udp://@0.0.0.0:8554",
        popen_factory=lambda cmd, **kw: _PipeFakeProcess(),
        restart_delay_sec=0.05,
    )
    controller = LiveCameraController(
        client=client,
        info=CameraInfo(model_name="GoPro (USB CDC-ECM)", ip_address="172.20.10.51"),
        downloads_dir=tmp_path / "Downloads",
        transcoder=transcoder,
        keep_alive_interval=0.0,
        model_override="hero10",
    )
    server = LiveFeedServer(
        controller,
        host="127.0.0.1",
        port=0,
        start_stream=False,
    )
    with server:
        assert controller.info.model_name == "HERO10 Black"
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            caps_50 = http.get("/api/capabilities").json()
            assert caps_50["ok"] is True
            assert caps_50["model"] == "HERO10 Black"
            assert caps_50["anti_flicker_hz"] == 50
            assert "bitrate" not in caps_50["settings"]
            assert [o["value"] for o in caps_50["settings"]["fps"]["options"]] == [2, 6, 9, 10]

            # Switching anti_flicker to 60 Hz returns updated 60Hz FPS options immediately
            r_set = http.post("/api/setting", json={"setting": "anti_flicker", "value": 2})
            assert r_set.status_code == 200
            caps_60 = r_set.json()["capabilities"]
            assert caps_60["anti_flicker_hz"] == 60
            assert [o["value"] for o in caps_60["settings"]["fps"]["options"]] == [1, 5, 8, 10]

            # Fallback when get_raw_state fails after set_setting succeeds
            client.get_raw_state.side_effect = TransportError("transient state blip")
            r_set_fb = http.post("/api/setting", json={"setting": "resolution", "value": 4})
            assert r_set_fb.status_code == 200
            fb_payload = r_set_fb.json()
            assert fb_payload["ok"] is True
            assert fb_payload["setting_id"] == 2
            assert fb_payload["value"] == 4
            assert fb_payload["capabilities"]["model"] == "HERO10 Black"
            assert fb_payload["capabilities"]["settings"]["resolution"]["current"] == 4


def test_live_controller_default_fps_and_mjpeg_tcp_nodelay(tmp_path: Path):
    client = MagicMock(spec=GoProRestClient)
    default_ctrl = LiveCameraController(
        client=client,
        info=CameraInfo(model_name="HERO10 Black"),
        downloads_dir=tmp_path / "Downloads",
        keep_alive_interval=0.0,
    )
    assert default_ctrl.transcoder.fps == 30
    assert default_ctrl.transcoder.read_chunk_size == 8192

    frame = _make_jpeg(b"nodelay-frame")
    server, _, _, _, _, _ = _build_harness(
        tmp_path,
        start_stream=True,
        initial_frames=[frame],
    )
    accepted: list[socket.socket] = []
    orig_get_request = server._httpd.get_request

    def recording_get_request():
        conn, addr = orig_get_request()
        accepted.append(conn)
        return conn, addr

    server._httpd.get_request = recording_get_request  # type: ignore[method-assign]

    with server:
        with httpx.Client(base_url=server.url, timeout=5.0) as http:
            with http.stream("GET", "/stream.mjpeg") as stream_resp:
                assert stream_resp.status_code == 200
                buf = bytearray()
                for chunk in stream_resp.iter_bytes():
                    buf.extend(chunk)
                    if frame in buf:
                        assert accepted
                        assert accepted[-1].getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY) != 0
                        break


def test_start_preview_recovers_from_409_by_stopping_and_retrying(tmp_path: Path):
    client = MagicMock(spec=GoProRestClient)
    calls: list[str] = []

    def start_side_effect():
        calls.append("start")
        if calls.count("start") == 1:
            raise CommandError("HTTP 409 Conflict: stream already active")

    def stop_side_effect():
        calls.append("stop")

    client.start_preview_stream.side_effect = start_side_effect
    client.stop_preview_stream.side_effect = stop_side_effect

    transcoder = MjpegStreamTranscoder(
        stream_url="udp://@0.0.0.0:8554",
        popen_factory=lambda cmd, **kw: _PipeFakeProcess(),
        restart_delay_sec=0.05,
    )
    controller = LiveCameraController(
        client=client,
        info=CameraInfo(model_name="HERO10 Black"),
        downloads_dir=tmp_path / "Downloads",
        transcoder=transcoder,
        keep_alive_interval=0.0,
    )
    try:
        res = controller.start_preview()
        assert res["ok"] is True
        assert res["running"] is True
        assert calls == ["start", "stop", "start"]

        # Also verify _best_effort_restart_preview recovers from 409
        calls.clear()
        controller._best_effort_restart_preview()
        assert calls == ["start", "stop", "start"]

        # Non-409 CommandError does not invoke stop_preview_stream
        calls.clear()
        client.start_preview_stream.side_effect = CommandError("HTTP 500 Internal Error")
        controller._best_effort_restart_preview()
        assert calls == []
        client.stop_preview_stream.assert_called()
        assert client.stop_preview_stream.call_count == 2
    finally:
        controller.stop()


