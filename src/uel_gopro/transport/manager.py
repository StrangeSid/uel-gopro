from __future__ import annotations

import logging
from typing import Optional

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CameraNotFoundError
from uel_gopro.core.models import CameraInfo, TransportType
from uel_gopro.transport.usb import detect_usb_camera, probe_camera_ip

logger = logging.getLogger(__name__)

DEFAULT_WIFI_IP = "10.5.5.9"
DEFAULT_PORT = 8080


def resolve_camera(
    target_ip: Optional[str] = None,
    transport_hint: TransportType = TransportType.AUTO,
    timeout_sec: float = 1.0,
) -> tuple[CameraInfo, GoProRestClient]:
    """Resolves and connects to a GoPro camera using prioritized transport fallback.

    Priority:
    1. Explicit target_ip if provided.
    2. Wired USB-C (CDC-ECM subnet 172.2X.1XX.51:8080).
    3. Wi-Fi AP (10.5.5.9:8080).
    """
    # 1. Manual IP passed
    if target_ip:
        if probe_camera_ip(target_ip, port=DEFAULT_PORT, timeout_sec=timeout_sec):
            info = CameraInfo(
                model_name="GoPro (Manual IP / COHN)",
                ip_address=target_ip,
                port=DEFAULT_PORT,
                transport=TransportType.COHN if transport_hint == TransportType.COHN else TransportType.AUTO,
            )
            return info, GoProRestClient(ip=target_ip, port=DEFAULT_PORT)
        raise CameraNotFoundError(f"No GoPro response at specified IP: {target_ip}:{DEFAULT_PORT}")

    # 2. Wired USB CDC-ECM (unless user explicitly forced wifi)
    if transport_hint in (TransportType.AUTO, TransportType.USB):
        cam = detect_usb_camera(timeout_sec=timeout_sec)
        if cam:
            return cam, GoProRestClient(ip=cam.ip_address, port=cam.port)
        if transport_hint == TransportType.USB:
            raise CameraNotFoundError(
                "No GoPro detected over USB-C CDC-ECM.\n"
                "Ensure camera is powered ON, USB connection mode is set to 'GoPro Connect' (not MTP), "
                "and cable supports data."
            )

    # 3. Wi-Fi AP default IP (10.5.5.9)
    if transport_hint in (TransportType.AUTO, TransportType.WIFI_AP):
        if probe_camera_ip(DEFAULT_WIFI_IP, port=DEFAULT_PORT, timeout_sec=timeout_sec):
            info = CameraInfo(
                model_name="GoPro (Wi-Fi AP)",
                ip_address=DEFAULT_WIFI_IP,
                port=DEFAULT_PORT,
                transport=TransportType.WIFI_AP,
            )
            return info, GoProRestClient(ip=DEFAULT_WIFI_IP, port=DEFAULT_PORT)
        if transport_hint == TransportType.WIFI_AP:
            raise CameraNotFoundError(
                f"No GoPro response on Wi-Fi AP ({DEFAULT_WIFI_IP}:{DEFAULT_PORT}).\n"
                "Ensure your computer's Wi-Fi is connected to the camera's Wi-Fi network."
            )

    raise CameraNotFoundError(
        "Could not detect any GoPro camera.\n"
        "Connect via USB-C (GoPro Connect mode) or connect computer Wi-Fi to camera AP (10.5.5.9),\n"
        "or specify IP explicitly with --ip <ip>."
    )
