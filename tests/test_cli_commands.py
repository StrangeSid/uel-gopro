import json
from unittest.mock import MagicMock

from typer.testing import CliRunner

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.cli.main import app
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

    result = runner.invoke(app, ["config", "set", "resolution", "4"])
    assert result.exit_code == 0
    mock_client.set_setting.assert_called_once_with(2, 4)


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
