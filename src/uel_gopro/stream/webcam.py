from __future__ import annotations

import logging
from typing import Any, Dict

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError

logger = logging.getLogger(__name__)

# OpenGoPro webcam resolution codes.
# Source: https://gopro.github.io/OpenGoPro/http#tag/Webcam
WEBCAM_RESOLUTIONS = {
    "480p": 4,
    "720p": 7,
    "1080p": 12,
}

# OpenGoPro webcam field-of-view codes.
WEBCAM_FOVS = {
    "wide": 0,
    "narrow": 2,
    "superview": 3,
    "linear": 4,
}


def start_webcam(
    client: GoProRestClient,
    resolution: str = "1080p",
    fov: str = "wide",
) -> Dict[str, Any]:
    """Initiate USB webcam mode on the GoPro."""
    resolution_code = WEBCAM_RESOLUTIONS.get(resolution.lower())
    if resolution_code is None:
        raise CommandError(
            f"Unsupported webcam resolution: {resolution!r}. "
            f"Choose one of: {', '.join(WEBCAM_RESOLUTIONS)}"
        )

    fov_code = WEBCAM_FOVS.get(fov.lower())
    if fov_code is None:
        raise CommandError(
            f"Unsupported webcam field of view: {fov!r}. "
            f"Choose one of: {', '.join(WEBCAM_FOVS)}"
        )

    try:
        client.enable_wired_usb(True)
    except Exception as exc:  # webcam can still work if this endpoint is unavailable
        logger.warning(f"Could not enable wired USB control: {exc}")

    result = client.start_webcam(resolution_code, fov_code)
    logger.info(f"GoPro webcam started with resolution={resolution}, fov={fov}")
    return result


def stop_webcam(client: GoProRestClient) -> Dict[str, Any]:
    """Stop USB webcam mode on the GoPro."""
    result = client.stop_webcam()
    logger.info("GoPro webcam stopped")
    return result


def get_webcam_status(client: GoProRestClient) -> Dict[str, Any]:
    """Query the current webcam status from the camera."""
    return client.get_webcam_status()
