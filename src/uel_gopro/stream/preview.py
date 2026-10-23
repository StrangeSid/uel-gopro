from __future__ import annotations

import logging
import shutil
import subprocess
from typing import List, Optional

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError

logger = logging.getLogger(__name__)

DEFAULT_STREAM_URL = "udp://@0.0.0.0:8554"


def build_player_command(player: str = "mpv", stream_url: str = DEFAULT_STREAM_URL) -> List[str]:
    """Generates optimal low-latency playback command arguments for mpv or ffplay."""
    if player == "mpv":
        return [
            "mpv",
            "--no-cache",
            "--untimed",
            "--vd-lavc-threads=1",
            "--fps=30",
            stream_url,
        ]
    elif player == "ffplay":
        return [
            "ffplay",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-strict",
            "experimental",
            stream_url,
        ]
    else:
        return [player, stream_url]


def launch_preview_stream(
    client: GoProRestClient,
    player: Optional[str] = None,
    stream_url: str = DEFAULT_STREAM_URL,
    spawn_player: bool = True,
) -> Optional[subprocess.Popen]:
    """Starts camera stream and optionally launches external video player."""
    # Trigger wired USB control / stream start
    try:
        client._get("/gopro/camera/control/wired_usb", params={"p": 1})
    except Exception as exc:
        logger.warning(f"Could not enable wired_usb control: {exc}")

    try:
        client._get("/gopro/camera/stream/start")
    except Exception as exc:
        logger.warning(f"Stream start endpoint returned: {exc}")

    if not spawn_player:
        return None

    selected_player = player
    if not selected_player:
        if shutil.which("mpv"):
            selected_player = "mpv"
        elif shutil.which("ffplay"):
            selected_player = "ffplay"
        else:
            raise CommandError("Neither 'mpv' nor 'ffplay' found in system PATH. Install one or pass --no-player.")

    cmd = build_player_command(player=selected_player, stream_url=stream_url)
    logger.info(f"Spawning player: {' '.join(cmd)}")
    return subprocess.Popen(cmd)
