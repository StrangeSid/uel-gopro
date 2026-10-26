from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from uel_gopro.core.exceptions import CommandError, MediaError, TransportError

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "uel-gopro" / "cloud.json"
BASE_URL = "https://api.gopro.com/media"


def _safe_filename(value: Any, fallback: str) -> str:
    """Return a path-component-safe filename, never ``.``/``..``."""
    name = Path(str(value or "")).name.strip()
    if name in ("", ".", ".."):
        safe_fallback = Path(str(fallback or "media")).name
        return safe_fallback if safe_fallback not in ("", ".", "..") else "media"
    return name


def save_cloud_auth(
    token: str,
    user_id: str = "",
    config_path: Optional[Path | str] = None,
) -> Path:
    """Save GoPro Cloud authentication token and user ID to a private config file."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "auth_token": token,
        "user_id": user_id,
    }
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:  # pragma: no cover - best effort on non-POSIX filesystems
        pass
    tmp_path.replace(path)
    logger.info(f"GoPro Cloud credentials saved to {path}")
    return path


def load_cloud_auth(config_path: Optional[Path | str] = None) -> dict[str, str]:
    """Load GoPro Cloud authentication token and user ID from config file."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"Error reading cloud auth config from {path}: {exc}")
        return {}


class GoProCloudClient:
    """GoPro Plus Cloud API client for media listing and batch sync downloads.

    This uses GoPro's undocumented media API with a user-supplied bearer
    token.  It is inherently best-effort and may break when GoPro changes the
    service.
    """

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
        # Stored for compatibility with existing config files; the current
        # undocumented API calls are authenticated with the bearer token only.
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
        """Query one page of the GoPro Cloud media library."""
        url = f"{self.base_url}/search"
        headers = self._get_headers()
        params = {"page": page, "per_page": per_page}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(url, headers=headers, params=params)
                if resp.status_code != 200:
                    raise CommandError(
                        f"GoPro Cloud search failed with HTTP {resp.status_code}: {resp.text}"
                    )
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise CommandError(f"Invalid JSON from GoPro Cloud API: {exc}") from exc
                if isinstance(data, dict):
                    embedded = data.get("_embedded", {})
                    if isinstance(embedded, dict) and isinstance(embedded.get("media"), list):
                        return embedded["media"]
                    if isinstance(data.get("media"), list):
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
                try:
                    data = resp.json()
                except ValueError as exc:
                    raise CommandError(f"Invalid JSON from GoPro Cloud API: {exc}") from exc
                if isinstance(data, dict):
                    embedded = data.get("_embedded", {})
                    variations = embedded.get("variations", []) if isinstance(embedded, dict) else []
                    for variation in variations:
                        if variation.get("label") == "source" and "url" in variation:
                            return variation["url"]
                    if variations and "url" in variations[0]:
                        return variations[0]["url"]
                    files = embedded.get("files", []) if isinstance(embedded, dict) else []
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
        """Download a media file, resuming from an existing ``.partial`` buffer."""
        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        partial_path = target.with_name(f"{target.name}.partial")

        headers: dict[str, str] = {}
        if "gopro.com" in url and self.auth_token:
            token = self.auth_token
            headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"

        if expected_size is not None and expected_size <= 0:
            expected_size = None
        existing = partial_path.stat().st_size if partial_path.exists() else 0
        if expected_size is not None and existing > expected_size:
            partial_path.unlink(missing_ok=True)
            existing = 0
        if expected_size is not None and existing == expected_size and partial_path.exists():
            partial_path.replace(target)
            return target

        if existing > 0:
            headers["Range"] = f"bytes={existing}-"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                    if resp.status_code == 206:
                        mode = "ab"
                        downloaded = existing
                    elif resp.status_code == 200:
                        if existing > 0:
                            logger.info("Server did not honor Range; restarting cloud download from byte 0")
                        mode = "wb"
                        downloaded = 0
                    elif resp.status_code == 416:
                        partial_path.unlink(missing_ok=True)
                        where = "Range Not Satisfiable; partial buffer removed"
                        raise MediaError(f"Cloud download failed for {url}: {where}")
                    else:
                        resp.raise_for_status()
                        mode = "wb"
                        downloaded = 0

                    if expected_size is None:
                        content_length = resp.headers.get("content-length")
                        if content_length and content_length.isdigit() and resp.status_code == 200:
                            expected_size = int(content_length)

                    with open(partial_path, mode) as f:
                        for chunk in resp.iter_bytes(chunk_size=chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, expected_size or 0)

            if expected_size is not None and expected_size > 0 and downloaded != expected_size:
                partial_path.unlink(missing_ok=True)
                raise MediaError(
                    f"Downloaded size ({downloaded}) does not match expected size ({expected_size})"
                )

            partial_path.replace(target)
            return target

        except MediaError:
            raise
        except httpx.HTTPStatusError as exc:
            raise MediaError(
                f"HTTP {exc.response.status_code} error downloading {url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise MediaError(f"Network error downloading {url} to {target_path}: {exc}") from exc
        except OSError as exc:
            raise MediaError(f"Filesystem error downloading {url} to {target_path}: {exc}") from exc

    def sync_all(
        self,
        dest_dir: Path | str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        max_pages: Optional[int] = None,
    ) -> list[Path]:
        """Iterate cloud pages and download all media files to ``dest_dir``.

        Existing files with a matching size are skipped.  A partial buffer is
        retained on network failure so the next run can resume it.
        """
        dest = Path(dest_dir).resolve()
        dest.mkdir(parents=True, exist_ok=True)

        downloaded_paths: list[Path] = []
        seen_ids: set[str] = set()
        previous_page_ids: set[str] = set()
        page = 1
        per_page = 100

        while True:
            items = self.list_media(page=page, per_page=per_page)
            if not items:
                break

            page_ids = {str(item.get("id")) for item in items if item.get("id") is not None}
            if page > 1 and page_ids and page_ids == previous_page_ids:
                logger.warning("Cloud API returned the same page twice; stopping pagination")
                break
            previous_page_ids = page_ids

            for item in items:
                asset_id = str(item.get("id") or "").strip()
                if asset_id and asset_id in seen_ids:
                    continue
                if asset_id:
                    seen_ids.add(asset_id)

                fallback = f"{asset_id or 'media'}.mp4"
                filename = _safe_filename(item.get("filename"), fallback)
                target_path = dest / filename

                raw_size = item.get("file_size")
                if raw_size is None:
                    raw_size = item.get("size")
                expected_size: Optional[int] = None
                if raw_size is not None:
                    try:
                        expected_size = int(raw_size)
                        if expected_size <= 0:
                            expected_size = None
                    except (ValueError, TypeError):
                        expected_size = None

                if target_path.exists():
                    actual_size = target_path.stat().st_size
                    if (expected_size is not None and actual_size == expected_size) or (
                        expected_size is None and actual_size > 0
                    ):
                        logger.info(f"Skipping {filename}: already exists ({actual_size} bytes)")
                        downloaded_paths.append(target_path)
                        continue
                    if expected_size is not None and asset_id:
                        # Do not overwrite a different asset that happens to share a filename.
                        target_path = dest / f"{asset_id}_{filename}"

                download_url = item.get("download_url") or item.get("url")
                if not download_url and item.get("id"):
                    download_url = self.get_download_url(str(item["id"]))

                if not download_url:
                    logger.warning(f"Could not resolve download URL for item {asset_id or filename}")
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
