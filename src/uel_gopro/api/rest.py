from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from uel_gopro.core.exceptions import CommandError, TransportError
from uel_gopro.core.models import CameraStatus, MediaItem, MediaType
from uel_gopro.media.stitcher import parse_gopro_filename

logger = logging.getLogger(__name__)

# OpenGoPro status IDs.
# Source: https://gopro.github.io/OpenGoPro/docs/ble/statuses
STATUS_BATTERY_PRESENT = 1
STATUS_BATTERY_BARS = 2
STATUS_SYSTEM_HOT = 6
STATUS_BUSY = 8
STATUS_ENCODING = 10
STATUS_PRIMARY_STORAGE = 33
STATUS_REMAINING_PHOTOS = 34
STATUS_REMAINING_VIDEO_TIME = 35
STATUS_SD_CARD_REMAINING_KB = 54
STATUS_INTERNAL_BATTERY_PERCENT = 70
STATUS_PRESET_GROUP = 96
STATUS_PRESET = 97

# Primary storage values (status 33).
SD_STORAGE_STATES = {
    -1: "UNKNOWN",
    0: "OK",
    1: "FULL",
    2: "MISSING",
    3: "FORMAT_ERROR",
    4: "BUSY",
    8: "SWAPPED",
}

# Preset group values (status 96).
PRESET_GROUP_NAMES = {
    1000: "Video",
    1001: "Photo",
    1002: "Timelapse",
    2000: "General",
}


