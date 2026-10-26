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
    timeout_sec: float = 2.0,
) -> tuple[CameraInfo, GoProRestClient]:
    """Resolve a camera over the transports this project actually supports.

    Priority:
    1. Explicit ``target_ip`` (plain HTTP on port 8080).
    2. Wired USB-C CDC-ECM (``172.2X.1XX.51:8080``), unless Wi-Fi was forced.
    3. Wi-Fi access point (``10.5.5.9:8080``).

    MTP is handled explicitly by the CLI for media-list/download fallback;
    COHN and BLE are not part of automatic transport negotiation yet.
    """
    if target_ip:
        if probe_camera_ip(target_ip, port=DEFAULT_PORT, timeout_sec=timeout_sec):
            return (
                CameraInfo(
                    model_name="GoPro (manual IP)",
                    ip_address=target_ip,
                    port=DEFAULT_PORT,
                    transport=TransportType.MANUAL,
                ),
                GoProRestClient(ip=target_ip, port=DEFAULT_PORT),
            )
        raise CameraNotFoundError(f"No GoPro response at specified IP: {target_ip}:{DEFAULT_PORT}")

    if transport_hint in (TransportType.AUTO, TransportType.USB):
        cam = detect_usb_camera(timeout_sec=timeout_sec)
        if cam:
            return cam, GoProRestClient(ip=cam.ip_address, port=cam.port)
        if transport_hint == TransportType.USB:
            raise CameraNotFoundError(
                "No GoPro detected over USB-C CDC-ECM.\n"
                "Ensure the camera is powered ON, the USB connection mode is "
                "'GoPro Connect' (not MTP), and the cable supports data."
            )

    if transport_hint in (TransportType.AUTO, TransportType.WIFI_AP):
        if probe_camera_ip(DEFAULT_WIFI_IP, port=DEFAULT_PORT, timeout_sec=timeout_sec):
            return (
                CameraInfo(
                    model_name="GoPro (Wi-Fi AP)",
                    ip_address=DEFAULT_WIFI_IP,
                    port=DEFAULT_PORT,
                    transport=TransportType.WIFI_AP,
                ),
                GoProRestClient(ip=DEFAULT_WIFI_IP, port=DEFAULT_PORT),
            )
        if transport_hint == TransportType.WIFI_AP:
            raise CameraNotFoundError(
                f"No GoPro response on Wi-Fi AP ({DEFAULT_WIFI_IP}:{DEFAULT_PORT}).\n"
                "Ensure your computer's Wi-Fi is connected to the camera's Wi-Fi network."
            )

    raise CameraNotFoundError(
        "Could not detect any GoPro camera.\n"
        "Connect via USB-C (GoPro Connect mode) or join the camera Wi-Fi AP (10.5.5.9),\n"
        "or specify an address explicitly with --ip <ip>."
    )
