from __future__ import annotations

import concurrent.futures
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable, Optional
from uuid import uuid4

from pydantic import BaseModel

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import MediaError, UelError
from uel_gopro.core.models import CameraInfo, MediaItem, MediaType
from uel_gopro.media.downloader import download_file
from uel_gopro.media.exif import sync_file_time

logger = logging.getLogger(__name__)

PRIMARY_MEDIA_TYPES = frozenset({MediaType.VIDEO, MediaType.PHOTO})


def default_downloads_dir() -> Path:
    """Return the user's default Downloads directory."""
    return (Path.home() / "Downloads").expanduser()


def _candidate_available(candidate: Path) -> bool:
    partial = candidate.with_name(f"{candidate.name}.partial")
    return (
        not candidate.exists()
        and not candidate.is_symlink()
        and not partial.exists()
        and not partial.is_symlink()
    )


def unique_destination_path(dest_dir: Path, filename: str) -> Path:
    """Resolve a safe, collision-free destination path inside ``dest_dir``.

    Extracts only the basename from ``filename`` and rejects unsafe path
    components such as empty strings, ``.``, or ``..``.
    """
    if not isinstance(filename, str) or "\x00" in filename:
        raise MediaError(f"Refusing unsafe filename: {filename!r}")

    normalized = filename.replace("\\", "/")
    raw_segments = [seg for seg in normalized.split("/") if seg]
    if not raw_segments or raw_segments[-1].strip() in ("", ".", ".."):
        raise MediaError(f"Refusing unsafe filename: {filename!r}")

    name = Path(normalized).name.strip()
    if name in ("", ".", ".."):
        raise MediaError(f"Refusing unsafe filename: {filename!r}")

    candidate = dest_dir / name
    if _candidate_available(candidate):
        return candidate

    stem = Path(name).stem
    suffix = Path(name).suffix
    counter = 1
    while True:
        numbered = dest_dir / f"{stem}_{counter}{suffix}"
        if _candidate_available(numbered):
            return numbered
        counter += 1


class CaptureRecord(BaseModel):
    """Metadata describing a locally saved capture or snapshot."""

    id: str
    filename: str
    local_path: str
    size_bytes: int
    media_type: str
    source: str
    captured_at: str
    camera_directory: Optional[str] = None


class TransferProgress(BaseModel):
    """Live progress state for a camera media download job."""

    job_id: str
    filename: str
    status: str
    bytes_downloaded: int = 0
    total_bytes: int = 0
    percent: Optional[float] = None
    local_path: Optional[str] = None
    error: Optional[str] = None


