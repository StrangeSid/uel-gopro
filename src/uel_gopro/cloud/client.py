from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import httpx

from uel_gopro.core.exceptions import CommandError, MediaError, TransportError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "uel-gopro" / "cloud.json"
BASE_URL = "https://api.gopro.com/media"


def save_cloud_auth(
    token: str,
    user_id: str = "",
    config_path: Optional[Path | str] = None,
) -> Path:
    """Save GoPro Cloud authentication token and user ID to config file."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "auth_token": token,
        "user_id": user_id,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    logger.info(f"GoPro Cloud credentials saved to {path}")
    return path


def load_cloud_auth(config_path: Optional[Path | str] = None) -> dict[str, str]:
    """Load GoPro Cloud authentication token and user ID from config file."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            return {}
    except Exception as exc:
        logger.warning(f"Error reading cloud auth config from {path}: {exc}")
        return {}


class GoProCloudClient:
    """GoPro Plus Cloud API client for media listing and batch sync downloads."""

    def __init__(
        self,
        auth_token: Optional[str] = None,
        user_id: Optional[str] = None,
        base_url: str = BASE_URL,
        timeout_sec: float = 30.0,
        config_path: Optional[Path | str] = None,
    ):
        creds = load_cloud_auth(config_path) if (auth_token is None or user_id is None) else {}
        self.auth_token = auth_token if auth_token is not None else creds.get("auth_token", "")
        self.user_id = user_id if user_id is not None else creds.get("user_id", "")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout_sec

    def _get_headers(self) -> dict[str, str]:
        if not self.auth_token:
            raise TransportError("GoPro Cloud auth token is not configured or provided")
        token = self.auth_token
        auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"
        return {
            "Authorization": auth_header,
            "Accept": "application/vnd.gopro.jk.media+json; version=2.0.0, application/json",
        }

    def list_media(self, page: int = 1, per_page: int = 100) -> list[dict[str, Any]]:
        """Query media library page using GoPro Cloud search endpoint, bypassing 25-file limit."""
        url = f"{self.base_url}/search"
        headers = self._get_headers()
        params = {
            "page": page,
            "per_page": per_page,
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    raise CommandError(
                        f"GoPro Cloud search failed with HTTP {resp.status_code}: {resp.text}"
                    )
                data = resp.json()
                if isinstance(data, dict):
                    embedded = data.get("_embedded", {})
                    if "media" in embedded and isinstance(embedded["media"], list):
                        return embedded["media"]
                    if "media" in data and isinstance(data["media"], list):
                        return data["media"]
                elif isinstance(data, list):
                    return data
                return []
        except httpx.RequestError as exc:
            raise TransportError(f"Failed to connect to GoPro Cloud API: {exc}") from exc

    def get_download_url(self, media_id: str) -> Optional[str]:
        """Fetch the direct source download URL for a given media ID."""
        url = f"{self.base_url}/{media_id}/download"
        headers = self._get_headers()

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code != 200:
                    logger.warning(
                        f"Download endpoint for {media_id} returned HTTP {resp.status_code}"
                    )
                    return None
                data = resp.json()
                if isinstance(data, dict):
                    embedded = data.get("_embedded", {})
                    variations = embedded.get("variations", [])
                    for var in variations:
                        if var.get("label") == "source" and "url" in var:
                            return var["url"]
                    if variations and "url" in variations[0]:
                        return variations[0]["url"]
                    files = embedded.get("files", [])
                    if files and "url" in files[0]:
                        return files[0]["url"]
                    if "url" in data:
                        return data["url"]
                return None
        except httpx.RequestError as exc:
            logger.warning(f"Error querying download URL for {media_id}: {exc}")
            return None

    def download_media_file(
        self,
        url: str,
        target_path: Path | str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        chunk_size: int = 65536,
    ) -> Path:
        """Downloads a media file to target_path using a .partial buffer."""
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial_path = target.with_name(f"{target.name}.partial")

        headers = {}
        if "gopro.com" in url and self.auth_token:
            auth_token = self.auth_token
            headers["Authorization"] = (
                auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"
            )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    total = expected_size or 0
                    if total == 0 and "content-length" in resp.headers:
                        cl = resp.headers["content-length"]
                        if cl.isdigit():
                            total = int(cl)

                    downloaded = 0
                    with open(partial_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total)

            if expected_size is not None and downloaded != expected_size:
                raise MediaError(
                    f"Downloaded size ({downloaded}) does not match expected size ({expected_size})"
                )

            partial_path.replace(target)
            return target
        except Exception as exc:
            if partial_path.exists():
                try:
                    partial_path.unlink()
                except OSError:
                    pass
            if isinstance(exc, (MediaError, TransportError, CommandError)):
                raise
            raise MediaError(f"Error downloading {url} to {target_path}: {exc}") from exc

    def sync_all(
        self,
        dest_dir: Path | str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_pages: Optional[int] = None,
    ) -> list[Path]:
        """Iterates media pages and downloads all media files to dest_dir.

        Skips already downloaded files if size matches. Uses .partial buffer during download.
        """
        dest = Path(dest_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        downloaded_paths: list[Path] = []
        page = 1
        per_page = 100

        while True:
            items = self.list_media(page=page, per_page=per_page)
            if not items:
                break

            for item in items:
                filename = item.get("filename") or f"{item.get('id', 'media')}.mp4"
                target_path = dest / filename

                raw_size = item.get("file_size")
                if raw_size is None:
                    raw_size = item.get("size")
                expected_size: Optional[int] = None
                if raw_size is not None:
                    try:
                        expected_size = int(raw_size)
                    except (ValueError, TypeError):
                        expected_size = None

                # Check if already completely downloaded
                if target_path.exists():
                    actual_size = target_path.stat().st_size
                    if expected_size is not None and actual_size == expected_size:
                        logger.info(
                            f"Skipping {filename}: already exists with matching size ({actual_size} bytes)"
                        )
                        downloaded_paths.append(target_path)
                        continue
                    elif expected_size is None and actual_size > 0:
                        logger.info(f"Skipping {filename}: already exists ({actual_size} bytes)")
                        downloaded_paths.append(target_path)
                        continue

                # Determine download URL
                download_url = item.get("download_url") or item.get("url")
                if not download_url and item.get("id"):
                    download_url = self.get_download_url(item["id"])

                if not download_url:
                    logger.warning(
                        f"Could not resolve download URL for item {item.get('id', filename)}"
                    )
                    continue

                saved_path = self.download_media_file(
                    url=download_url,
                    target_path=target_path,
                    expected_size=expected_size,
                    progress_callback=progress_callback,
                )
                downloaded_paths.append(saved_path)

            if len(items) < per_page:
                break
            if max_pages is not None and page >= max_pages:
                break
            page += 1

        return downloaded_paths
