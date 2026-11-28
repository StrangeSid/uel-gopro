---
name: uel-gopro
description: >-
  Non-obvious transport, firmware, streaming, media, telemetry, and development
  constraints for using or extending uel-gopro with OpenGoPro cameras (HERO9+).
---

# uel-gopro Agent Notes

Assume `--help` covers flags and subcommands. Only non-obvious runtime, hardware, and integration facts are listed here.

## Transports & Hardware Gotchas

- **Resolution order**: `--ip` -> USB CDC-ECM (`172.2X.1XX.51:8080`, camera USB mode must be `GoPro Connect`, not `MTP`) -> Wi-Fi AP (`10.5.5.9:8080`). No COHN/mDNS; `--ip` is plain HTTP.
- **MTP fallback (macOS only)**: Used only when HTTP discovery fails for `media list` and `media download`. No camera control/config/stream over MTP, and MTP downloads do not resume.
- **BLE (`--ble`)**: Explicit only. Cameras pause BLE advertising while tethered over USB-C, and CLI always picks the first discovered device. `config` and `status` over BLE parse `SETTINGS_RSP`/`QUERY_RSP` (`0x12`/`0x13`/`0x32`), while BLE shutter writes do not await `COMMAND_RSP` acks.
- **Wi-Fi AP timeouts & USB routing**: Camera AP has no internet and drops idle HTTP leases after ~30 s without `/gopro/camera/keep_alive` (`stream live` keeps it alive automatically). USB CDC-ECM DHCP can hijack the host default route on macOS/Linux; route `172.20.0.0/14` specifically if host internet drops.
- **HERO9–11 vs HERO12+**: `/gopro/camera/info` returns 404 on HERO9–11 (`uel-gopro` falls back to `/gp/gpControl/info`). `/gopro/camera/capabilities` is 404 on HERO10 (`config capabilities --ble` queries live opcode `0x32`; HTTP/matrix mode infers valid options from model + anti-flicker + resolution + FPS).

## Settings & Capture Semantics

- **Setting values are enums, not physical units**: e.g., `resolution=1` (4K 16:9), `fps=6` (50 fps), `fov=3` (SuperView), `anti_flicker=3` (50 Hz PAL). Run `uel-gopro config capabilities [--json]` before `config set` — FPS depends on resolution + 50/60 Hz anti-flicker, Lens depends on resolution + FPS, and HERO9/10 omit `bitrate` (`182`).
- **Photo shutter guard**: `record photo` fails outside a Photo preset unless `--force` is passed (over BLE, mode cannot be pre-checked). Over HTTP `stream live`, `POST /api/photo` accepts `{"auto_switch": true, "auto_download": true}`.
- **No SD format**: OpenGoPro HTTP API exposes no SD-card format endpoint.

## Live Feed Server (`stream live`)

- **Headless / agent invocation**: `--open` is on by default and calls `webbrowser.open` (non-fatal warning on headless hosts). Always pass `--no-open` in automated/agent sessions.
- **Single UDP consumer**: Only one FFmpeg process can bind `udp://@0.0.0.0:8554`; `stream live` fans out JPEG frames to unlimited `/stream.mjpeg` HTTP clients (`TCP_NODELAY`, zero FFmpeg filter buffering at default `fps=30`).
- **409 stream-start recovery**: HERO10 returns HTTP `409` on `/gopro/camera/stream/start` if a preview stream was left running; `LiveCameraController` auto-stops and retries once.
- **Self-contained UI & integration surfaces** (zero external CDN URLs — works offline on camera Wi-Fi AP):
  - `GET /` (full monitor), `GET /embed` (iframe/OBS HUD), `GET /widget.js` (`<uel-gopro-live server="..." controls="compact|full" auto-download="true|false">`, dispatches `uel-status`, `uel-capture`, `uel-error` `CustomEvent`s).
  - `GET /stream.mjpeg`, `/api/status`, `/api/capabilities`, `/api/presets`, `/api/settings`, `/api/captures`, `/api/media`.
  - `POST /api/shutter/start`, `/api/shutter/stop`, `/api/photo`, `/api/snapshot`, `/api/preset/load`, `/api/setting`, `/api/preview/start`, `/api/preview/stop`, `/api/media/pull`.
- **Downloads behavior**: Auto-download on recording stop and photo capture, frame snapshots, and `media/pull` save into `~/Downloads` (or `--downloads-dir`) using `_1`/`_2` collision suffixes — existing files are never overwritten.

## Media, Stitching, Telemetry & Cloud

- **4 GB+ file sizes**: `/gopro/media/list` overflows 32-bit `s` on `>= 4 GB` files; `media download` ignores `s` and queries `HEAD` (1-byte `Range` fallback) with `.partial` resume.
- **`--dest` path heuristic**: Non-existent `--dest` without a file suffix is created as a directory; existing files or paths with a suffix are treated as the target filename.
- **Chapter stitch**: `process stitch --output` fails if inputs span multiple base IDs (omit `--output` to emit `STITCH_<base>.mp4` per group). Capture-time sync warns and skips if the MP4 `mvhd` atom has time `0`.
- **Telemetry & Cloud limits**: `telemetry export` extracts GPS5/GPS9 only (`GPSP` precision time and `ACCL`/`GYRO` IMU samples are not exported). `cloud` uses an undocumented GoPro endpoint with a manual bearer token in `~/.config/uel-gopro/cloud.json` (`0600`), with no OAuth flow.

## Repo Development

- `tests/test_live_server.py` binds real `127.0.0.1:0` sockets and requires loopback network access if executed inside a restricted sandbox.
- `uv run ruff check src tests` and `uv run pytest -q` are the required CI gates (`pyproject.toml` ignores `PLAN.md` via `.gitignore`; keep `PLAN.md` uncommitted).