def _as_int(value: Any) -> Optional[int]:
    """Best-effort integer coercion for camera status/settings values.

    Cameras occasionally report status values as strings, floats, empty
    strings, or omit them entirely.  Status parsing must never crash because
    of one unexpected field.
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class GoProRestClient:
    """HTTP REST API client for GoPro cameras (OpenGoPro v1/v2 over USB or Wi-Fi)."""

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
                content_type = resp.headers.get("content-type", "")
                if not content_type.startswith("application/json"):
                    return {}
                try:
                    return resp.json()
                except ValueError as exc:
                    raise CommandError(f"Invalid JSON response from {url}: {exc}") from exc
        except httpx.RequestError as exc:
            raise TransportError(f"Failed to connect to GoPro at {url}: {exc}") from exc

    # ------------------------------------------------------------------
    # State & info
    # ------------------------------------------------------------------
    def get_raw_state(self) -> Dict[str, Any]:
        """Fetches raw status and settings dictionary from the camera."""
        return self._get("/gopro/camera/state")

    def get_camera_info(self) -> Dict[str, Any]:
        """Fetches model name, firmware, and serial number (HERO12+).

        Older cameras may return 404/403 for this endpoint; callers should
        treat failures as non-fatal.
        """
        return self._get("/gopro/camera/info")

    def get_status(self) -> CameraStatus:
        """Parses camera state into a typed CameraStatus model."""
        raw = self.get_raw_state() or {}
        status_dict = raw.get("status", {}) or {}

        def s(key: int) -> Any:
            # OpenGoPro status keys are strings, but tolerate integer keys too.
            if key in status_dict:
                return status_dict[key]
            return status_dict.get(str(key))

        battery_bars = _as_int(s(STATUS_BATTERY_BARS))
        battery_percent = _as_int(s(STATUS_INTERNAL_BATTERY_PERCENT))
        if battery_percent is None and battery_bars in (0, 1, 2, 3):
            # Approximate fallback for cameras that do not expose percentage.
            battery_percent = {0: 0, 1: 33, 2: 66, 3: 100}[battery_bars]

        encoding_active = _as_int(s(STATUS_ENCODING)) == 1
        storage_code = _as_int(s(STATUS_PRIMARY_STORAGE))
        sd_status = SD_STORAGE_STATES.get(storage_code, "UNKNOWN") if storage_code is not None else "UNKNOWN"

        sd_remaining_kb = _as_int(s(STATUS_SD_CARD_REMAINING_KB))
        sd_remaining_mb = (
            sd_remaining_kb // 1024 if sd_remaining_kb is not None and sd_remaining_kb >= 0 else None
        )

        preset_group = _as_int(s(STATUS_PRESET_GROUP))
        current_mode = (
            PRESET_GROUP_NAMES.get(preset_group, f"Unknown ({preset_group})")
            if preset_group is not None
            else "Unknown"
        )
        current_preset = _as_str(s(STATUS_PRESET))

        return CameraStatus(
            connected=True,
            battery_percent=battery_percent,
            battery_bars=battery_bars,
            is_charging=battery_bars == 4,
            is_recording=encoding_active,
            encoding_active=encoding_active,
            system_hot=_as_int(s(STATUS_SYSTEM_HOT)) == 1,
            sd_status=sd_status,
            sd_remaining_mb=sd_remaining_mb,
            sd_remaining_video_time_sec=_as_int(s(STATUS_REMAINING_VIDEO_TIME)),
            sd_remaining_photos=_as_int(s(STATUS_REMAINING_PHOTOS)),
            current_mode=current_mode,
            current_preset=current_preset,
            raw_status=status_dict,
        )

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------
    def shutter_start(self) -> None:
        """Starts video recording or triggers photo capture in the current mode."""
        self._get("/gopro/camera/shutter/start")

    def shutter_stop(self) -> None:
        """Stops video recording."""
        self._get("/gopro/camera/shutter/stop")

    def set_setting(self, setting_id: int, value: int) -> None:
        """Mutates a camera setting.

        The OpenGoPro HTTP API uses the query parameter ``option`` (not
        ``opt``) for the desired value.
        """
        self._get("/gopro/camera/setting", params={"setting": setting_id, "option": value})

    def keep_alive(self) -> None:
        """Pings the keep-alive endpoint to maintain the connection lease."""
        self._get("/gopro/camera/keep_alive")

    def enable_wired_usb(self, enabled: bool = True) -> None:
        """Enable/disable wired USB control."""
        self._get("/gopro/camera/control/wired_usb", params={"p": int(enabled)})

    # ------------------------------------------------------------------
    # Presets & media
    # ------------------------------------------------------------------
    def get_presets(self, include_hidden: Optional[bool] = None) -> Dict[str, Any]:
        """Retrieves list of presets available on the camera."""
        params: Optional[Dict[str, Any]] = None
        if include_hidden is not None:
            params = {"include-hidden": int(include_hidden)}
        return self._get("/gopro/camera/presets/get", params=params)

    def load_preset(self, preset_id: int) -> None:
        """Loads a specific preset by ID."""
        self._get("/gopro/camera/presets/load", params={"id": preset_id})

    def get_media_list(self) -> List[MediaItem]:
        """Retrieves listing of all media stored on camera SD card."""
        raw = self._get("/gopro/media/list") or {}
        items: List[MediaItem] = []

        for media_dir in raw.get("media", []) or []:
            dirname = media_dir.get("d", "100GOPRO")
            for f in media_dir.get("fs", []) or []:
                filename = f.get("n", "")
                if not filename:
                    continue
                raw_size = _as_int(f.get("s")) or 0
                mod_time = _as_int(f.get("mod"))

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

                chapter_info = parse_gopro_filename(filename)
                items.append(
                    MediaItem(
                        directory=dirname,
                        filename=filename,
                        size_bytes=max(0, raw_size),
                        mod_time=mod_time,
                        media_type=mtype,
                        is_chapter=(chapter_info.chapter_num > 1) if chapter_info else False,
                        chapter_num=chapter_info.chapter_num if chapter_info else 1,
                        base_id=chapter_info.base_id if chapter_info else "",
                    )
                )

        return items

    def delete_file(self, directory: str, filename: str) -> None:
        """Deletes a single file from the camera SD card."""
        self._get("/gopro/media/delete/file", params={"path": f"{directory}/{filename}"})

    # ------------------------------------------------------------------
    # Streaming & webcam
    # ------------------------------------------------------------------
    def start_preview_stream(self) -> None:
        """Starts the camera's preview stream (UDP 8554 by default)."""
        self._get("/gopro/camera/stream/start")

    def stop_preview_stream(self) -> None:
        """Stops the camera's preview stream."""
        self._get("/gopro/camera/stream/stop")

    def start_webcam(self, resolution_code: int, fov_code: int) -> Dict[str, Any]:
        """Starts USB webcam mode with explicit OpenGoPro codes."""
        return self._get(
            "/gopro/webcam/start",
            params={"res": resolution_code, "fov": fov_code},
        )

    def stop_webcam(self) -> Dict[str, Any]:
        """Stops USB webcam mode."""
        return self._get("/gopro/webcam/stop")

    def get_webcam_status(self) -> Dict[str, Any]:
        """Queries current webcam status from the camera."""
        return self._get("/gopro/webcam/status")
