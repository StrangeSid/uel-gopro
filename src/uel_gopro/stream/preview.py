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
    """Generate low-latency playback arguments for mpv or ffplay."""
    if player == "mpv":
        return [
            "mpv",
            "--no-cache",
            "--untimed",
            "--vd-lavc-threads=1",
            "--fps=30",
            stream_url,
        ]
    if player == "ffplay":
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
    return [player, stream_url]


def launch_preview_stream(
    client: GoProRestClient,
    player: Optional[str] = None,
    stream_url: str = DEFAULT_STREAM_URL,
    spawn_player: bool = True,
) -> Optional[subprocess.Popen]:
    """Start the camera preview stream and optionally launch an external player.

    The preview stream is a best-effort operation: some camera/firmware
    combinations reject the wired-USB control endpoint while still allowing
    the stream to start.
    """
    try:
        client.enable_wired_usb(True)
    except Exception as exc:
        logger.warning(f"Could not enable wired USB control: {exc}")

    try:
        client.start_preview_stream()
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
            raise CommandError(
                "Neither 'mpv' nor 'ffplay' found in PATH. "
                "Install one or rerun with --no-player."
            )

    cmd = build_player_command(player=selected_player, stream_url=stream_url)
    logger.info(f"Spawning player: {' '.join(cmd)}")
    try:
        return subprocess.Popen(cmd)
    except FileNotFoundError as exc:
        raise CommandError(f"Could not launch player '{selected_player}': {exc}") from exc
