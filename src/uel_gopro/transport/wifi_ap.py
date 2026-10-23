from __future__ import annotations

import logging
import threading
import time
from typing import Optional
import httpx

from uel_gopro.api.rest import GoProRestClient

logger = logging.getLogger(__name__)


class WifiKeepAliveDaemon:
    """Background daemon thread sending keep-alive pings to prevent GoPro Wi-Fi timeout."""

    def __init__(self, client: GoProRestClient, interval_sec: float = 15.0):
        self.client = client
        self.interval = interval_sec
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the keep-alive loop in a background daemon thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="GoProKeepAlive")
        self._thread.start()
        logger.info(f"Keep-alive daemon started (interval={self.interval}s)")

    def stop(self) -> None:
        """Stops the keep-alive loop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            logger.info("Keep-alive daemon stopped")

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.client.keep_alive()
                logger.debug("Keep-alive ping sent successfully")
            except Exception as exc:
                logger.warning(f"Keep-alive ping failed: {exc}")
            self._stop_event.wait(self.interval)
