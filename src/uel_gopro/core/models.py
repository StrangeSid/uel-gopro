from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional
from urllib.parse import quote

from pydantic import BaseModel, Field


class TransportType(str, Enum):
    USB = "usb"
    MTP = "mtp"
    WIFI_AP = "wifi_ap"
    MANUAL = "manual"
    BLE = "ble"
    AUTO = "auto"


class CameraInfo(BaseModel):
    model_name: str = "Unknown GoPro"
    firmware_version: str = "Unknown"
    serial_number: Optional[str] = None
    ip_address: str = "172.20.150.51"
    port: int = 8080
    transport: TransportType = TransportType.USB
    interface_name: Optional[str] = None


class CameraStatus(BaseModel):
    connected: bool = True
    battery_percent: Optional[int] = None
    battery_bars: Optional[int] = None
    is_charging: bool = False
    is_recording: bool = False
    encoding_active: bool = False
    system_hot: bool = False
    sd_status: str = "UNKNOWN"  # OK, FULL, MISSING, FORMAT_ERROR, BUSY, SWAPPED, UNKNOWN
    sd_remaining_mb: Optional[int] = None
    sd_remaining_video_time_sec: Optional[int] = None
    sd_remaining_photos: Optional[int] = None
    current_mode: str = "Unknown"
    current_preset: Optional[str] = None
    raw_status: dict[str, Any] = Field(default_factory=dict)


class MediaType(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"
    AUDIO = "audio"
    THUMBNAIL = "thumbnail"
    SIDECAR = "sidecar"


class MediaItem(BaseModel):
    directory: str
    filename: str
    size_bytes: int
    mod_time: Optional[int] = None
    media_type: MediaType = MediaType.VIDEO
    is_chapter: bool = False
    chapter_num: int = 1
    base_id: str = ""

    @property
    def download_url_path(self) -> str:
        directory = quote(self.directory, safe="")
        filename = quote(self.filename, safe="")
        return f"/videos/DCIM/{directory}/{filename}"


class GpsPoint(BaseModel):
    timestamp_utc: Optional[str] = None
    lat: float
    lon: float
    alt: float
    speed_2d: Optional[float] = None
    speed_3d: Optional[float] = None


class TelemetryTrack(BaseModel):
    device_name: str = "GoPro"
    gps_points: List[GpsPoint] = Field(default_factory=list)
    has_gyro: bool = False
    has_accel: bool = False
