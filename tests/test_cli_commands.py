from unittest.mock import MagicMock
import pytest
from typer.testing import CliRunner

from uel_gopro.cli.main import app
from uel_gopro.api.rest import GoProRestClient

runner = CliRunner()


def test_cli_config_get(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_raw_state.return_value = {"settings": {"2": 1, "3": 5}}
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    # Test get all
    result = runner.invoke(app, ["config", "get"])
    assert result.exit_code == 0
    assert "GoPro Active Settings" in result.stdout

    # Test get specific alias
    result_res = runner.invoke(app, ["config", "get", "resolution"])
    assert result_res.exit_code == 0
    assert "resolution = 1" in result_res.stdout


def test_cli_config_set(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    result = runner.invoke(app, ["config", "set", "resolution", "4"])
    assert result.exit_code == 0
    mock_client.set_setting.assert_called_once_with(2, 4)


def test_cli_preset_list_and_load(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    mock_client.get_presets.return_value = {
        "presetGroupArray": [
            {
                "presets": [
                    {"id": 1000, "title": "Standard", "userDefined": 0},
                    {"id": 1001, "title": "Cinematic", "userDefined": 1},
                ]
            }
        ]
    }
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    # List
    res_list = runner.invoke(app, ["preset", "list"])
    assert res_list.exit_code == 0
    assert "Standard" in res_list.stdout
    assert "Cinematic" in res_list.stdout

    # Load
    res_load = runner.invoke(app, ["preset", "load", "1001"])
    assert res_load.exit_code == 0
    mock_client.load_preset.assert_called_once_with(1001)


def test_cli_media_delete(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    # Test force delete
    res = runner.invoke(app, ["media", "delete", "GX010042.MP4", "--force"])
    assert res.exit_code == 0
    mock_client.delete_file.assert_called_once_with(directory="100GOPRO", filename="GX010042.MP4")


def test_cli_media_format_safeguards(monkeypatch):
    mock_client = MagicMock(spec=GoProRestClient)
    monkeypatch.setattr("uel_gopro.cli.main.resolve_camera", lambda **kw: (MagicMock(), mock_client))

    # Without --confirm -> exit code 1
    res_fail = runner.invoke(app, ["media", "format"])
    assert res_fail.exit_code == 1
    assert "Safety Check" in res_fail.output


def test_cli_discover_ble(monkeypatch):
    class MockBleDevice:
        name = "GoPro Hero 11"
        address = "AA:BB:CC:DD:EE:FF"

    import asyncio
    async def mock_scan(**kw):
        return [MockBleDevice()]

    monkeypatch.setattr("uel_gopro.cli.main.detect_usb_camera", lambda **kw: None)
    monkeypatch.setattr("uel_gopro.transport.ble.GoProBleClient.scan", mock_scan)

    res = runner.invoke(app, ["discover", "--ble"])
    assert res.exit_code == 0
    assert "GoPro Hero 11" in res.stdout
    assert "AA:BB:CC:DD:EE:FF" in res.stdout


def test_cli_cloud_auth_and_list(tmp_path, monkeypatch):
    # Mock auth save
    saved = {}
    monkeypatch.setattr("uel_gopro.cloud.client.save_cloud_auth", lambda token, user_id="": saved.update({"token": token, "user_id": user_id}))

    res_auth = runner.invoke(app, ["cloud", "auth", "--token", "fake_token_123", "--user-id", "user_456"])
    assert res_auth.exit_code == 0
    assert saved == {"token": "fake_token_123", "user_id": "user_456"}

    # Mock list
    class MockCloudClient:
        def list_media(self, page=1, per_page=25):
            return [
                {
                    "id": "asset_001",
                    "filename": "GX010042.MP4",
                    "type": "video",
                    "captured_at": "2026-10-23T12:00:00Z",
                    "file_size": 104857600,
                }
            ]

    monkeypatch.setattr("uel_gopro.cloud.client.GoProCloudClient", MockCloudClient)

    res_list = runner.invoke(app, ["cloud", "list"])
    assert res_list.exit_code == 0
    assert "GX010042.MP4" in res_list.stdout
    assert "asset_001" in res_list.stdout
