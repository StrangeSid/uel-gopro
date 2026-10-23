from __future__ import annotations

import logging
from typing import Dict, Any

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError

logger = logging.getLogger(__name__)

# GoPro Webcam Resolution Codes
WEBCAM_RES_1080P = 12
WEBCAM_RES_770P = 7
WEBCAM_RES_720P = 4

# Webcam FOV Codes
WEBCAM_FOV_WIDE = 0
WEBCAM_FOV_LINEAR = 4
WEBCAM_FOV_NARROW = 6
WEBCAM_FOV_SUPERVIEW = 3


def start_webcam(
    client: GoProRestClient,
    resolution: str = "1080p",
    fov: str = "wide",
) -> Dict[str, Any]:
    """Initiates USB webcam mode on the GoPro."""
    res_code = WEBCAM_RES_1080P if resolution == "1080p" else WEBCAM_RES_720P
    fov_code = WEBCAM_FOV_LINEAR if fov == "linear" else WEBCAM_FOV_WIDE

    # Ensure wired USB is activated
    try:
        client._get("/gopro/camera/control/wired_usb", params={"p": 1})
    except Exception:
        pass

    # Start webcam endpoint
    # OpenGoPro v2 endpoint: /gopro/webcam/start?res=X&fov=Y
    res = client._get("/gopro/webcam/start", params={"res": res_code, "fov": fov_code})
    logger.info(f"GoPro webcam started with resolution={resolution}, fov={fov}")
    return res


def stop_webcam(client: GoProRestClient) -> Dict[str, Any]:
    """Stops USB webcam mode on the GoPro."""
    res = client._get("/gopro/webcam/stop")
    logger.info("GoPro webcam stopped")
    return res


def get_webcam_status(client: GoProRestClient) -> Dict[str, Any]:
    """Queries current webcam status from the camera."""
    return client._get("/gopro/webcam/status")