class CaptureManager:
    """Coordinates camera media polling, downloads, and preview frame snapshots."""

    def __init__(
        self,
        downloads_dir: Optional[Path] = None,
        download_fn: Optional[Callable[..., Path]] = None,
        max_history: int = 100,
    ) -> None:
        self.downloads_dir = (downloads_dir or default_downloads_dir()).expanduser()
        self._download_fn = download_fn or download_file
        self._max_history = max(0, max_history)
        self._lock = threading.Lock()
        self._file_lock = threading.Lock()
        self._reserved_paths: set[Path] = set()
        self._captures: list[CaptureRecord] = []
        self._transfers: dict[str, TransferProgress] = {}
        self._futures: list[Future[Any]] = []
        self._shutdown = False
        self._shutdown_event = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uel-capture")

    def _prepend_capture(self, record: CaptureRecord) -> None:
        if self._max_history <= 0:
            return
        with self._lock:
            self._captures.insert(0, record)
            if len(self._captures) > self._max_history:
                del self._captures[self._max_history :]

    def _trim_transfers_locked(self) -> None:
        cap = max(self._max_history, 1)
        if len(self._transfers) <= cap:
            return
        finished_ids = [
            tid
            for tid, transfer in self._transfers.items()
            if transfer.status in ("completed", "failed")
        ]
        for tid in finished_ids:
            if len(self._transfers) <= cap:
                break
            del self._transfers[tid]

    def _update_transfer(self, job_id: str, **updates: Any) -> None:
        with self._lock:
            existing = self._transfers.get(job_id)
            if existing is not None:
                self._transfers[job_id] = existing.model_copy(update=updates)

    def _reserve_destination(self, filename: str) -> Path:
        with self._file_lock:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            candidate = unique_destination_path(self.downloads_dir, filename)
            if candidate not in self._reserved_paths:
                self._reserved_paths.add(candidate)
                return candidate

            stem = candidate.stem
            suffix = candidate.suffix
            counter = 1
            while True:
                numbered = self.downloads_dir / f"{stem}_{counter}{suffix}"
                if _candidate_available(numbered) and numbered not in self._reserved_paths:
                    self._reserved_paths.add(numbered)
                    return numbered
                counter += 1

    def _release_destination(self, path: Path) -> None:
        with self._file_lock:
            self._reserved_paths.discard(path)

    def snapshot_camera_media(self, client: GoProRestClient) -> set[tuple[str, str]]:
        """Capture a baseline set of ``(directory, filename)`` currently on the camera."""
        return {(item.directory, item.filename) for item in client.get_media_list()}

    def wait_for_new_media(
        self,
        client: GoProRestClient,
        baseline: set[tuple[str, str]],
        timeout_sec: float = 15.0,
        poll_interval: float = 0.5,
    ) -> list[MediaItem]:
        """Poll until the camera finishes encoding and exposes new primary media."""
        deadline = time.monotonic() + timeout_sec

        def _wait_next_poll() -> bool:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            sleep_for = max(0.0, min(poll_interval, remaining))
            return not self._shutdown_event.wait(timeout=sleep_for)

        while True:
            if self._shutdown_event.is_set():
                return []
            try:
                status = client.get_status()
                busy_flag = status.raw_status.get("8", status.raw_status.get(8))
                if status.encoding_active or busy_flag in (1, "1", True):
                    if not _wait_next_poll():
                        return []
                    continue
            except UelError as exc:
                logger.debug("Transient error polling camera status: %s", exc)
                if not _wait_next_poll():
                    return []
                continue

            try:
                media_items = client.get_media_list()
            except UelError as exc:
                logger.debug("Transient error polling camera media list: %s", exc)
                if not _wait_next_poll():
                    return []
                continue

            new_items = [
                item
                for item in media_items
                if (item.directory, item.filename) not in baseline
                and item.media_type in PRIMARY_MEDIA_TYPES
            ]
            if new_items:
                return sorted(new_items, key=lambda item: (item.directory, item.filename))

            if not _wait_next_poll():
                return []

    def _download_single_item(
        self,
        info: CameraInfo,
        item: MediaItem,
        *,
        on_progress: Callable[[int, int], None],
        on_reserved: Optional[Callable[[Path], None]] = None,
    ) -> CaptureRecord:
        dest = self._reserve_destination(item.filename)
        try:
            if on_reserved is not None:
                on_reserved(dest)

            url = f"http://{info.ip_address}:{info.port}{item.download_url_path}"
            completed = self._download_fn(
                url,
                dest,
                progress_callback=on_progress,
                expected_size=item.size_bytes or None,
            )
            if item.mod_time:
                try:
                    sync_file_time(completed, timestamp=item.mod_time)
                except Exception as exc:
                    logger.warning("Failed to sync file time for %s: %s", completed, exc)

            size_bytes = completed.stat().st_size if completed.exists() else item.size_bytes
            record = CaptureRecord(
                id=uuid4().hex,
                filename=completed.name,
                local_path=str(completed),
                size_bytes=size_bytes,
                media_type=item.media_type.value,
                source="camera",
                captured_at=datetime.now(timezone.utc).isoformat(),
                camera_directory=item.directory,
            )
            self._prepend_capture(record)
            return record
        finally:
            self._release_destination(dest)

    def download_camera_item(
        self,
        info: CameraInfo,
        item: MediaItem,
        job_id: Optional[str] = None,
    ) -> CaptureRecord:
        """Download a single camera media item into ``self.downloads_dir``."""
        active_job_id = job_id or uuid4().hex
        initial_total = item.size_bytes or 0
        with self._lock:
            if active_job_id not in self._transfers:
                self._transfers[active_job_id] = TransferProgress(
                    job_id=active_job_id,
                    filename=item.filename,
                    status="downloading",
                    bytes_downloaded=0,
                    total_bytes=initial_total,
                    percent=0.0 if initial_total > 0 else None,
                )
                self._trim_transfers_locked()
            else:
                self._transfers[active_job_id] = self._transfers[active_job_id].model_copy(
                    update={
                        "filename": item.filename,
                        "status": "downloading",
                        "bytes_downloaded": 0,
                        "total_bytes": initial_total,
                        "percent": 0.0 if initial_total > 0 else None,
                        "local_path": None,
                        "error": None,
                    }
                )

        def on_progress(downloaded: int, total: int) -> None:
            effective_total = total if total > 0 else initial_total
            percent = (
                round(min(100.0, (downloaded / effective_total) * 100.0), 2)
                if effective_total > 0
                else None
            )
            self._update_transfer(
                active_job_id,
                status="downloading",
                bytes_downloaded=downloaded,
                total_bytes=effective_total,
                percent=percent,
            )

        def on_reserved(dest: Path) -> None:
            if dest.name != item.filename:
                self._update_transfer(active_job_id, filename=dest.name)

        try:
            record = self._download_single_item(
                info,
                item,
                on_progress=on_progress,
                on_reserved=on_reserved,
            )
            self._update_transfer(
                active_job_id,
                filename=record.filename,
                status="completed",
                bytes_downloaded=record.size_bytes,
                total_bytes=record.size_bytes if record.size_bytes > 0 else initial_total,
                percent=100.0,
                local_path=record.local_path,
                error=None,
            )
            return record
        except Exception as exc:
            self._update_transfer(active_job_id, status="failed", error=str(exc))
            if isinstance(exc, MediaError):
                raise
            raise MediaError(f"Failed to download {item.filename}: {exc}") from exc

    def save_frame_snapshot(
        self,
        jpeg_bytes: bytes,
        prefix: str = "gopro_snapshot",
    ) -> CaptureRecord:
        """Atomically save a JPEG preview frame snapshot into ``self.downloads_dir``."""
        if not jpeg_bytes:
            raise MediaError("Cannot save an empty snapshot frame.")

        if (
            not isinstance(prefix, str)
            or "\x00" in prefix
            or "/" in prefix
            or "\\" in prefix
        ):
            raise MediaError(f"Refusing unsafe snapshot prefix: {prefix!r}")

        safe_prefix = prefix.strip()
        if safe_prefix in ("", ".", ".."):
            raise MediaError(f"Refusing unsafe snapshot prefix: {prefix!r}")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self._reserve_destination(f"{safe_prefix}_{stamp}.jpg")
        partial_path = dest.with_name(f"{dest.name}.partial")
        created_partial = False

        try:
            fd = os.open(partial_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            created_partial = True
            try:
                f = os.fdopen(fd, "wb")
            except BaseException:
                os.close(fd)
                raise
            with f:
                f.write(jpeg_bytes)
            partial_path.replace(dest)
        except OSError as exc:
            if created_partial:
                try:
                    partial_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise MediaError(f"Failed to write snapshot {dest.name}: {exc}") from exc
        finally:
            self._release_destination(dest)

        record = CaptureRecord(
            id=uuid4().hex,
            filename=dest.name,
            local_path=str(dest),
            size_bytes=len(jpeg_bytes),
            media_type="photo",
            source="snapshot",
            captured_at=datetime.now(timezone.utc).isoformat(),
            camera_directory=None,
        )
        self._prepend_capture(record)
        return record

    def enqueue_post_capture_sync(
        self,
        client: GoProRestClient,
        info: CameraInfo,
        baseline: set[tuple[str, str]],
        timeout_sec: float = 15.0,
        poll_interval: float = 0.5,
    ) -> str:
        """Queue a background job that waits for new camera media and downloads it."""
        job_id = uuid4().hex
        with self._lock:
            if self._shutdown:
                raise MediaError("CaptureManager has been shut down.")
            self._transfers[job_id] = TransferProgress(
                job_id=job_id,
                filename="Waiting for camera...",
                status="waiting",
            )
            self._trim_transfers_locked()

        def _worker() -> None:
            try:
                items = self.wait_for_new_media(
                    client,
                    baseline,
                    timeout_sec=timeout_sec,
                    poll_interval=poll_interval,
                )
                if not items:
                    error_msg = (
                        "CaptureManager shut down before new media appeared"
                        if self._shutdown_event.is_set()
                        else "No new captured media appeared on camera before timeout"
                    )
                    self._update_transfer(
                        job_id,
                        status="failed",
                        error=error_msg,
                    )
                    return

                if len(items) == 1:
                    self.download_camera_item(info, items[0], job_id=job_id)
                    return

                total_expected = sum(item.size_bytes or 0 for item in items)
                completed_bytes = 0
                last_record: Optional[CaptureRecord] = None
                self._update_transfer(
                    job_id,
                    filename=items[0].filename,
                    status="downloading",
                    bytes_downloaded=0,
                    total_bytes=total_expected,
                    percent=0.0 if total_expected > 0 else None,
                    local_path=None,
                    error=None,
                )

                for item in items:
                    item_expected = item.size_bytes or 0

                    def on_item_progress(
                        downloaded: int,
                        total: int,
                        *,
                        base: int = completed_bytes,
                        fallback_total: int = item_expected,
                    ) -> None:
                        item_total = total if total > 0 else fallback_total
                        agg_downloaded = base + downloaded
                        agg_total = max(total_expected, base + item_total)
                        percent = (
                            round(min(100.0, (agg_downloaded / agg_total) * 100.0), 2)
                            if agg_total > 0
                            else None
                        )
                        self._update_transfer(
                            job_id,
                            status="downloading",
                            bytes_downloaded=agg_downloaded,
                            total_bytes=agg_total,
                            percent=percent,
                        )

                    def on_item_reserved(dest: Path) -> None:
                        self._update_transfer(job_id, filename=dest.name)

                    last_record = self._download_single_item(
                        info,
                        item,
                        on_progress=on_item_progress,
                        on_reserved=on_item_reserved,
                    )
                    completed_bytes += last_record.size_bytes

                assert last_record is not None
                final_total = max(total_expected, completed_bytes)
                self._update_transfer(
                    job_id,
                    filename=last_record.filename,
                    status="completed",
                    bytes_downloaded=completed_bytes,
                    total_bytes=final_total,
                    percent=100.0,
                    local_path=last_record.local_path,
                    error=None,
                )
            except Exception as exc:
                logger.warning("Post-capture sync job %s failed: %s", job_id, exc)
                self._update_transfer(job_id, status="failed", error=str(exc))

        try:
            future = self._executor.submit(_worker)
        except RuntimeError as exc:
            with self._lock:
                self._transfers.pop(job_id, None)
            raise MediaError(f"CaptureManager has been shut down: {exc}") from exc

        with self._lock:
            self._futures = [f for f in self._futures if not f.done()]
            self._futures.append(future)
        return job_id

    def list_captures(self) -> list[dict[str, Any]]:
        """Return recent capture records as serialized dictionaries."""
        with self._lock:
            return [record.model_dump() for record in self._captures]

    def list_transfers(self) -> list[dict[str, Any]]:
        """Return tracked transfer progress entries as serialized dictionaries."""
        with self._lock:
            return [transfer.model_dump() for transfer in self._transfers.values()]

    def wait_idle(self, timeout: Optional[float] = None) -> bool:
        """Wait for all queued background capture transfers to finish."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                pending = [f for f in self._futures if not f.done()]
                self._futures = pending
            if not pending:
                return True

            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if remaining is not None and remaining <= 0.0:
                return False

            _, not_done = concurrent.futures.wait(pending, timeout=remaining)
            if not_done and deadline is not None and time.monotonic() >= deadline:
                return False

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the background download executor."""
        with self._lock:
            self._shutdown = True
        self._shutdown_event.set()
        self._executor.shutdown(wait=wait)
