from __future__ import annotations

import logging
from typing import Optional
import httpx

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import TransportError

logger = logging.getLogger(__name__)


class CohnRestClient(GoProRestClient):
    """Client for Camera-On-Home-Network (COHN).

    Connects to GoPro over local Wi-Fi router IP via HTTPS/HTTP using TLS cert or basic credentials.
    """

    def __init__(
        self,
        ip: str,
        port: int = 8080,
        use_https: bool = False,
        cert_path: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout_sec: float = 5.0,
    ):
        super().__init__(ip=ip, port=port, timeout_sec=timeout_sec)
        scheme = "https" if use_https else "http"
        self.base_url = f"{scheme}://{ip}:{port}"
        self.cert_path = cert_path
        self.auth = (username, password) if username and password else None
        self.verify = cert_path if cert_path else False

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            with httpx.Client(timeout=self.timeout, verify=self.verify, auth=self.auth) as client:
                resp = client.get(url, params=params)
                if resp.status_code != 200:
                    from uel_gopro.core.exceptions import CommandError
                    raise CommandError(f"HTTP {resp.status_code} for {url}: {resp.text}")
                return resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        except httpx.RequestError as exc:
            raise TransportError(f"Failed to connect to GoPro over COHN at {url}: {exc}") from exc
