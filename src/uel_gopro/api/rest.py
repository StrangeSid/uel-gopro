from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from uel_gopro.core.exceptions import CommandError, TransportError
from uel_gopro.core.models import CameraStatus, MediaItem, MediaType
from uel_gopro.media.stitcher import parse_gopro_filename

logger = logging.getLogger(__name__)

# Standard OpenGoPro Status Codes
STATUS_BATTERY_LEVEL = 2
STATUS_SYSTEM_HOT = 6
STATUS_ENCODING_ACTIVE = 8
STATUS_SHUTTER_ACTIVE = 10
STATUS_SD_REMAINING_TIME_SEC = 28
STATUS_SD_REMAINING_PHOTOS = 29
STATUS_SD_CARD_INSERTED = 33
STATUS_SD_REMAINING_KB = 38
STATUS_PRESET_GROUP = 43
STATUS_IS_CHARGING = 49

PRESET_GROUP_NAMES = {
    0: "Video",
    1: "Photo",
    2: "Timelapse",
}

SD_STATUS_NAMES = {
    0: "OK",
    1: "MISSING",
    2: "ERROR",
    3: "FULL",
}


class GoProRestClient:
    """HTTP REST API Client for GoPro cameras (OpenGoPro v1/v2 over USB or Wi-Fi)."""

    def __init__(self, ip: str = "172.20.150.51", port: int = 8080, timeout_sec: float = 5.0):
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
        self.timeout = timeout_sec

    def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    raise CommandError(f"HTTP {resp.status_code} for {url}: {resp.text}")
                return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        except httpx.RequestError as exc:
            raise TransportError(f"Failed to connect to GoPro at {url}: {exc}") from exc

    def get_raw_state(self) -> Dict[str, Any]:
        """Fetches raw status and settings dictionary from the camera."""
        return self._get("/gopro/camera/state")

    def get_status(self) -> CameraStatus:
        """Parses camera state into a typed CameraStatus model."""
        raw = self.get_raw_state()
        status_dict = raw.get("status", {})

        def s(key: int) -> Optional[Any]:
            # OpenGoPro status keys are string representations of integers
            return status_dict.get(str(key))

        bat_level = s(STATUS_BATTERY_LEVEL)
        is_charging = bool(s(STATUS_IS_CHARGING) == 1)
        is_encoding = bool(s(STATUS_ENCODING_ACTIVE) == 1 or s(STATUS_SHUTTER_ACTIVE) == 1)
        system_hot = bool(s(STATUS_SYSTEM_HOT) == 1)

        sd_code = s(STATUS_SD_CARD_INSERTED)
        sd_status = SD_STATUS_NAMES.get(sd_code, "OK") if sd_code is not None else "OK"

        sd_kb = s(STATUS_SD_REMAINING_KB)
        sd_mb = (sd_kb // 1024) if sd_kb is not None else None

        preset_grp = s(STATUS_PRESET_GROUP)
        current_mode = PRESET_GROUP_NAMES.get(preset_grp, "Video") if preset_grp is not None else "Video"

        return CameraStatus(
            connected=True,
            battery_percent=bat_level,
            is_charging=is_charging,
            is_recording=is_encoding,
            encoding_active=is_encoding,
            system_hot=system_hot,
            sd_status=sd_status,
            sd_remaining_mb=sd_mb,
            sd_remaining_video_time_sec=s(STATUS_SD_REMAINING_TIME_SEC),
            sd_remaining_photos=s(STATUS_SD_REMAINING_PHOTOS),
            current_mode=current_mode,
            raw_status=status_dict,
        )

    def shutter_start(self) -> None:
        """Starts video recording or triggers photo capture."""
        self._get("/gopro/camera/shutter/start")

    def shutter_stop(self) -> None:
        """Stops video recording."""
        self._get("/gopro/camera/shutter/stop")

    def set_setting(self, setting_id: int, value: int) -> None:
        """Mutates a camera setting."""
        self._get("/gopro/camera/setting", params={"setting": setting_id, "opt": value})

    def get_media_list(self) -> List[MediaItem]:
        """Retrieves listing of all media stored on camera SD card."""
        raw = self._get("/gopro/media/list")
        items: List[MediaItem] = []

        media_dirs = raw.get("media", [])
        for media_dir in media_dirs:
            dirname = media_dir.get("d", "100GOPRO")
            files = media_dir.get("fs", [])
            for f in files:
                filename = f.get("n", "")
                raw_size = int(f.get("s", 0))
                mod_time = f.get("mod")

                # Determine media type
                lower_name = filename.lower()
                if lower_name.endswith((".mp4", ".mov")):
                    mtype = MediaType.VIDEO
                elif lower_name.endswith((".jpg", ".gpr")):
                    mtype = MediaType.PHOTO
                elif lower_name.endswith(".wav"):
                    mtype = MediaType.AUDIO
                elif lower_name.endswith(".thm"):
                    mtype = MediaType.THUMBNAIL
                else:
                    mtype = MediaType.SIDECAR

                info = parse_gopro_filename(filename)
                items.append(
                    MediaItem(
                        directory=dirname,
                        filename=filename,
                        size_bytes=raw_size,
                        mod_time=int(mod_time) if mod_time else None,
                        media_type=mtype,
                        is_chapter=(info.chapter_num > 1) if info else False,
                        chapter_num=info.chapter_num if info else 1,
                        base_id=info.base_id if info else "",
                    )
                )

        return items

    def delete_file(self, directory: str, filename: str) -> None:
        """Deletes a single file from the camera SD card."""
        self._get("/gopro/media/delete/file", params={"path": f"{directory}/{filename}"})

    def format_sd_card(self) -> None:
        """Formats the camera SD card."""
        self._get("/gopro/media/format")

    def get_presets(self) -> Dict[str, Any]:
        """Retrieves list of presets available on the camera."""
        return self._get("/gopro/camera/presets/get")

    def load_preset(self, preset_id: int) -> None:
        """Loads a specific preset by ID."""
        self._get("/gopro/camera/presets/load", params={"id": preset_id})

    def keep_alive(self) -> None:
        """Pings the keep-alive endpoint to maintain Wi-Fi / connection lease."""
        self._get("/gopro/camera/keep_alive")
