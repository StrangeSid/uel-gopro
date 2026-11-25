from __future__ import annotations

from collections.abc import Iterator
import io
import logging
import math
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Optional

from uel_gopro.core.exceptions import CommandError
from uel_gopro.stream.preview import DEFAULT_STREAM_URL

logger = logging.getLogger(__name__)

JPEG_SOI = b"\xff\xd8"
JPEG_EOI = b"\xff\xd9"
MAX_BUFFER_BYTES = 16 * 1024 * 1024


def build_mjpeg_ffmpeg_command(
    stream_url: str = DEFAULT_STREAM_URL,
    ffmpeg_path: str = "ffmpeg",
    fps: int = 30,
    quality: int = 5,
) -> list[str]:
    """Build low-latency FFmpeg arguments to transcode a live stream to stdout MJPEG."""
    if not isinstance(stream_url, str) or not stream_url.strip():
        raise CommandError("stream_url must be a non-empty string")
    if not isinstance(ffmpeg_path, str) or not ffmpeg_path.strip():
        raise CommandError("ffmpeg_path must be a non-empty string")
    if isinstance(fps, bool) or not isinstance(fps, int) or fps < 1 or fps > 60:
        raise CommandError(f"fps must be an integer between 1 and 60, got {fps!r}")
    if isinstance(quality, bool) or not isinstance(quality, int) or quality < 2 or quality > 31:
        raise CommandError(f"quality must be an integer between 2 and 31, got {quality!r}")

    if stream_url.startswith("udp://") and "?" not in stream_url:
        effective_url = f"{stream_url}?overrun_nonfatal=1&fifo_size=5570"
    else:
        effective_url = stream_url

    return [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-fflags",
        "+nobuffer+discardcorrupt",
        "-flags",
        "low_delay",
        "-max_delay",
        "0",
        "-analyzeduration",
        "100000",
        "-probesize",
        "65536",
        "-threads",
        "1",
        "-i",
        effective_url,
        "-an",
        "-threads",
        "1",
        "-fps_mode",
        "passthrough",
        "-strict",
        "unofficial",
        "-q:v",
        str(quality),
        "-flush_packets",
        "1",
        "-f",
        "mjpeg",
        "pipe:1",
    ]


def extract_jpeg_frames(buffer: bytearray) -> list[bytes]:
    """Extract all complete JPEG SOI..EOI frames from ``buffer`` in place.

    Discards leading non-SOI noise, preserves a trailing ``0xff`` byte in case
    an SOI marker spans chunk boundaries, and clears oversized incomplete buffers
    to prevent unbounded memory growth.
    """
    frames: list[bytes] = []
    while True:
        start = buffer.find(JPEG_SOI)
        if start == -1:
            if buffer.endswith(b"\xff"):
                del buffer[:-1]
            else:
                buffer.clear()
            break

        if start > 0:
            del buffer[:start]

        end = buffer.find(JPEG_EOI, 2)
        if end == -1:
            if len(buffer) > MAX_BUFFER_BYTES:
                buffer.clear()
            break

        frames.append(bytes(buffer[: end + 2]))
        del buffer[: end + 2]

    return frames


def _wait_process(process: Any, timeout: float) -> Optional[int]:
    wait_fn = getattr(process, "wait", None)
    if not callable(wait_fn):
        return getattr(process, "returncode", None)
    try:
        return wait_fn(timeout=timeout)
    except TypeError:
        return wait_fn()


def _terminate_process(process: Any) -> None:
    poll_fn = getattr(process, "poll", None)
    still_running = poll_fn() is None if callable(poll_fn) else True
    if not still_running:
        return

    terminate_fn = getattr(process, "terminate", None)
    if callable(terminate_fn):
        try:
            terminate_fn()
        except OSError:
            pass

    try:
        _wait_process(process, timeout=1.0)
    except subprocess.TimeoutExpired:
        kill_fn = getattr(process, "kill", None)
        if callable(kill_fn):
            try:
                kill_fn()
            except OSError:
                pass
        try:
            _wait_process(process, timeout=1.0)
        except Exception:
            pass
    except Exception:
        pass


def _close_process_pipes(process: Any) -> None:
    for attr in ("stdout", "stderr", "stdin"):
        stream = getattr(process, attr, None)
        if stream is not None:
            close_fn = getattr(stream, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except (OSError, ValueError):
                    pass


class _StderrDrainer:
    """Continuously drains a subprocess stderr pipe into a bounded tail buffer."""

    def __init__(self, stderr: Any, max_bytes: int = 4096) -> None:
        self._stderr = stderr
        self._max_bytes = max_bytes
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        if stderr is not None:
            self._thread = threading.Thread(
                target=self._drain,
                name="uel-mjpeg-stderr",
                daemon=True,
            )
            self._thread.start()

    def _drain(self) -> None:
        read_fn = (
            self._stderr.read1
            if isinstance(self._stderr, io.BufferedIOBase)
            else getattr(self._stderr, "read", None)
        )
        if not callable(read_fn):
            return
        while True:
            try:
                chunk = read_fn(1024)
            except (OSError, ValueError):
                break
            except Exception:
                break
            if not chunk:
                break
            if isinstance(chunk, str):
                chunk_bytes = chunk.encode("utf-8", errors="replace")
            elif isinstance(chunk, (bytes, bytearray)):
                chunk_bytes = bytes(chunk)
            else:
                break
            with self._lock:
                self._buf.extend(chunk_bytes)
                if len(self._buf) > self._max_bytes:
                    del self._buf[: -self._max_bytes]

    def collect(self, join_timeout: float = 0.2) -> str:
        """Wait briefly for the drainer thread and return the captured stderr tail."""
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=join_timeout)
        with self._lock:
            return self._buf.decode("utf-8", errors="replace").strip()


