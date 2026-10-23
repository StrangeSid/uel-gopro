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
