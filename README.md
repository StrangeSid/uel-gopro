# UEL-GoPro

> **Unofficial Extended Life GoPro Toolchain**
> A local-first, scriptable CLI for OpenGoPro-compatible cameras.

---

## What this is

UEL-GoPro is a command-line toolchain for GoPro cameras. It talks to the
camera directly over USB CDC-ECM or the camera's Wi-Fi access point, and adds
local post-processing for chapter stitching, timestamps, GPMF GPS telemetry,
and GoPro Labs QR codes.

It is **alpha software**. The OpenGoPro HTTP API is the primary interface. Some
endpoints only exist on newer cameras, and Bluetooth and USB-MTP support are
narrower than the wired and Wi-Fi path.

Current version: **0.1.1** (source). The latest PyPI release is **0.1.0** and
doesn't contain the fixes in this tree. See [Installation](#installation).

---

## Features

- Commands resolve a camera through manual IP, USB CDC-ECM
  (`172.2X.1XX.51:8080`), or the camera Wi-Fi AP (`10.5.5.9:8080`). `discover`
  scans USB, the macOS MTP fallback, and optionally BLE.
- A status dashboard built from OpenGoPro status IDs: battery percentage and
  bars, charging, recording, SD state and free space, preset group, remaining
  photos and video time, and an overheat warning.
- Recording control for shutter start and stop, plus photo capture when the
  camera is already in a Photo preset.
- The CLI lists, reads, and writes settings, and lists and loads presets.
- The media commands list files. HTTP downloads resume with `.partial` files
  and HTTP Range, use `HEAD` for the authoritative size with a ranged-GET
  fallback, and verify the byte count. The macOS MTP fallback does not resume.
- Chapter stitching uses the FFmpeg concat demuxer with `-map 0 -c copy` and
  keeps video, audio, timecode, and `gpmd` telemetry tracks. `stitch` restores
  the first chapter's capture timestamp when the container exposes one.
- GPMF GPS extraction uses a native KLV parser for GPS5 or GPS9 streams and
  exports GPX, KML, GeoJSON (with `bbox`), and CSV. The parser detects IMU
  streams but does not export them yet.
- GoPro Labs QR support renders codes in the terminal with half blocks,
  exports PNG and SVG, and includes a small preset library.
- Preview and webcam commands start the camera's preview stream and can launch
  `mpv` or `ffplay`, or start USB webcam mode at 480p/720p/1080p with a chosen
  field of view.
- GoPro Plus cloud mirroring provides paginated listing and resumable
  downloads with a user-supplied bearer token. It uses an undocumented GoPro
  API.

---

## Requirements

