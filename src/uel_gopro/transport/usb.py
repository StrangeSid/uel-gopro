from __future__ import annotations

import logging
import re
from typing import Optional
import httpx
import psutil

from uel_gopro.core.exceptions import CameraNotFoundError, TransportError
from uel_gopro.core.models import CameraInfo, TransportType

logger = logging.getLogger(__name__)

# GoPro CDC-ECM USB IP standard: 172.2X.1XX.51:8080
GOPRO_IP_PATTERN = re.compile(r"^172\.(2[0-9])\.(\d{1,3})\.(\d{1,3})$")
DEFAULT_GOPRO_PORT = 8080


def detect_usb_camera(timeout_sec: float = 1.0) -> Optional[CameraInfo]:
    """Scans local network interfaces to detect a connected GoPro over CDC-ECM USB."""
    addrs = psutil.net_if_addrs()

    candidate_ips: list[tuple[str, str]] = []  # (camera_ip, iface_name)

    for iface_name, addr_list in addrs.items():
        for addr in addr_list:
            # We look for IPv4 addresses
            if addr.family == psutil.AF_LINK or not addr.address:
                continue
            ip = addr.address
            match = GOPRO_IP_PATTERN.match(ip)
            if match:
                # Host IP is e.g. 172.24.162.2; camera is .51 in the same subnet
                octets = ip.split(".")
                camera_ip = f"{octets[0]}.{octets[1]}.{octets[2]}.51"
                candidate_ips.append((camera_ip, iface_name))

    for camera_ip, iface in candidate_ips:
        if probe_camera_ip(camera_ip, port=DEFAULT_GOPRO_PORT, timeout_sec=timeout_sec):
            logger.info(f"GoPro detected on {iface} at {camera_ip}:{DEFAULT_GOPRO_PORT}")
            return CameraInfo(
                model_name="GoPro (USB CDC-ECM)",
                ip_address=camera_ip,
                port=DEFAULT_GOPRO_PORT,
                transport=TransportType.USB,
                interface_name=iface,
            )

    return None


def probe_camera_ip(ip: str, port: int = DEFAULT_GOPRO_PORT, timeout_sec: float = 1.0) -> bool:
    """Probes if a GoPro HTTP API server responds at the specified IP."""
    url = f"http://{ip}:{port}/gopro/camera/state"
    try:
        with httpx.Client(timeout=timeout_sec) as client:
            resp = client.get(url)
            return resp.status_code == 200
    except (httpx.RequestError, httpx.TimeoutException):
        return False
