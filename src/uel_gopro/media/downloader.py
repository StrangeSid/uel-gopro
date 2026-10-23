from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional
import httpx

from uel_gopro.core.exceptions import MediaError

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MB


def get_remote_file_size(
    url: str,
    *,
    client: Optional[httpx.Client] = None,
    timeout: float | httpx.Timeout = 10.0,
) -> int:
    """Query remote file size via HTTP HEAD request.

    GoPro firmware has a known bug in /gopro/media/list where the file size is
    represented as a 32-bit unsigned integer, overflowing for files >= 4 GB.
    HTTP HEAD returns the authoritative 64-bit Content-Length header.
    """
    def _do_head(c: httpx.Client) -> int:
        try:
            resp = c.head(url, follow_redirects=True)
            resp.raise_for_status()
            content_length = resp.headers.get("content-length")
            if content_length and content_length.isdigit():
                return int(content_length)
            return 0
        except httpx.HTTPStatusError as e:
            raise MediaError(
                f"HTTP {e.response.status_code} while querying file size for {url}"
            ) from e
        except httpx.RequestError as e:
            raise MediaError(f"Network error querying file size for {url}: {e}") from e

    if client is not None:
        return _do_head(client)

    with httpx.Client(timeout=timeout) as temp_client:
        return _do_head(temp_client)


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
    """Download a file with chunked streaming, resume capability, and size verification.

    1. Issues an HTTP HEAD request to obtain true 64-bit Content-Length (fixing 32-bit overflow).
    2. Writes to `<target_path>.partial` first.
    3. Resumes download using HTTP Range header if `<target_path>.partial` already exists.
    4. Atomically renames `<target_path>.partial` to `<target_path>` upon completion.
    5. Verifies downloaded file size matches expected size.
    6. Calls `progress_callback(bytes_downloaded, total_bytes)` throughout download.

    Args:
        url: Direct HTTP download URL.
        target_path: Final destination file path.
        client: Optional shared httpx.Client instance.
        chunk_size: Streaming chunk size in bytes (default 1MB).
        progress_callback: Optional callback receiving (bytes_downloaded, total_bytes).
        timeout: HTTP request timeout.
        expected_size: Optional expected file size. If None or if HEAD yields a valid
            Content-Length, the HEAD response Content-Length takes precedence.

    Returns:
        Path to the completed target file.

    Raises:
        MediaError: If download fails, HTTP error occurs, or final size mismatches.
    """
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    partial_path = target.with_name(f"{target.name}.partial")

    def _execute_download(active_client: httpx.Client) -> Path:
        # Step 1: Always check HEAD for accurate 64-bit Content-Length
        remote_size = get_remote_file_size(url, client=active_client, timeout=timeout)
        total_size = remote_size if remote_size > 0 else (expected_size or 0)

        # Step 2: Inspect existing .partial file
        existing_size = partial_path.stat().st_size if partial_path.exists() else 0

        if total_size > 0:
            if existing_size == total_size:
                logger.info(f"File already completely downloaded in partial buffer: {partial_path}")
                partial_path.replace(target)
                if progress_callback:
                    progress_callback(total_size, total_size)
                return target
            elif existing_size > total_size:
                logger.warning(
                    f"Existing partial file ({existing_size} bytes) exceeds total size "
                    f"({total_size} bytes). Resetting partial file."
                )
                partial_path.unlink(missing_ok=True)
                existing_size = 0

        # Step 3: Determine Range header and file open mode
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
                    # Partial Content accepted
                    pass
                elif resp.status_code == 200:
                    # Full content returned (Range not supported or ignored by server)
                    if existing_size > 0:
                        logger.info("Server did not honor Range request; restarting from byte 0.")
                    mode = "wb"
                    downloaded = 0
                    if total_size == 0 and "content-length" in resp.headers:
                        cl = resp.headers["content-length"]
                        if cl.isdigit():
                            total_size = int(cl)
                elif resp.status_code == 416:
                    # Range Not Satisfiable: partial file invalid, restart from 0
                    logger.warning("Range not satisfiable (416). Restarting download from byte 0.")
                    partial_path.unlink(missing_ok=True)
                    mode = "wb"
                    downloaded = 0
                    with active_client.stream("GET", url, follow_redirects=True) as full_resp:
                        full_resp.raise_for_status()
                        if total_size == 0 and "content-length" in full_resp.headers:
                            cl = full_resp.headers["content-length"]
                            if cl.isdigit():
                                total_size = int(cl)
                        return _write_stream(full_resp, partial_path, mode, downloaded, total_size)
                else:
                    resp.raise_for_status()

                return _write_stream(resp, partial_path, mode, downloaded, total_size)

        except httpx.HTTPStatusError as e:
            raise MediaError(
                f"HTTP {e.response.status_code} error downloading {url}: {e}"
            ) from e
        except httpx.RequestError as e:
            raise MediaError(f"Network error downloading {url}: {e}") from e
        except OSError as e:
            raise MediaError(f"Filesystem error during download of {url}: {e}") from e

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

        # Atomic rename to destination
        part_path.replace(target)
        return target

    if client is not None:
        return _execute_download(client)

    with httpx.Client(timeout=timeout) as default_client:
        return _execute_download(default_client)
