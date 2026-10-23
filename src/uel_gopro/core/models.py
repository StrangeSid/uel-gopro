from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class TransportType(str, Enum):
    USB = "usb"
    COHN = "cohn"
    WIFI_AP = "wifi_ap"
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
    is_charging: bool = False
    is_recording: bool = False
    encoding_active: bool = False
    system_hot: bool = False
    sd_status: str = "OK"  # OK, MISSING, FULL, ERROR
    sd_remaining_mb: Optional[int] = None
    sd_remaining_video_time_sec: Optional[int] = None
    sd_remaining_photos: Optional[int] = None
    current_mode: str = "Video"
    current_preset: Optional[str] = None
    resolution: Optional[str] = None
    fps: Optional[str] = None
    fov: Optional[str] = None
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
        return f"/videos/DCIM/{self.directory}/{self.filename}"


class ChapterGroup(BaseModel):
    base_id: str
    items: List[MediaItem] = Field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)


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