class MjpegStreamTranscoder:
    """Single-FFmpeg UDP-to-MJPEG decoder that fans out frames to multiple consumers."""

    def __init__(
        self,
        stream_url: str = DEFAULT_STREAM_URL,
        ffmpeg_path: str = "ffmpeg",
        fps: int = 30,
        quality: int = 5,
        popen_factory: Optional[Callable[..., Any]] = None,
        restart_delay_sec: float = 1.0,
        read_chunk_size: int = 8192,
    ) -> None:
        # Validate command arguments eagerly so configuration errors fail fast.
        build_mjpeg_ffmpeg_command(
            stream_url=stream_url,
            ffmpeg_path=ffmpeg_path,
            fps=fps,
            quality=quality,
        )
        if (
            isinstance(restart_delay_sec, bool)
            or not isinstance(restart_delay_sec, (int, float))
            or math.isnan(restart_delay_sec)
            or math.isinf(restart_delay_sec)
            or restart_delay_sec < 0
        ):
            raise CommandError(
                f"restart_delay_sec must be a non-negative finite number, got {restart_delay_sec!r}"
            )
        if (
            isinstance(read_chunk_size, bool)
            or not isinstance(read_chunk_size, int)
            or read_chunk_size <= 0
        ):
            raise CommandError(
                f"read_chunk_size must be a positive integer, got {read_chunk_size!r}"
            )

        self.stream_url = stream_url
        self.ffmpeg_path = ffmpeg_path
        self.fps = fps
        self.quality = quality
        self._popen_factory = popen_factory
        self.restart_delay_sec = float(restart_delay_sec)
        self.read_chunk_size = read_chunk_size

        self._lifecycle_lock = threading.Lock()
        self._cond = threading.Condition()
        self._stop_event = threading.Event()
        self._latest_frame: Optional[bytes] = None
        self._frame_seq = 0
        self._last_frame_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._running = False
        self._stop_requested = False
        self._process: Any = None
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the background FFmpeg reader thread if not already running."""
        with self._lifecycle_lock:
            with self._cond:
                if self._running and not self._stop_requested:
                    return
                prev_thread = self._reader_thread

            if prev_thread is not None and prev_thread.is_alive():
                prev_thread.join(timeout=5.0)

            if self._popen_factory is None and shutil.which(self.ffmpeg_path) is None:
                raise CommandError(f"FFmpeg binary not found: {self.ffmpeg_path}")

            with self._cond:
                self._latest_frame = None
                self._last_frame_at = None
                self._last_error = None
                self._stop_requested = False
                self._stop_event.clear()
                self._running = True
                thread = threading.Thread(
                    target=self._reader_loop,
                    name="uel-mjpeg-transcoder",
                    daemon=True,
                )
                self._reader_thread = thread
                thread.start()

    def stop(self) -> None:
        """Stop FFmpeg, unblock all active frame consumers, and join the reader thread."""
        with self._lifecycle_lock:
            with self._cond:
                self._stop_requested = True
                self._stop_event.set()
                process = self._process
                thread = self._reader_thread
                self._cond.notify_all()

            if process is not None:
                _terminate_process(process)

            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=5.0)

    def get_latest_frame(self) -> Optional[bytes]:
        """Return the most recently decoded JPEG frame, if any."""
        with self._cond:
            return self._latest_frame

    def status(self) -> dict[str, Any]:
        """Return a thread-safe snapshot of transcoder health and stream metrics."""
        with self._cond:
            last_frame_age_sec: Optional[float] = None
            if self._last_frame_at is not None:
                last_frame_age_sec = max(0.0, time.monotonic() - self._last_frame_at)
            return {
                "running": self._running,
                "stream_url": self.stream_url,
                "has_frame": self._latest_frame is not None,
                "frame_seq": self._frame_seq,
                "last_frame_age_sec": last_frame_age_sec,
                "error": self._last_error,
            }

    def iter_frames(
        self,
        stop_event: Optional[threading.Event] = None,
        timeout_sec: float = 1.0,
    ) -> Iterator[bytes]:
        """Yield JPEG frames as they arrive until ``stop()`` or ``stop_event`` is set."""
        wait_timeout = 0.05 if math.isnan(timeout_sec) else max(0.05, float(timeout_sec))
        last_seq = 0
        while True:
            with self._cond:
                if self._stop_requested or (stop_event is not None and stop_event.is_set()):
                    return

                if self._latest_frame is not None and self._frame_seq > last_seq:
                    frame = self._latest_frame
                    last_seq = self._frame_seq
                else:
                    self._cond.wait(timeout=wait_timeout)
                    if self._stop_requested or (stop_event is not None and stop_event.is_set()):
                        return
                    if self._latest_frame is not None and self._frame_seq > last_seq:
                        frame = self._latest_frame
                        last_seq = self._frame_seq
                    else:
                        continue
            yield frame

    def _spawn_process(self, cmd: list[str]) -> Any:
        factory = self._popen_factory or subprocess.Popen
        return factory(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

    def _finish_and_read_error(
        self,
        process: Any,
        stderr_drainer: _StderrDrainer,
    ) -> tuple[str, str]:
        if self._stop_requested:
            _terminate_process(process)
            _close_process_pipes(process)
            stderr_drainer.collect(join_timeout=0.2)
            return ("", "")

        poll_fn = getattr(process, "poll", None)
        if callable(poll_fn) and poll_fn() is None:
            try:
                _wait_process(process, timeout=0.5)
            except subprocess.TimeoutExpired:
                _terminate_process(process)
            except Exception:
                _terminate_process(process)

        stderr_text = stderr_drainer.collect(join_timeout=0.2)
        _close_process_pipes(process)

        rc = poll_fn() if callable(poll_fn) else getattr(process, "returncode", None)
        if stderr_text:
            return (stderr_text[-500:], "")
        if rc is not None:
            return ("", f"FFmpeg exited with code {rc}")
        return ("", "FFmpeg stream ended unexpectedly")

    def _reader_loop(self) -> None:
        try:
            min_frame_interval = 0.0 if self.fps >= 30 else 1.0 / self.fps
            cmd = build_mjpeg_ffmpeg_command(
                stream_url=self.stream_url,
                ffmpeg_path=self.ffmpeg_path,
                fps=self.fps,
                quality=self.quality,
            )
            while not self._stop_requested:
                try:
                    process = self._spawn_process(cmd)
                except Exception as exc:
                    with self._cond:
                        self._process = None
                        self._last_error = f"Failed to start FFmpeg: {exc}"
                        self._cond.notify_all()
                    if self._stop_event.wait(self.restart_delay_sec):
                        break
                    continue

                with self._cond:
                    if self._stop_requested:
                        self._process = None
                        should_abort = True
                    else:
                        self._process = process
                        should_abort = False

                if should_abort:
                    _terminate_process(process)
                    _close_process_pipes(process)
                    break

                stdout = getattr(process, "stdout", None)
                if stdout is None:
                    with self._cond:
                        if self._process is process:
                            self._process = None
                        self._last_error = "FFmpeg process has no stdout pipe"
                        self._cond.notify_all()
                    _terminate_process(process)
                    _close_process_pipes(process)
                    if self._stop_event.wait(self.restart_delay_sec):
                        break
                    continue

                stderr_drainer = _StderrDrainer(getattr(process, "stderr", None))
                buf = bytearray()
                published_in_proc = False
                read_fn = (
                    stdout.read1 if isinstance(stdout, io.BufferedIOBase) else stdout.read
                )
                read_exc: Optional[str] = None
                try:
                    while not self._stop_requested:
                        chunk = read_fn(self.read_chunk_size)
                        if not chunk:
                            break
                        buf.extend(chunk)
                        frames = extract_jpeg_frames(buf)
                        if frames:
                            now = time.monotonic()
                            with self._cond:
                                if (
                                    not published_in_proc
                                    or min_frame_interval <= 0.0
                                    or self._last_frame_at is None
                                    or (now - self._last_frame_at) >= min_frame_interval
                                ):
                                    published_in_proc = True
                                    self._latest_frame = frames[-1]
                                    self._frame_seq += (
                                        1 if min_frame_interval > 0.0 else len(frames)
                                    )
                                    self._last_frame_at = now
                                    self._last_error = None
                                    self._cond.notify_all()
                except Exception as exc:
                    if not self._stop_requested:
                        read_exc = f"Stream read error: {exc}"
                finally:
                    stderr_msg, exit_msg = self._finish_and_read_error(
                        process, stderr_drainer
                    )
                    with self._cond:
                        if self._process is process:
                            self._process = None
                        if not self._stop_requested:
                            if stderr_msg:
                                self._last_error = stderr_msg
                            elif read_exc:
                                self._last_error = read_exc
                            elif exit_msg:
                                self._last_error = exit_msg
                            self._cond.notify_all()

                if self._stop_requested:
                    break

                if self._stop_event.wait(self.restart_delay_sec):
                    break
        finally:
            with self._cond:
                self._running = False
                self._process = None
                self._cond.notify_all()
