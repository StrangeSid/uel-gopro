import json
import re
from unittest.mock import MagicMock
import webbrowser

from typer.testing import CliRunner

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.cli.main import SETTING_ALIASES, app
from uel_gopro.core.exceptions import CommandError
from uel_gopro.core.models import CameraInfo, CameraStatus, MediaItem, MediaType

runner = CliRunner()


def test_cli_config_get_and_list(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_raw_state.return_value = {"settings": {"2": 1, "3": 5}}
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    result = runner.invoke(app, ["config", "get"])
    assert result.exit_code == 0
    assert "GoPro Active Settings" in result.stdout

    result_list = runner.invoke(app, ["config", "list"])
    assert result_list.exit_code == 0
    assert "GoPro Active Settings" in result_list.stdout

    result_res = runner.invoke(app, ["config", "get", "resolution"])
    assert result_res.exit_code == 0
    assert "resolution = 1" in result_res.stdout


def test_cli_config_set(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    assert SETTING_ALIASES["resolution"] == 2
    assert SETTING_ALIASES["res"] == 2
    assert SETTING_ALIASES["framerate"] == 3
    assert SETTING_ALIASES["lens"] == 121

    result = runner.invoke(app, ["config", "set", "resolution", "4"])
    assert result.exit_code == 0
    mock_client.set_setting.assert_called_once_with(2, 4)

    bad = runner.invoke(app, ["config", "set", "nonexistent", "4"])
    assert bad.exit_code == 1
    assert "Unknown setting" in bad.output


def test_cli_preset_list_current_schema_and_load(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_presets.return_value = {
        "presetGroupArray": [
            {
                "id": "PRESET_GROUP_ID_VIDEO",
                "presetArray": [
                    {"id": 1000, "titleId": "PRESET_TITLE_STANDARD", "userDefined": False},
                    {"id": 1001, "titleId": "PRESET_TITLE_CINEMATIC", "userDefined": True},
                ],
            }
        ]
    }
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    result = runner.invoke(app, ["preset", "list"])
    assert result.exit_code == 0
    assert "Video / Standard" in result.stdout
    assert "Video / Cinematic" in result.stdout
    assert "User" in result.stdout

    result_load = runner.invoke(app, ["preset", "load", "1001"])
    assert result_load.exit_code == 0
    mock_client.load_preset.assert_called_once_with(1001)


def test_cli_status_json_includes_camera_and_corrected_status(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_status.return_value = CameraStatus(
        battery_percent=36,
        battery_bars=4,
        is_charging=True,
        sd_status="OK",
        sd_remaining_mb=25029,
        current_mode="Video",
        current_preset="2",
    )
    mock_client.get_camera_info.return_value = {
        "model_name": "HERO12 Black",
        "firmware_version": "H23.01.01.10.00",
        "serial_number": "C3501324645504",
    }
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(model_name="GoPro (USB)"), mock_client),
    )

    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["camera"]["model_name"] == "HERO12 Black"
    assert payload["status"]["battery_percent"] == 36
    assert payload["status"]["battery_bars"] == 4
    assert payload["status"]["sd_remaining_mb"] == 25029


def test_cli_status_ble_with_camera_status_json_and_panel(monkeypatch):
    class MockBleDevice:
        name = "GoPro 2108"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    calls = {"connected": 0, "disconnected": 0}

    class FakeBleClient:
        def __init__(self, address=None):
            self.address = address
            self.is_connected = False

        async def connect(self):
            calls["connected"] += 1
            self.is_connected = True

        async def disconnect(self):
            calls["disconnected"] += 1
            self.is_connected = False

        async def get_battery_level(self):
            return 0  # Fallback to cam_status.battery_percent

        async def get_device_info(self):
            return {
                "manufacturer": "GoPro",
                "model": "HERO10 Black",
                "firmware": "H21.01.01.62.00",
                "serial": "C3461326122108",
            }

        async def get_camera_status(self):
            return CameraStatus(
                battery_percent=74,
                is_charging=True,
                is_recording=True,
                system_hot=False,
                sd_status="OK",
                sd_remaining_mb=12345,
                sd_remaining_photos=900,
                sd_remaining_video_time_sec=3661,
                current_mode="Video",
                current_preset="0",
            )

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res_json = runner.invoke(app, ["status", "--ble", "--json"])
    assert res_json.exit_code == 0
    payload = json.loads(res_json.stdout)
    assert payload["transport"] == "ble"
    assert payload["device_name"] == "GoPro 2108"
    assert payload["battery_percent"] == 74
    assert payload["model"] == "HERO10 Black"
    assert payload["status"]["sd_remaining_mb"] == 12345
    assert payload["status"]["current_mode"] == "Video"

    res_panel = runner.invoke(app, ["status", "--ble"])
    assert res_panel.exit_code == 0
    assert "74%" in res_panel.stdout
    assert "RECORDING" in res_panel.stdout
    assert "Video (preset 0)" in res_panel.stdout
    assert "12,345 MB free" in res_panel.stdout
    assert "900 photos / 1:01:01 video" in res_panel.stdout
    assert "Nominal" in res_panel.stdout
    assert calls == {"connected": 2, "disconnected": 2}


def test_cli_config_ble_list_get_set(monkeypatch):
    class MockBleDevice:
        name = "GoPro 2108"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    recorded = {"get_calls": [], "set_calls": []}

    class FakeBleClient:
        def __init__(self, address=None):
            self.address = address
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_settings(self, setting_ids=None):
            recorded["get_calls"].append(setting_ids)
            return {2: 9, 134: 2, 135: 3}

        async def set_setting(self, setting_id, value):
            recorded["set_calls"].append((setting_id, value))

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res_list = runner.invoke(app, ["config", "list", "--ble", "--json"])
    assert res_list.exit_code == 0
    assert json.loads(res_list.stdout) == {"2": 9, "134": 2, "135": 3}

    res_get = runner.invoke(app, ["config", "get", "anti_flicker", "--ble"])
    assert res_get.exit_code == 0
    assert "anti_flicker = 2" in res_get.stdout

    res_get_all = runner.invoke(app, ["config", "get", "--ble", "--json"])
    assert res_get_all.exit_code == 0
    assert json.loads(res_get_all.stdout) == {"2": 9, "134": 2, "135": 3}

    res_set = runner.invoke(app, ["config", "set", "hypersmooth", "3", "--ble"])
    assert res_set.exit_code == 0
    assert "hypersmooth (135) -> 3 over BLE" in res_set.stdout
    assert recorded["get_calls"] == [None, [134], None]
    assert recorded["set_calls"] == [(135, 3)]


def test_cli_status_ble_camera_status_fallback_to_none(monkeypatch):
    class MockBleDevice:
        name = "GoPro 2108"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    class FakeBleClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_battery_level(self):
            return 55

        async def get_device_info(self):
            return {
                "manufacturer": "GoPro",
                "model": "HERO10 Black",
                "firmware": "H21.01.01.62.00",
                "serial": "C3461326122108",
            }

        async def get_camera_status(self):
            raise RuntimeError("unsupported")

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res = runner.invoke(app, ["status", "--ble", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["battery_percent"] == 55
    assert payload["status"] is None


def test_cli_discover_ble_json_outputs_clean_json(monkeypatch):
    class MockBleDevice:
        name = None
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    monkeypatch.setattr("uel_gopro.cli.main.detect_usb_camera", lambda **kw: None)
    monkeypatch.setattr("uel_gopro.transport.mtp.is_mtp_available", lambda: False)
    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient.scan", mock_scan)

    res = runner.invoke(app, ["discover", "--ble", "--json"])
    assert res.exit_code == 0
    parsed = json.loads(res.stdout)
    assert parsed == [
        {
            "model_name": "GoPro BLE",
            "address": "AA:BB:CC:DD:EE:FF",
            "transport": "ble",
        }
    ]


def test_cli_status_ble_gatt_battery_error_and_none_name(monkeypatch):
    class MockBleDevice:
        name = None
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    class FakeBleClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_battery_level(self):
            raise RuntimeError("GATT battery unavailable")

        async def get_device_info(self):
            return {"manufacturer": "GoPro", "model": "HERO10", "firmware": "H21", "serial": "123"}

        async def get_camera_status(self):
            return CameraStatus(battery_percent=63)

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res = runner.invoke(app, ["status", "--ble", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["device_name"] == "GoPro"
    assert payload["battery_percent"] == 63


def test_cli_config_ble_connect_error_raises_transport_error_and_missing_setting(monkeypatch):
    from uel_gopro.core.exceptions import TransportError

    class MockBleDevice:
        name = "GoPro"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    class FailingConnectClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            raise RuntimeError("BleakError: failed to connect")

        async def disconnect(self):
            self.is_connected = False

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FailingConnectClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res_err = runner.invoke(app, ["config", "list", "--ble"])
    assert res_err.exit_code != 0
    assert isinstance(res_err.exception, TransportError)
    assert "BleakError" in str(res_err.exception)

    # Unknown setting name in config get exits with code 1
    res_unknown = runner.invoke(app, ["config", "get", "nonexistent", "--ble"])
    assert res_unknown.exit_code == 1
    assert "Unknown setting" in res_unknown.output

    # Valid setting ID missing from returned map exits 1 without corrupting JSON stdout
    class EmptySettingsClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_settings(self, setting_ids=None):
            return {}

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", EmptySettingsClient)
    res_missing = runner.invoke(app, ["config", "get", "resolution", "--ble", "--json"])
    assert res_missing.exit_code == 1
    assert res_missing.stdout == ""
    assert "not found or not active" in res_missing.output


def test_cli_media_delete(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    result = runner.invoke(app, ["media", "delete", "GX010042.MP4", "--force"])
    assert result.exit_code == 0
    mock_client.delete_file.assert_called_once_with(directory="100GOPRO", filename="GX010042.MP4")


def test_cli_media_download_treats_missing_dest_as_directory(tmp_path, monkeypatch):
    item = MediaItem(
        directory="100GOPRO",
        filename="GX010042.MP4",
        size_bytes=100,
        media_type=MediaType.VIDEO,
    )
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_media_list.return_value = [item]
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(), mock_client),
    )

    recorded = {}

    def fake_download(url, dest_path, **kwargs):
        recorded["url"] = url
        recorded["dest"] = dest_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"x")
        return dest_path

    monkeypatch.setattr("uel_gopro.cli.main.download_file", fake_download)
    destination = tmp_path / "GoProVideos"  # does not exist and has no suffix

    result = runner.invoke(
        app,
        ["media", "download", "GX010042.MP4", "--dest", str(destination)],
    )
    assert result.exit_code == 0
    assert destination.is_dir()
    assert recorded["dest"] == destination / "GX010042.MP4"
    assert recorded["url"].endswith("/videos/DCIM/100GOPRO/GX010042.MP4")


def test_cli_record_photo_requires_photo_mode(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_status.return_value = CameraStatus(current_mode="Video")
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    result = runner.invoke(app, ["record", "photo"])
    assert result.exit_code == 1
    assert "Photo preset" in result.output
    mock_client.shutter_start.assert_not_called()

    forced = runner.invoke(app, ["record", "photo", "--force"])
    assert forced.exit_code == 0
    mock_client.shutter_start.assert_called_once()


def test_cli_discover_ble(monkeypatch):
    class MockBleDevice:
        name = "GoPro Hero 11"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    monkeypatch.setattr("uel_gopro.cli.main.detect_usb_camera", lambda **kw: None)
    monkeypatch.setattr("uel_gopro.transport.mtp.is_mtp_available", lambda: False)
    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient.scan", mock_scan)

    result = runner.invoke(app, ["discover", "--ble"])
    assert result.exit_code == 0
    assert "GoPro Hero 11" in result.stdout
    assert "AA:BB:CC:DD:EE:FF" in result.stdout


def test_cli_cloud_auth_and_list(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        "uel_gopro.cloud.client.save_cloud_auth",
        lambda token, user_id="": saved.update({"token": token, "user_id": user_id}) or "/tmp/cloud.json",
    )

    result_auth = runner.invoke(
        app, ["cloud", "auth", "--token", "fake_token_123", "--user-id", "user_456"]
    )
    assert result_auth.exit_code == 0
    assert saved == {"token": "fake_token_123", "user_id": "user_456"}

    class MockCloudClient:
        def list_media(self, page=1, per_page=25):
            return [
                {
                    "id": "asset_001",
                    "filename": "GX010042.MP4",
                    "type": "video",
                    "captured_at": "2026-10-23T12:00:00Z",
                    "file_size": "104857600",
                }
            ]

    monkeypatch.setattr("uel_gopro.cloud.client.GoProCloudClient", MockCloudClient)

    result_list = runner.invoke(app, ["cloud", "list"])
    assert result_list.exit_code == 0
    assert "GX010042.MP4" in result_list.stdout
    assert "asset_001" in result_list.stdout


def test_cli_stream_live_help_shows_all_options():
    result = runner.invoke(app, ["stream", "live", "--help"])
    assert result.exit_code == 0
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    for flag in (
        "--ip",
        "--host",
        "--port",
        "--downloads-dir",
        "--stream-url",
        "--fps",
        "--open",
        "--no-open",
        "--cors-origin",
        "--ffmpeg",
        "--no-stream",
        "--model",
    ):
        assert flag in plain


def test_cli_stream_live_no_open_default_downloads_and_keyboard_interrupt(tmp_path, monkeypatch):
    mock_info = CameraInfo(model_name="HERO12 Black")
    mock_client = MagicMock(spec=GoProRestClient)
    resolve_calls = []

    def fake_resolve_camera(**kw):
        resolve_calls.append(kw)
        return mock_info, mock_client

    default_dl = tmp_path / "Downloads"
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", fake_resolve_camera)
    monkeypatch.setattr("uel_gopro.cli.main.default_downloads_dir", lambda: default_dl)

    created = {}

    class FakeController:
        def __init__(self, **kwargs):
            created["controller_kwargs"] = kwargs
            self.captures = MagicMock()
            self.captures.downloads_dir = kwargs["downloads_dir"]
            self.stop_calls = 0

        def stop(self):
            self.stop_calls += 1

    class FakeServer:
        def __init__(self, controller, **kwargs):
            created["server_controller"] = controller
            created["server_kwargs"] = kwargs
            self.url = f"http://{kwargs['host']}:{kwargs['port']}"
            self.embed_url = f"{self.url}/embed"
            self.widget_url = f"{self.url}/widget.js"
            self.stream_url = f"{self.url}/stream.mjpeg"
            self.serve_called = False
            self.shutdown_called = False
            created["server"] = self

        def serve_forever(self):
            self.serve_called = True
            raise KeyboardInterrupt()

        def shutdown(self):
            self.shutdown_called = True

    open_calls = []
    monkeypatch.setattr("uel_gopro.cli.main.LiveCameraController", FakeController)
    monkeypatch.setattr("uel_gopro.cli.main.LiveFeedServer", FakeServer)
    monkeypatch.setattr("uel_gopro.cli.main.webbrowser.open", lambda url: open_calls.append(url))

    result = runner.invoke(app, ["stream", "live", "--no-open"])
    assert result.exit_code == 0
    assert resolve_calls == [{"target_ip": None}]
    assert created["controller_kwargs"]["downloads_dir"] == default_dl
    assert created["controller_kwargs"]["fps"] == 30
    assert created["server_kwargs"]["start_stream"] is True
    assert open_calls == []
    assert created["server"].serve_called is True
    assert created["server"].shutdown_called is True

    compact_stdout = re.sub(r"[\s│]+", "", result.stdout)
    assert "http://127.0.0.1:8765" in compact_stdout
    assert "http://127.0.0.1:8765/embed" in compact_stdout
    assert "http://127.0.0.1:8765/widget.js" in compact_stdout
    assert "http://127.0.0.1:8765/stream.mjpeg" in compact_stdout
    assert str(default_dl) in compact_stdout
    assert "Press Ctrl+C to stop." in result.stdout
    assert "Stopping live camera feed..." in result.stdout


def test_cli_stream_live_open_custom_options_forwarded(tmp_path, monkeypatch):
    mock_info = CameraInfo(model_name="HERO12 Black")
    mock_client = MagicMock(spec=GoProRestClient)
    resolve_calls = []

    def fake_resolve_camera(**kw):
        resolve_calls.append(kw)
        return mock_info, mock_client

    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", fake_resolve_camera)

    custom_dl = tmp_path / "CustomCaptures"
    created = {}

    class FakeController:
        def __init__(self, **kwargs):
            created["controller_kwargs"] = kwargs
            self.captures = MagicMock()
            self.captures.downloads_dir = kwargs["downloads_dir"]

        def stop(self):
            pass

    class FakeServer:
        def __init__(self, controller, **kwargs):
            created["server_controller"] = controller
            created["server_kwargs"] = kwargs
            self.url = f"http://{kwargs['host']}:{kwargs['port']}"
            self.embed_url = f"{self.url}/embed"
            self.widget_url = f"{self.url}/widget.js"
            self.stream_url = f"{self.url}/stream.mjpeg"
            self.serve_called = False
            self.shutdown_called = False
            created["server"] = self

        def serve_forever(self):
            self.serve_called = True

        def shutdown(self):
            self.shutdown_called = True

    open_calls = []
    monkeypatch.setattr("uel_gopro.cli.main.LiveCameraController", FakeController)
    monkeypatch.setattr("uel_gopro.cli.main.LiveFeedServer", FakeServer)
    monkeypatch.setattr("uel_gopro.cli.main.webbrowser.open", lambda url: open_calls.append(url))

    result = runner.invoke(
        app,
        [
            "stream",
            "live",
            "--ip",
            "10.5.5.9",
            "--host",
            "0.0.0.0",
            "--port",
            "9123",
            "--downloads-dir",
            str(custom_dl),
            "--stream-url",
            "udp://0.0.0.0:8555",
            "--fps",
            "30",
            "--open",
            "--cors-origin",
            "http://localhost:3000",
            "--ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "--no-stream",
            "--model",
            "hero10",
        ],
    )
    assert result.exit_code == 0
    assert resolve_calls == [{"target_ip": "10.5.5.9"}]
    assert created["controller_kwargs"] == {
        "client": mock_client,
        "info": mock_info,
        "downloads_dir": custom_dl,
        "stream_url": "udp://0.0.0.0:8555",
        "ffmpeg_path": "/opt/homebrew/bin/ffmpeg",
        "fps": 30,
        "model_override": "hero10",
    }
    assert created["server_kwargs"] == {
        "host": "0.0.0.0",
        "port": 9123,
        "cors_origin": "http://localhost:3000",
        "start_stream": False,
    }
    assert open_calls == ["http://0.0.0.0:9123"]
    assert created["server"].serve_called is True
    assert created["server"].shutdown_called is True


def test_cli_stream_live_invalid_cors_raises_command_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(), MagicMock(spec=GoProRestClient)),
    )
    stopped = []

    class FakeController:
        def __init__(self, **kwargs):
            self.captures = MagicMock()
            self.captures.downloads_dir = kwargs["downloads_dir"]

        def stop(self):
            stopped.append(True)

    def failing_server(controller, **kwargs):
        raise ValueError("Invalid cors_origin")

    monkeypatch.setattr("uel_gopro.cli.main.LiveCameraController", FakeController)
    monkeypatch.setattr("uel_gopro.cli.main.LiveFeedServer", failing_server)

    result = runner.invoke(
        app,
        ["stream", "live", "--downloads-dir", str(tmp_path), "--cors-origin", " "],
    )
    assert result.exit_code != 0
    assert isinstance(result.exception, CommandError)
    assert "Invalid cors_origin" in str(result.exception)
    assert stopped == [True]


def test_cli_stream_live_browser_open_error_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(), MagicMock(spec=GoProRestClient)),
    )
    created = {}

    class FakeController:
        def __init__(self, **kwargs):
            self.captures = MagicMock()
            self.captures.downloads_dir = kwargs["downloads_dir"]

        def stop(self):
            pass

    class FakeServer:
        def __init__(self, controller, **kwargs):
            self.url = "http://127.0.0.1:8765"
            self.embed_url = f"{self.url}/embed"
            self.widget_url = f"{self.url}/widget.js"
            self.stream_url = f"{self.url}/stream.mjpeg"
            self.serve_called = False
            self.shutdown_called = False
            created["server"] = self

        def serve_forever(self):
            self.serve_called = True

        def shutdown(self):
            self.shutdown_called = True

    def raise_browser_error(url):
        raise webbrowser.Error("no runnable browser")

    monkeypatch.setattr("uel_gopro.cli.main.LiveCameraController", FakeController)
    monkeypatch.setattr("uel_gopro.cli.main.LiveFeedServer", FakeServer)
    monkeypatch.setattr("uel_gopro.cli.main.webbrowser.open", raise_browser_error)

    result = runner.invoke(app, ["stream", "live", "--downloads-dir", str(tmp_path), "--open"])
    assert result.exit_code == 0
    assert "Could not open browser automatically: no runnable browser" in result.output
    assert created["server"].serve_called is True
    assert created["server"].shutdown_called is True


def test_cli_stream_live_server_oserror_stops_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(), MagicMock(spec=GoProRestClient)),
    )
    stopped = []

    class FakeController:
        def __init__(self, **kwargs):
            self.captures = MagicMock()
            self.captures.downloads_dir = kwargs["downloads_dir"]

        def stop(self):
            stopped.append(True)

    def failing_server(controller, **kwargs):
        raise OSError("Address already in use")

    monkeypatch.setattr("uel_gopro.cli.main.LiveCameraController", FakeController)
    monkeypatch.setattr("uel_gopro.cli.main.LiveFeedServer", failing_server)

    result = runner.invoke(app, ["stream", "live", "--downloads-dir", str(tmp_path)])
    assert result.exit_code != 0
    assert isinstance(result.exception, OSError)
    assert "Address already in use" in str(result.exception)
    assert stopped == [True]


