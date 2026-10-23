from pathlib import Path
from uel_gopro.core.config import UelConfig, load_config, save_config


def test_config_save_and_load(tmp_path: Path):
    cfg_file = tmp_path / "config.json"
    cfg = UelConfig(
        default_download_dir="/tmp/test_gopro",
        default_transport="usb",
        custom_camera_ip="172.24.162.51",
    )
    save_config(cfg, cfg_file)
    assert cfg_file.exists()

    loaded = load_config(cfg_file)
    assert loaded.default_download_dir == "/tmp/test_gopro"
    assert loaded.default_transport == "usb"
    assert loaded.custom_camera_ip == "172.24.162.51"


def test_config_missing_file(tmp_path: Path):
    missing_file = tmp_path / "does_not_exist.json"
    loaded = load_config(missing_file)
    assert loaded.default_transport == "auto"
