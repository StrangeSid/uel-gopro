from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import socket
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from uel_gopro.api.capabilities import detect_camera_model, resolve_setting_capabilities
from uel_gopro.api.rest import SETTING_ALIASES, GoProRestClient, resolve_setting_id
from uel_gopro.core.exceptions import (
    CameraNotFoundError,
    CommandError,
    MediaError,
    TransportError,
    UelError,
)
from uel_gopro.core.models import CameraInfo, CameraStatus
from uel_gopro.stream.capture import PRIMARY_MEDIA_TYPES, CaptureManager
from uel_gopro.stream.live_ui import render_live_page, render_widget_js
from uel_gopro.stream.preview import DEFAULT_STREAM_URL
from uel_gopro.stream.transcoder import MjpegStreamTranscoder

logger = logging.getLogger(__name__)

MAX_JSON_BODY_BYTES = 64 * 1024


def _clean_preset_label(raw: Any, prefix: str) -> str:
    text = "" if raw is None else str(raw)
    return text.replace(prefix, "").replace("_", " ").strip().title()


def parse_preset_groups(raw_presets: Dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize raw OpenGoPro preset JSON into UI-friendly preset groups."""
    groups: list[dict[str, Any]] = []
    for group in (raw_presets or {}).get("presetGroupArray") or []:
        if not isinstance(group, dict):
            continue
        group_id = group.get("id")
        group_name = _clean_preset_label(group_id, "PRESET_GROUP_ID_")

        presets_out: list[dict[str, Any]] = []
        for preset in group.get("presetArray") or group.get("presets") or []:
            if not isinstance(preset, dict):
                continue
            preset_id = preset.get("id")
            raw_title = (
                preset.get("customName")
                or preset.get("title")
                or preset.get("titleId")
                or (f"Preset {preset_id}" if preset_id is not None else "Preset")
            )
            title = _clean_preset_label(raw_title, "PRESET_TITLE_")
            presets_out.append(
                {
                    "id": preset_id,
                    "name": title,
                    "user_defined": bool(preset.get("userDefined")),
                }
            )

        groups.append(
            {
                "id": group_id,
                "name": group_name,
                "presets": presets_out,
            }
        )
    return groups


def find_photo_preset_id(raw_presets: Dict[str, Any]) -> Optional[int]:
    """Return the first valid integer preset ID inside a Photo preset group."""
    for group in (raw_presets or {}).get("presetGroupArray") or []:
        if not isinstance(group, dict):
            continue
        raw_group_id = group.get("id", "")
        group_str = "" if raw_group_id is None else str(raw_group_id)
        if "PHOTO" not in group_str.upper() and group_str != "1001":
            continue

        for preset in group.get("presetArray") or group.get("presets") or []:
            if not isinstance(preset, dict):
                continue
            pid = preset.get("id")
            if isinstance(pid, bool):
                continue
            if isinstance(pid, int):
                return pid
            if isinstance(pid, str):
                stripped = pid.strip()
                if stripped.isascii() and stripped.isdigit():
                    return int(stripped)
    return None


def _require_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    val = payload[key]
    if not isinstance(val, bool):
        raise CommandError(f"Field '{key}' must be a boolean.")
    return val


class LiveCameraController:
    """Thread-safe coordinator for GoPro live control, preview transcoding, and captures."""

    def __init__(
        self,
        client: GoProRestClient,
        info: CameraInfo,
        downloads_dir: Optional[Path] = None,
        stream_url: str = DEFAULT_STREAM_URL,
        ffmpeg_path: str = "ffmpeg",
        fps: int = 30,
        keep_alive_interval: float = 5.0,
        transcoder: Optional[MjpegStreamTranscoder] = None,
        capture_manager: Optional[CaptureManager] = None,
        model_override: Optional[str] = None,
    ) -> None:
        self.client = client
        self.info = info
        self._model_override = (
            model_override.strip()
            if isinstance(model_override, str) and model_override.strip()
            else None
        )
        self.transcoder = (
            transcoder
            if transcoder is not None
            else MjpegStreamTranscoder(
                stream_url=stream_url,
                ffmpeg_path=ffmpeg_path,
                fps=fps,
            )
        )
        self.captures = (
            capture_manager
            if capture_manager is not None
            else CaptureManager(downloads_dir=downloads_dir)
        )
        self.keep_alive_interval = float(keep_alive_interval)
        self._cmd_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._keep_alive_stop = threading.Event()
        self._keep_alive_thread: Optional[threading.Thread] = None
        self._recording_started_at: Optional[float] = None
        self._recording_epoch: int = 0
        self._recording_baseline: Optional[set[tuple[str, str]]] = None
        self._stream_enabled: bool = False
        self._started: bool = False
        self._stopped: bool = False

    def _keep_alive_loop(self) -> None:
        while not self._keep_alive_stop.wait(self.keep_alive_interval):
            try:
                self.client.keep_alive()
            except Exception as exc:
                logger.debug("Keep-alive ping failed: %s", exc)

    def start(self, start_stream: bool = True) -> None:
        """Initialize USB control, enrich camera metadata, and start background services."""
        with self._cmd_lock:
            if self._stopped:
                raise CommandError("Controller has been stopped.")
            if self._started:
                return

        try:
            self.client.enable_wired_usb(True)
        except Exception as exc:
            logger.warning("Could not enable wired USB control: %s", exc)

        try:
            details = self.client.get_camera_info() or {}
            if isinstance(details, dict):
                self.info.model_name = details.get("model_name") or self.info.model_name
                self.info.firmware_version = (
                    details.get("firmware_version") or self.info.firmware_version
                )
                self.info.serial_number = details.get("serial_number") or self.info.serial_number
        except Exception as exc:
            logger.debug("Camera info enrichment unavailable: %s", exc)

        if self._model_override:
            self.info.model_name = detect_camera_model(model_name=self._model_override)

        with self._cmd_lock:
            if self._stopped:
                raise CommandError("Controller has been stopped.")
            if self._started:
                return
            if self.keep_alive_interval > 0 and (
                self._keep_alive_thread is None or not self._keep_alive_thread.is_alive()
            ):
                self._keep_alive_stop.clear()
                self._keep_alive_thread = threading.Thread(
                    target=self._keep_alive_loop,
                    name="uel-live-keepalive",
                    daemon=True,
                )
                self._keep_alive_thread.start()
            self._started = True

        if start_stream:
            try:
                self.start_preview()
            except Exception:
                with self._cmd_lock:
                    self._started = False
                self._stop_keep_alive()
                raise

    def _stop_keep_alive(self) -> None:
        with self._cmd_lock:
            self._keep_alive_stop.set()
            thread = self._keep_alive_thread
            self._keep_alive_thread = None
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=2.0)

    def stop(self) -> None:
        """Stop keep-alive, transcoder, capture workers, and preview stream."""
        # Signal stop and unblock any active MJPEG stream consumers before taking _cmd_lock.
        self._keep_alive_stop.set()
        self.transcoder.stop()

        with self._cmd_lock:
            self._stopped = True
            self._started = False
            was_enabled = self._stream_enabled
            self._stream_enabled = False
            self._keep_alive_stop.set()
            ka_thread = self._keep_alive_thread
            self._keep_alive_thread = None

        if (
            ka_thread is not None
            and ka_thread.is_alive()
            and ka_thread is not threading.current_thread()
        ):
            ka_thread.join(timeout=2.0)

        # Ensure transcoder could not have been started right before _stopped = True.
        self.transcoder.stop()
        self.captures.shutdown(wait=True)

        if was_enabled:
            try:
                self.client.stop_preview_stream()
            except Exception as exc:
                logger.debug("Ignoring preview stream stop error during shutdown: %s", exc)

    def _ensure_camera_preview_started(self) -> None:
        """Start camera preview stream, recovering once from HTTP 409 already-active state."""
        try:
            self.client.start_preview_stream()
        except CommandError as exc:
            if "409" not in str(exc):
                raise
            logger.debug("Preview stream returned 409 (already active); stopping and retrying")
            try:
                self.client.stop_preview_stream()
            except Exception as stop_exc:
                logger.debug("Ignoring preview stream stop error before retry: %s", stop_exc)
            self.client.start_preview_stream()

    def _best_effort_restart_preview(self) -> None:
        if not self._stream_enabled:
            return
        try:
            self._ensure_camera_preview_started()
        except Exception as exc:
            logger.debug("Could not re-arm preview stream: %s", exc)

    def _best_effort_snapshot_baseline(self) -> set[tuple[str, str]]:
        try:
            return self.captures.snapshot_camera_media(self.client)
        except UelError as exc:
            logger.debug("Could not snapshot baseline media: %s", exc)
            return set()

    def get_state(self) -> dict[str, Any]:
        """Return aggregated camera status, settings, stream health, and capture history."""
        with self._state_lock:
            pre_epoch = self._recording_epoch

        status_error: Optional[str] = None
        settings: dict[str, Any] = {}
        try:
            status = self.client.get_status()
        except Exception as exc:
            status = CameraStatus(connected=False)
            status_error = str(exc)
        else:
            try:
                raw_state = self.client.get_raw_state() or {}
                raw_settings = raw_state.get("settings")
                if isinstance(raw_settings, dict):
                    settings = raw_settings
            except Exception as exc:
                logger.debug("Could not read camera settings state: %s", exc)

        with self._state_lock:
            if status_error is None and not status.is_recording:
                if self._recording_epoch == pre_epoch:
                    self._recording_started_at = None
                elapsed = 0.0
            elif status.is_recording:
                started_at = self._recording_started_at
                elapsed = (
                    round(max(0.0, time.monotonic() - started_at), 2)
                    if started_at is not None
                    else 0.0
                )
            else:
                elapsed = 0.0

        payload: dict[str, Any] = {
            "ok": True,
            "camera": self.info.model_dump(),
            "status": status.model_dump(),
            "settings": settings,
            "capabilities": self.get_capabilities(raw_settings=settings),
            "stream": self.transcoder.status(),
            "downloads_dir": str(self.captures.downloads_dir),
            "transfers": self.captures.list_transfers(),
            "captures": self.captures.list_captures(),
            "recording_elapsed_sec": elapsed,
        }
        if status_error:
            payload["status_error"] = status_error
        return payload

    def get_capabilities(
        self,
        raw_settings: Optional[Dict[Any, Any]] = None,
    ) -> dict[str, Any]:
        """Resolve model- and setting-aware valid options for camera settings."""
        if raw_settings is None:
            raw_state = self.client.get_raw_state() or {}
            candidate = raw_state.get("settings")
            raw_settings = candidate if isinstance(candidate, dict) else {}
        return resolve_setting_capabilities(
            model_name=self._model_override or self.info.model_name,
            current_settings=raw_settings,
            firmware_version=self.info.firmware_version,
        )

    def get_presets(self) -> dict[str, Any]:
        """Fetch and normalize camera presets."""
        raw = self.client.get_presets() or {}
        return {
            "ok": True,
            "groups": parse_preset_groups(raw),
            "raw": raw,
        }

    def get_settings(self) -> dict[str, Any]:
        """Fetch current raw camera settings along with supported CLI/UI aliases."""
        raw = self.client.get_raw_state() or {}
        settings = raw.get("settings", {}) or {}
        return {
            "ok": True,
            "settings": settings,
            "aliases": dict(SETTING_ALIASES),
            "capabilities": self.get_capabilities(raw_settings=settings),
        }

    def get_media_list(self) -> dict[str, Any]:
        """Fetch serialized SD card media listing."""
        items = self.client.get_media_list()
        return {
            "ok": True,
            "items": [item.model_dump() for item in items],
        }

    def start_recording(self) -> dict[str, Any]:
        """Snapshot baseline media and start video recording."""
        with self._cmd_lock:
            baseline = self._best_effort_snapshot_baseline()
            self.client.shutter_start()
            self._recording_baseline = baseline
            with self._state_lock:
                self._recording_started_at = time.monotonic()
                self._recording_epoch += 1
            return {"ok": True, "recording": True}

    def stop_recording(self, auto_download: bool = True) -> dict[str, Any]:
        """Stop video recording and optionally queue post-capture auto-download."""
        with self._cmd_lock:
            baseline = self._recording_baseline
            if auto_download and baseline is None:
                baseline = self._best_effort_snapshot_baseline()
            self.client.shutter_stop()
            with self._state_lock:
                self._recording_started_at = None
                self._recording_epoch += 1
            self._recording_baseline = None

            job_id: Optional[str] = None
            if auto_download:
                job_id = self.captures.enqueue_post_capture_sync(
                    self.client,
                    self.info,
                    baseline or set(),
                )

            self._best_effort_restart_preview()
            return {
                "ok": True,
                "recording": False,
                "download_queued": bool(auto_download),
                "job_id": job_id,
            }

    def capture_photo(
        self,
        force: bool = False,
        auto_switch: bool = False,
        auto_download: bool = True,
    ) -> dict[str, Any]:
        """Trigger a photo capture, optionally auto-switching to a Photo preset."""
        with self._cmd_lock:
            status = self.client.get_status()
            switched_preset: Optional[int] = None

            if status.current_mode.lower() != "photo":
                if auto_switch:
                    raw_presets = self.client.get_presets() or {}
                    pid = find_photo_preset_id(raw_presets)
                    if pid is None:
                        raise CommandError(
                            "No Photo preset available on camera to switch into."
                        )
                    self.client.load_preset(pid)
                    switched_preset = pid
                elif not force:
                    raise CommandError(
                        f"Camera is in {status.current_mode} mode. "
                        "Switch to a Photo preset, or pass auto_switch=true or force=true."
                    )

            succeeded = False
            try:
                baseline = self._best_effort_snapshot_baseline() if auto_download else set()
                self.client.shutter_start()
                job_id = (
                    self.captures.enqueue_post_capture_sync(
                        self.client,
                        self.info,
                        baseline,
                    )
                    if auto_download
                    else None
                )
                succeeded = True
            finally:
                if succeeded or switched_preset is not None:
                    self._best_effort_restart_preview()
            return {
                "ok": True,
                "captured": True,
                "switched_preset": switched_preset,
                "download_queued": bool(auto_download),
                "job_id": job_id,
            }

    def take_snapshot(self) -> dict[str, Any]:
        """Save the latest decoded live preview frame as a JPEG in Downloads."""
        frame = self.transcoder.get_latest_frame()
        if not frame:
            raise CommandError("No live video frame available yet.")
        record = self.captures.save_frame_snapshot(frame)
        return {"ok": True, "capture": record.model_dump()}

    def load_preset(self, preset_id: int) -> dict[str, Any]:
        """Activate a specific camera preset by integer ID."""
        if isinstance(preset_id, bool) or not isinstance(preset_id, int):
            raise CommandError(f"preset_id must be an integer, got {preset_id!r}")
        with self._cmd_lock:
            self.client.load_preset(preset_id)
            self._best_effort_restart_preview()
            return {"ok": True, "preset_id": preset_id}

    def set_setting(self, setting: str | int, value: int) -> dict[str, Any]:
        """Resolve setting alias/ID and update the camera setting."""
        setting_id = resolve_setting_id(setting)
        if isinstance(value, bool) or not isinstance(value, int):
            raise CommandError(f"Setting value must be an integer, got {value!r}")
        with self._cmd_lock:
            self.client.set_setting(setting_id, value)
            settings_map: dict[Any, Any] = {}
            try:
                raw_state = self.client.get_raw_state() or {}
                raw_settings = raw_state.get("settings")
                if isinstance(raw_settings, dict):
                    settings_map = dict(raw_settings)
            except Exception as exc:
                logger.debug("Could not refresh settings after set_setting: %s", exc)
            settings_map.pop(setting_id, None)
            settings_map[str(setting_id)] = value
            return {
                "ok": True,
                "setting_id": setting_id,
                "value": value,
                "capabilities": self.get_capabilities(raw_settings=settings_map),
            }

    def pull_latest_media(self, filename: Optional[str] = None) -> dict[str, Any]:
        """Download a named SD card file or the newest primary photo/video item."""
        items = self.client.get_media_list()
        if filename is not None:
            target_name = filename.strip() if isinstance(filename, str) else ""
            if not target_name:
                raise MediaError("Filename cannot be empty.")
            target = next(
                (item for item in items if item.filename.lower() == target_name.lower()),
                None,
            )
            if target is None:
                raise MediaError(
                    f"Media file '{target_name}' not found on camera SD card."
                )
        else:
            primary = [item for item in items if item.media_type in PRIMARY_MEDIA_TYPES]
            if not primary:
                raise MediaError("No photo or video media found on camera SD card.")
            target = max(
                primary,
                key=lambda item: (item.mod_time or 0, item.directory, item.filename),
            )

        record = self.captures.download_camera_item(self.info, target)
        return {"ok": True, "capture": record.model_dump()}

    def start_preview(self) -> dict[str, Any]:
        """Enable the camera preview stream and start the MJPEG transcoder."""
        with self._cmd_lock:
            if self._stopped:
                raise CommandError("Controller has been stopped.")
            try:
                self.client.enable_wired_usb(True)
            except Exception as exc:
                logger.warning("Could not enable wired USB control: %s", exc)
            try:
                self._ensure_camera_preview_started()
            except Exception as exc:
                logger.warning("Preview stream start returned: %s", exc)
            self.transcoder.start()
            self._stream_enabled = True
            return {"ok": True, **self.transcoder.status()}

    def stop_preview(self) -> dict[str, Any]:
        """Stop the MJPEG transcoder and camera preview stream."""
        with self._cmd_lock:
            self._stream_enabled = False
            self.transcoder.stop()
            try:
                self.client.stop_preview_stream()
            except Exception as exc:
                logger.warning("Preview stream stop returned: %s", exc)
            return {"ok": True, **self.transcoder.status()}


class _LiveThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        RequestHandlerClass: type[BaseHTTPRequestHandler],
        live_server: LiveFeedServer,
    ) -> None:
        if ":" in server_address[0]:
            self.address_family = socket.AF_INET6
        self.live_server = live_server
        super().__init__(server_address, RequestHandlerClass)


class _LiveRequestHandler(BaseHTTPRequestHandler):
    server: _LiveThreadingHTTPServer  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("%s - %s", self.address_string(), format % args)

    def _emit_cors_headers(self, path: str) -> None:
        cors_origin = self.server.live_server.cors_origin
        if cors_origin is not None and path.startswith("/api/"):
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        path: str = "",
        extra_headers: Optional[dict[str, str]] = None,
    ) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self._emit_cors_headers(path)
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            if body:
                self.wfile.write(body)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        path: str = "",
    ) -> None:
        encoded = json.dumps(payload, default=str).encode("utf-8")
        self._send_bytes(
            status,
            encoded,
            "application/json; charset=utf-8",
            path=path,
        )

    def _read_json_body(self) -> dict[str, Any]:
        transfer_encoding = self.headers.get("Transfer-Encoding", "").strip()
        raw_len = self.headers.get("Content-Length")
        if transfer_encoding and (raw_len is None or not raw_len.strip()):
            raise CommandError("Transfer-Encoding without Content-Length is not supported.")
        if "chunked" in transfer_encoding.lower():
            raise CommandError("Chunked request bodies are not supported.")

        if raw_len is None or not raw_len.strip():
            return {}

        try:
            length = int(raw_len)
        except ValueError as exc:
            raise CommandError("Invalid Content-Length header.") from exc

        if length < 0:
            raise CommandError("Invalid Content-Length header.")
        if length > MAX_JSON_BODY_BYTES:
            raise CommandError(
                f"Request body exceeds maximum size of {MAX_JSON_BODY_BYTES} bytes."
            )
        if length == 0:
            return {}

        raw_bytes = self.rfile.read(length)
        if len(raw_bytes) < length:
            raise ValueError("Incomplete request body.")
        if len(raw_bytes) > MAX_JSON_BODY_BYTES:
            raise CommandError(
                f"Request body exceeds maximum size of {MAX_JSON_BODY_BYTES} bytes."
            )
        if not raw_bytes.strip():
            return {}

        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CommandError(f"Malformed JSON request body: {exc}") from exc

        if not isinstance(parsed, dict):
            raise CommandError("JSON request body must be a JSON object.")
        return parsed

    def _handle_exception(self, exc: Exception, path: str) -> None:
        if isinstance(exc, (CommandError, ValueError)):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"ok": False, "error": str(exc)},
                path=path,
            )
        elif isinstance(exc, (TransportError, CameraNotFoundError)):
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"ok": False, "error": str(exc)},
                path=path,
            )
        elif isinstance(exc, MediaError):
            is_io_failure = isinstance(exc.__cause__, OSError) or "failed to " in str(exc).lower()
            code = HTTPStatus.INTERNAL_SERVER_ERROR if is_io_failure else HTTPStatus.BAD_REQUEST
            self._send_json(code, {"ok": False, "error": str(exc)}, path=path)
        else:
            logger.exception("Unhandled error in LiveFeedServer for %s", path)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": str(exc)},
                path=path,
            )

    def _stream_mjpeg(self) -> None:
        live_server = self.server.live_server
        self.close_connection = True
        try:
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame",
            )
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            for frame in live_server.controller.transcoder.iter_frames(
                stop_event=live_server._stop_event
            ):
                if live_server._stop_event.is_set():
                    break
                header = (
                    "--frame\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode("ascii")
                self.wfile.write(header)
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def do_OPTIONS(self) -> None:
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"}, path=path)
            return

        try:
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self._emit_cors_headers(path)
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        live_server = self.server.live_server
        controller = live_server.controller

        if path == "/":
            self._send_bytes(
                HTTPStatus.OK,
                render_live_page(embed=False).encode("utf-8"),
                "text/html; charset=utf-8",
                path=path,
            )
            return
        if path == "/embed":
            self._send_bytes(
                HTTPStatus.OK,
                render_live_page(embed=True).encode("utf-8"),
                "text/html; charset=utf-8",
                path=path,
            )
            return
        if path == "/widget.js":
            self._send_bytes(
                HTTPStatus.OK,
                render_widget_js().encode("utf-8"),
                "application/javascript; charset=utf-8",
                path=path,
            )
            return
        if path == "/stream.mjpeg":
            self._stream_mjpeg()
            return

        try:
            if path == "/api/status":
                self._send_json(HTTPStatus.OK, controller.get_state(), path=path)
            elif path == "/api/presets":
                self._send_json(HTTPStatus.OK, controller.get_presets(), path=path)
            elif path == "/api/settings":
                self._send_json(HTTPStatus.OK, controller.get_settings(), path=path)
            elif path == "/api/capabilities":
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, **controller.get_capabilities()},
                    path=path,
                )
            elif path == "/api/captures":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "downloads_dir": str(controller.captures.downloads_dir),
                        "transfers": controller.captures.list_transfers(),
                        "captures": controller.captures.list_captures(),
                    },
                    path=path,
                )
            elif path == "/api/media":
                self._send_json(HTTPStatus.OK, controller.get_media_list(), path=path)
            else:
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": "Not found"},
                    path=path,
                )
        except Exception as exc:
            self._handle_exception(exc, path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        controller = self.server.live_server.controller

        post_routes = {
            "/api/shutter/start",
            "/api/shutter/stop",
            "/api/photo",
            "/api/snapshot",
            "/api/preset/load",
            "/api/setting",
            "/api/preview/start",
            "/api/preview/stop",
            "/api/media/pull",
        }
        if path not in post_routes:
            self._send_json(
                HTTPStatus.NOT_FOUND,
                {"ok": False, "error": "Not found"},
                path=path,
            )
            return

        try:
            body = self._read_json_body()
            if path == "/api/shutter/start":
                result = controller.start_recording()
            elif path == "/api/shutter/stop":
                auto_download = _require_bool(body, "auto_download", True)
                result = controller.stop_recording(auto_download=auto_download)
            elif path == "/api/photo":
                force = _require_bool(body, "force", False)
                auto_switch = _require_bool(body, "auto_switch", False)
                auto_download = _require_bool(body, "auto_download", True)
                result = controller.capture_photo(
                    force=force,
                    auto_switch=auto_switch,
                    auto_download=auto_download,
                )
            elif path == "/api/snapshot":
                result = controller.take_snapshot()
            elif path == "/api/preset/load":
                if "preset_id" not in body:
                    raise CommandError("Missing required field 'preset_id'.")
                result = controller.load_preset(body["preset_id"])
            elif path == "/api/setting":
                if "setting" not in body:
                    raise CommandError("Missing required field 'setting'.")
                if "value" not in body:
                    raise CommandError("Missing required field 'value'.")
                setting = body["setting"]
                if isinstance(setting, bool) or not isinstance(setting, (str, int)):
                    raise CommandError("Field 'setting' must be a string or integer.")
                result = controller.set_setting(setting, body["value"])
            elif path == "/api/preview/start":
                result = controller.start_preview()
            elif path == "/api/preview/stop":
                result = controller.stop_preview()
            elif path == "/api/media/pull":
                filename = body.get("filename")
                if filename is not None and (
                    not isinstance(filename, str) or not filename.strip()
                ):
                    raise CommandError("Field 'filename' must be a non-empty string.")
                result = controller.pull_latest_media(filename=filename)
            else:  # pragma: no cover - guarded by post_routes check
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"ok": False, "error": "Not found"},
                    path=path,
                )
                return

            self._send_json(HTTPStatus.OK, result, path=path)
        except Exception as exc:
            self._handle_exception(exc, path)


class LiveFeedServer:
    """Local HTTP server exposing the live GoPro control UI, MJPEG stream, and REST API."""

    def __init__(
        self,
        controller: LiveCameraController,
        host: str = "127.0.0.1",
        port: int = 8765,
        cors_origin: Optional[str] = None,
        start_stream: bool = True,
    ) -> None:
        if cors_origin is not None:
            if (
                not isinstance(cors_origin, str)
                or not cors_origin.strip()
                or any(ch in cors_origin for ch in ("\r", "\n", "\x00"))
            ):
                raise ValueError("Invalid cors_origin")
            cors_origin = cors_origin.strip()

        self.controller = controller
        self.cors_origin = cors_origin
        self.start_stream = start_stream
        self._stop_event = threading.Event()
        self._serve_entered = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._serve_thread: Optional[threading.Thread] = None
        self._serving = False
        self._controller_started = False
        self._closed = False
        self._httpd = _LiveThreadingHTTPServer(
            (host, port),
            _LiveRequestHandler,
            live_server=self,
        )
        self._host = str(self._httpd.server_address[0])

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def _base_url(self) -> str:
        display_host = (
            f"[{self.host}]"
            if ":" in self.host and not self.host.startswith("[")
            else self.host
        )
        return f"http://{display_host}:{self.port}"

    @property
    def url(self) -> str:
        return self._base_url()

    @property
    def embed_url(self) -> str:
        return f"{self._base_url()}/embed"

    @property
    def widget_url(self) -> str:
        return f"{self._base_url()}/widget.js"

    @property
    def stream_url(self) -> str:
        return f"{self._base_url()}/stream.mjpeg"

    def _ensure_controller_started(self) -> None:
        if not self._controller_started:
            self.controller.start(start_stream=self.start_stream)
            self._controller_started = True

    def _cleanup_failed_start(self) -> None:
        self._stop_event.set()
        self._closed = True
        try:
            self.controller.stop()
        except Exception as exc:
            logger.debug("Ignoring controller.stop() error after failed start: %s", exc)
        self._httpd.server_close()

    def start_in_thread(self) -> threading.Thread:
        """Start the controller and run the HTTP server on a background daemon thread."""
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("LiveFeedServer has already been shut down.")
            if self._serve_thread is not None and self._serve_thread.is_alive():
                return self._serve_thread
            if self._serving:
                raise RuntimeError("LiveFeedServer is already running.")
            try:
                self._ensure_controller_started()
            except Exception:
                self._cleanup_failed_start()
                raise

            self._stop_event.clear()
            self._serve_entered.clear()

            def _serve_target() -> None:
                with self._lifecycle_lock:
                    if self._stop_event.is_set() or self._closed:
                        self._serve_entered.set()
                        return
                    self._serving = True
                self._serve_entered.set()
                try:
                    self._httpd.serve_forever()
                finally:
                    with self._lifecycle_lock:
                        self._serving = False

            thread = threading.Thread(
                target=_serve_target,
                name="uel-live-http",
                daemon=True,
            )
            self._serve_thread = thread
            thread.start()

        self._serve_entered.wait(timeout=2.0)
        return thread

    def serve_forever(self) -> None:
        """Start the controller and serve HTTP requests on the calling thread until stopped."""
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("LiveFeedServer has already been shut down.")
            if self._serving or (
                self._serve_thread is not None and self._serve_thread.is_alive()
            ):
                raise RuntimeError("LiveFeedServer is already running.")
            try:
                self._ensure_controller_started()
            except Exception:
                self._cleanup_failed_start()
                raise
            self._stop_event.clear()
            self._serving = True

        try:
            self._httpd.serve_forever()
        finally:
            with self._lifecycle_lock:
                self._serving = False
            self.shutdown()

    def shutdown(self) -> None:
        """Idempotently stop streaming, controller workers, and the HTTP server."""
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            self._stop_event.set()
            was_serving = self._serving
            serve_thread = self._serve_thread

        # Stop controller (and transcoder) first so active /stream.mjpeg handlers exit promptly.
        self.controller.stop()

        if was_serving:
            self._httpd.shutdown()

        if (
            serve_thread is not None
            and serve_thread.is_alive()
            and serve_thread is not threading.current_thread()
        ):
            serve_thread.join(timeout=2.0)

        self._httpd.server_close()

    def __enter__(self) -> LiveFeedServer:
        self.start_in_thread()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.shutdown()
