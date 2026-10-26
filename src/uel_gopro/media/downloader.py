from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

import httpx

from uel_gopro.core.exceptions import MediaError

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB


def _parse_content_range_total(value: Optional[str]) -> int:
    """Extract the total size from a ``Content-Range: bytes 0-0/123`` header."""
    if not value or "/" not in value:
        return 0
    total = value.rsplit("/", 1)[1].strip()
    return int(total) if total.isdigit() else 0


def get_remote_file_size(
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    timeout: float | httpx.Timeout = 10.0,
) -> int:
    """Query the authoritative remote file size.

    GoPro firmware has a known bug in ``/gopro/media/list`` where the file
    size is represented as a 32-bit integer and overflows for files >= 4 GB.
    HTTP ``HEAD`` normally returns the correct 64-bit ``Content-Length``.

    Some firmware builds reject ``HEAD``.  In that case this function falls
    back to a one-byte ranged ``GET`` and reads ``Content-Range`` or
    ``Content-Length`` without downloading the body.  Returns ``0`` when the
    size cannot be determined.
    """

    def _head_size(active_client: httpx.Client) -> int:
        try:
            resp = active_client.head(url, follow_redirects=True)
            if resp.status_code in (403, 405, 501):
                return 0
            resp.raise_for_status()
            content_length = resp.headers.get("content-length")
            return int(content_length) if content_length and content_length.isdigit() else 0
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (403, 405, 501):
                return 0
            raise MediaError(
                f"HTTP {exc.response.status_code} while querying file size for {url}"
            ) from exc
        except httpx.RequestError as exc:
            raise MediaError(f"Network error querying file size for {url}: {exc}") from exc

    def _ranged_get_size(active_client: httpx.Client) -> int:
        try:
            with active_client.stream(
                "GET",
                url,
                headers={"Range": "bytes=0-0"},
                follow_redirects=True,
            ) as resp:
                if resp.status_code == 206:
                    return _parse_content_range_total(resp.headers.get("content-range"))
                if resp.status_code == 200:
                    content_length = resp.headers.get("content-length")
                    if content_length and content_length.isdigit():
                        return int(content_length)
                if resp.status_code == 416:
                    total = _parse_content_range_total(resp.headers.get("content-range"))
                    if total:
                        return total
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MediaError(
                f"HTTP {exc.response.status_code} while querying file size for {url}"
            ) from exc
        except httpx.RequestError as exc:
            raise MediaError(f"Network error querying file size for {url}: {exc}") from exc
        return 0

    def _do_size_query(active_client: httpx.Client) -> int:
        size = _head_size(active_client)
        if size > 0:
            return size
        logger.debug("HEAD did not return a usable Content-Length for %s; trying ranged GET", url)
        return _ranged_get_size(active_client)

    if client is not None:
        return _do_size_query(client)

    with httpx.Client(timeout=timeout) as temp_client:
        return _do_size_query(temp_client)


def download_file(
    url: str,
    target_path: Path | str,
    *,
    client: Optional[httpx.Client] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    timeout: float | httpx.Timeout = 30.0,
    expected_size: Optional[int] = None,
) -> Path:
    """Download a file with chunked streaming, resume, and size verification.

    1. Query the authoritative size (HEAD, with ranged-GET fallback).
    2. Write to ``<target_path>.partial`` first.
    3. Resume using an HTTP ``Range`` header if a partial file exists.
    4. Atomically rename ``.partial`` to the final path after verification.
    5. Verify the final byte count when the remote size is known.

    Args:
        url: Direct HTTP download URL.
        target_path: Final destination file path.
        client: Optional shared httpx.Client instance.
        chunk_size: Streaming chunk size in bytes (default 1 MB).
        progress_callback: Optional callback receiving (bytes_downloaded, total_bytes).
        timeout: HTTP request timeout.
        expected_size: Optional expected size used only when the remote size is unknown.

    Returns:
        Path to the completed target file.

    Raises:
        MediaError: If the download fails, an HTTP error occurs, or the size mismatches.
    """
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial_path = target.with_name(f"{target.name}.partial")

    def _execute_download(active_client: httpx.Client) -> Path:
        remote_size = get_remote_file_size(url, client=active_client, timeout=timeout)
        total_size = remote_size if remote_size > 0 else (expected_size or 0)

        existing_size = partial_path.stat().st_size if partial_path.exists() else 0

        if total_size > 0:
            if existing_size == total_size:
                logger.info(f"File already completely downloaded in partial buffer: {partial_path}")
                partial_path.replace(target)
                if progress_callback:
                    progress_callback(total_size, total_size)
                return target
            if existing_size > total_size:
                logger.warning(
                    f"Existing partial file ({existing_size} bytes) exceeds total size "
                    f"({total_size} bytes). Resetting partial file."
                )
                partial_path.unlink(missing_ok=True)
                existing_size = 0

        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"
            mode = "ab"
            downloaded = existing_size
        else:
            mode = "wb"
            downloaded = 0

        try:
            with active_client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
                if resp.status_code == 206:
                    pass  # Partial content accepted
                elif resp.status_code == 200:
                    if existing_size > 0:
                        logger.info("Server did not honor Range request; restarting from byte 0.")
                    mode = "wb"
                    downloaded = 0
                    if total_size == 0 and "content-length" in resp.headers:
                        cl = resp.headers["content-length"]
                        if cl.isdigit():
                            total_size = int(cl)
                elif resp.status_code == 416:
                    logger.warning("Range not satisfiable (416). Restarting download from byte 0.")
                    partial_path.unlink(missing_ok=True)
                    with active_client.stream("GET", url, follow_redirects=True) as full_resp:
                        full_resp.raise_for_status()
                        if total_size == 0 and "content-length" in full_resp.headers:
                            cl = full_resp.headers["content-length"]
                            if cl.isdigit():
                                total_size = int(cl)
                        return _write_stream(full_resp, partial_path, "wb", 0, total_size)
                else:
                    resp.raise_for_status()

                return _write_stream(resp, partial_path, mode, downloaded, total_size)

        except httpx.HTTPStatusError as exc:
            raise MediaError(
                f"HTTP {exc.response.status_code} error downloading {url}: {exc}"
            ) from exc
        except httpx.RequestError as exc:
            raise MediaError(f"Network error downloading {url}: {exc}") from exc
        except OSError as exc:
            raise MediaError(f"Filesystem error during download of {url}: {exc}") from exc

    def _write_stream(
        resp: httpx.Response,
        part_path: Path,
        mode: str,
        current_downloaded: int,
        target_total: int,
    ) -> Path:
        if progress_callback and current_downloaded > 0:
            progress_callback(current_downloaded, target_total)

        with open(part_path, mode) as f:
            for chunk in resp.iter_bytes(chunk_size=chunk_size):
                f.write(chunk)
                current_downloaded += len(chunk)
                if progress_callback:
                    progress_callback(current_downloaded, target_total)

        final_size = part_path.stat().st_size
        if target_total > 0 and final_size != target_total:
            raise MediaError(
                f"Downloaded size mismatch for {target.name}: "
                f"expected {target_total} bytes, got {final_size} bytes"
            )

        part_path.replace(target)
        return target

    if client is not None:
        return _execute_download(client)

    with httpx.Client(timeout=timeout) as default_client:
        return _execute_download(default_client)
