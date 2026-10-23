from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "uel-gopro"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.json"


class UelConfig(BaseModel):
    default_download_dir: str = str(Path.home() / "Movies" / "GoPro")
    default_transport: str = "auto"
    custom_camera_ip: Optional[str] = None
    stream_player: str = "mpv"
    preferred_webcam_res: str = "1080p"


def load_config(path: Path = DEFAULT_CONFIG_FILE) -> UelConfig:
    """Loads configuration from file or returns default."""
    if path.exists():
        try:
            return UelConfig.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return UelConfig()
    return UelConfig()


def save_config(config: UelConfig, path: Path = DEFAULT_CONFIG_FILE) -> None:
    """Saves configuration to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.model_dump_json(indent=2), encoding="utf-8")