- Python 3.11 or newer (3.13 recommended)
- uv for the recommended install path ([install uv](https://docs.astral.sh/uv/))
- FFmpeg for chapter stitching and GPMF extraction
- mpv or ffplay for live preview (optional)
- A GoPro camera compatible with the OpenGoPro HTTP API. HERO9 and newer
  cameras cover the core API. `/gopro/camera/info` and some webcam controls
  need HERO12+.

---

## Installation

### Recommended: from source

```bash
git clone https://github.com/StrangeSid/uel-gopro.git
cd uel-gopro
uv sync
uv tool install .
# or run without installing:
uv run uel-gopro --help
```

This installs the current source tree (0.1.1). Use this path until a fixed
release is published.

### One-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/StrangeSid/uel-gopro/main/install.sh | bash
```

The installer uses `uv` when available and installs from the `main` branch
when `git` is available. If `uv` is unavailable, it creates an isolated virtual
environment under `~/.local/share/uel-gopro`. If `git` is unavailable, it
installs the last PyPI release.

### PyPI

```bash
uv tool install uel-gopro
# or
pip install uel-gopro
```

The current PyPI release is **0.1.0**. It predates the fixes in this tree.

### Homebrew (HEAD only)

There is no stable Homebrew tap or release yet. From a checkout:

```bash
brew install --HEAD ./Formula/uel-gopro.rb
```

This builds the current `main` branch. It depends on Homebrew's `python@3.13`
and `ffmpeg`.

### Standalone binary

PyInstaller can build a single-file executable locally, but the project
publishes no prebuilt binary:

```bash
uv run pyinstaller --onefile --name uel-gopro --paths src --clean src/uel_gopro/cli/main.py
./dist/uel-gopro --help
```

BLE backends and macOS MTP/PyObjC may require additional platform libraries
when frozen. Test the binary on the target machine.

### MTP on macOS

MTP media fallback uses ImageCaptureCore through PyObjC. `bleak` normally
pulls Cocoa in on macOS. The project also declares the dependency explicitly:

```bash
pip install "uel-gopro[mtp]"
```

MTP is only available on macOS and only for listing and downloading media.
Camera control commands still require USB CDC-ECM or Wi-Fi.

---

## Transport support

| Transport | Discovery | Control | Media | Notes |
|---|---|---|---|---|
| USB CDC-ECM | Automatic | Yes | Yes | Camera must be in GoPro Connect mode |
| Wi-Fi AP `10.5.5.9` | Automatic/manual | Yes | Yes | Uses the camera's own AP |
| Manual IP `--ip` | Explicit | Yes | Yes | Plain HTTP on port 8080 |
| USB MTP | Fallback | No | List/download | macOS only; media commands only |
| BLE | `--ble` | Shutter | No | First discovered camera; no ack handling; Wi-Fi AP helper is not exposed in the CLI |
| COHN (home network) | Not implemented | No | No | Not part of the current transport resolver |

There's no automatic COHN/mDNS discovery and no automatic MTP/BLE fallback
for control commands.

---

## Command reference

### Discovery and status

```bash
uel-gopro discover
uel-gopro discover --ble
uel-gopro status
uel-gopro status --json
uel-gopro status --ble
```

`status` uses the OpenGoPro status map. When `/gopro/camera/info` is available
(HERO12+), the dashboard also shows the real model, firmware, and serial
number. Older cameras keep the generic transport label.

### Recording

```bash
uel-gopro record start
uel-gopro record stop
uel-gopro record photo            # requires a Photo preset
uel-gopro record photo --force    # trigger regardless of current mode
```

`record photo` checks the current preset group and exits with an error outside
a Photo preset unless you pass `--force`. Over BLE it can't read the mode, so
without `--force` it warns and triggers the camera's current mode.

### Presets and settings

```bash
uel-gopro preset list
uel-gopro preset load 1000

uel-gopro config list
uel-gopro config get 2
uel-gopro config get resolution
uel-gopro config set resolution 4
```

The current setting aliases are `resolution` (2), `fps` (3), `fov` (121), and
`bitrate` (182). Older cameras may use different IDs, so pass a numeric ID.
Bitrate and FOV option values are camera-dependent enums, not Mbps or
millimetres.

### Media

```bash
uel-gopro media list
uel-gopro media download GX010042.MP4 --dest ~/Videos/GoPro
uel-gopro media delete GX010042.MP4 --force
```

`media download` treats `--dest` as a directory unless it already exists as a
file or has a file suffix. It downloads one file at a time, resumes partial
files, and checks the byte count against the camera's authoritative size.

SD-card formatting is not supported. The OpenGoPro HTTP API doesn't expose a
format endpoint, so use the camera UI.

### Stitching and timestamps

```bash
uel-gopro process stitch /path/to/chapters/ --output stitched.mp4
uel-gopro process sync-dates GX010042.MP4
```

`stitch` uses FFmpeg stream copy (`-map 0 -c copy`). It writes to a temporary
file and only replaces the destination after FFmpeg succeeds. It restores the
first chapter's capture timestamp when the container exposes one. `--output`
is only valid for a single chapter group.

### GPS telemetry

```bash
uel-gopro telemetry export GX010042.MP4 --format gpx --output track.gpx
uel-gopro telemetry export GX010042.MP4 --format kml
uel-gopro telemetry export GX010042.MP4 --format geojson
uel-gopro telemetry export GX010042.MP4 --format csv
```

Only GPS points are exported. The parser selects the GPS5 or GPS9 sample
layout from the fourcc. GPSU timestamps are approximate because the parser
doesn't read `GPSP` precision time yet. The parser detects accelerometer and
gyroscope streams but does not decode them.

### GoPro Labs QR codes

```bash
uel-gopro labs presets
uel-gopro labs qr bitrate_max
uel-gopro labs qr "!M1" --save macro.png
uel-gopro labs qr "!M1" --invert
```

The terminal renderer uses two rows per character cell and a four-module quiet
zone. By default it uses standard polarity, with black modules on white.
`--invert` produces white modules on a black terminal background. Verify the
code scans on your camera before relying on it.

### Preview and webcam

```bash
uel-gopro stream preview
uel-gopro stream preview --player mpv
uel-gopro stream preview --no-player

uel-gopro stream webcam start --res 1080p --fov linear
uel-gopro stream webcam stop
```

Webcam codes follow the OpenGoPro API: 480p=4, 720p=7, 1080p=12. Field of
view: wide=0, narrow=2, superview=3, linear=4.

### GoPro Plus cloud

```bash
uel-gopro cloud auth --token <bearer-token>
uel-gopro cloud list --page 1 --per-page 25
uel-gopro cloud sync --dest /mnt/nas/GoProCloudBackup --max-pages 100
```

`cloud auth` stores the token in `~/.config/uel-gopro/cloud.json` with mode
`0600`. Cloud sync uses pagination, skips files whose size already matches,
keeps partial buffers on network failure, and avoids overwriting a different
asset that shares a filename. The API is undocumented and may change without
notice. There's no OAuth flow.

---

## Known limitations

- No COHN/mDNS support. Manual IP is plain HTTP only.
- MTP is macOS-only and limited to media listing and download.
- No SD-card format command.
- No parallel downloads. Downloads resume sequentially.
- BLE is minimal. The CLI exposes shutter control. The client has a Wi-Fi AP
  helper, but no command calls it. There is no response or ack parsing, pairing
  UI, or multi-camera selection.
- IMU telemetry isn't exported. Only GPS points are parsed into tracks.
- GPS timestamps are approximate because `GPSP` isn't parsed.
- Cloud support is unofficial and token-based.
- Windows isn't supported.
- No hardware-in-the-loop test suite. CI covers protocol construction,
  parsers, and filesystem behavior with mocks.

---

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check src tests
uv build
```

The test suite runs offline and uses mocked camera responses, synthetic MP4
boxes, synthetic GPMF KLV streams, and `httpx.MockTransport`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for details.

CI runs Python 3.11 to 3.13, Ruff, tests, and a distribution build. The
publish workflow runs tests, checks that the release tag matches
`pyproject.toml`, and uploads to PyPI.

---

## Disclaimer

GoPro, HERO, and MAX are registered trademarks of GoPro, Inc. UEL-GoPro is an
independent open-source project and isn't affiliated with,
sponsored by, or endorsed by GoPro, Inc. Use at your own risk.