def test_cli_status_ble_normalizes_hex_model_id(monkeypatch):
    class MockBleDevice:
        name = "GoPro 2108"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    class FakeBleClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_battery_level(self):
            return 80

        async def get_device_info(self):
            return {
                "manufacturer": "GoPro",
                "model": "00000039",
                "firmware": "H21.01.01.62.00",
                "serial": "C3461326122108",
            }

        async def get_camera_status(self):
            return CameraStatus(battery_percent=80)

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res_panel = runner.invoke(app, ["status", "--ble"])
    assert res_panel.exit_code == 0
    assert "GoPro 2108 (HERO10 Black)" in res_panel.stdout
    assert "00000039" not in res_panel.stdout

    res_json = runner.invoke(app, ["status", "--ble", "--json"])
    assert res_json.exit_code == 0
    payload = json.loads(res_json.stdout)
    assert payload["model"] == "HERO10 Black"
    assert payload["model_id"] == "00000039"


def test_cli_config_capabilities_ble_and_http(monkeypatch):
    class MockBleDevice:
        name = "GoPro 2108"
        address = "AA:BB:CC:DD:EE:FF"

    async def mock_scan(**kwargs):
        return [MockBleDevice()]

    class FakeBleClient:
        def __init__(self, address=None):
            self.is_connected = False

        async def connect(self):
            self.is_connected = True

        async def disconnect(self):
            self.is_connected = False

        async def get_device_info(self):
            return {
                "manufacturer": "GoPro",
                "model": "00000039",
                "firmware": "H21.01.01.62.00",
                "serial": "C3461326122108",
            }

        async def get_settings(self, setting_ids=None):
            return {2: 1, 3: 6, 121: 3, 134: 3, 135: 100}

        async def get_available_settings(self, setting_ids=None):
            return {
                2: [1, 4, 100],
                3: [2, 6, 9, 10],
                121: [0, 2, 3, 4],
                134: [2, 3],
                135: [0, 3, 100],
            }

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FakeBleClient)
    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", mock_scan)

    res_ble_json = runner.invoke(app, ["config", "capabilities", "--ble", "--json"])
    assert res_ble_json.exit_code == 0
    ble_caps = json.loads(res_ble_json.stdout)
    assert ble_caps["model"] == "HERO10 Black"
    assert ble_caps["source"] == "camera_live"
    assert ble_caps["anti_flicker_hz"] == 50
    assert "bitrate" not in ble_caps["settings"]
    assert [o["value"] for o in ble_caps["settings"]["fov"]["options"]] == [0, 2, 3, 4]

    res_ble_table = runner.invoke(app, ["config", "capabilities", "--ble"])
    assert res_ble_table.exit_code == 0
    assert "HERO10 Black Valid Settings" in res_ble_table.stdout
    assert "camera_live" in res_ble_table.stdout
    assert "4K (16:9)" in res_ble_table.stdout
    assert "50 fps" in res_ble_table.stdout

    # HTTP path (e.g. HERO10 where /gopro/camera/info may fail, firmware/name unavailable or enriched)
    mock_client = MagicMock()
    mock_client.get_raw_state.return_value = {"settings": {"2": 100, "3": 6, "134": 3}}
    mock_client.get_camera_info.return_value = {"firmware_version": "H21.01.01.62.00"}
    monkeypatch.setattr(
        "uel_gopro.cli.main.resolve_camera",
        lambda **kw: (CameraInfo(model_name="GoPro (USB CDC-ECM)"), mock_client),
    )

    res_http_json = runner.invoke(app, ["config", "capabilities", "--json"])
    assert res_http_json.exit_code == 0
    http_caps = json.loads(res_http_json.stdout)
    assert http_caps["model"] == "HERO10 Black"
    assert http_caps["source"] == "model_matrix"
    assert http_caps["anti_flicker_hz"] == 50
    assert [o["value"] for o in http_caps["settings"]["fps"]["options"]] == [6, 9, 10]

    res_http_table = runner.invoke(app, ["config", "capabilities"])
    assert res_http_table.exit_code == 0
    assert "HERO10 Black Valid Settings" in res_http_table.stdout
    assert "model_matrix" in res_http_table.stdout

    # HTTP path using model_number from get_camera_info when firmware_version is absent
    mock_client.get_camera_info.return_value = {"model_number": 57}
    res_model_num = runner.invoke(app, ["config", "capabilities", "--json"])
    assert res_model_num.exit_code == 0
    assert json.loads(res_model_num.stdout)["model"] == "HERO10 Black"

    # BLE fallback when opcode 0x32 raises CommandError -> falls back to model_matrix
    class FallbackBleClient(FakeBleClient):
        async def get_available_settings(self, setting_ids=None):
            raise CommandError("0x32 unsupported")

    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient", FallbackBleClient)
    res_ble_fb = runner.invoke(app, ["config", "capabilities", "--ble", "--json"])
    assert res_ble_fb.exit_code == 0
    fb_caps = json.loads(res_ble_fb.stdout)
    assert fb_caps["model"] == "HERO10 Black"
    assert fb_caps["source"] == "model_matrix"

    # BLE error path when no cameras are discovered
    async def empty_scan(**kwargs):
        return []

    monkeypatch.setattr("uel_gopro.cli.main._scan_gopro_ble", empty_scan)
    res_ble_missing = runner.invoke(app, ["config", "capabilities", "--ble"])
    assert res_ble_missing.exit_code != 0
    assert "No GoPro cameras discovered over BLE" in str(res_ble_missing.exception)


