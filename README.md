# UEL-GoPro

> **Unofficial Extended Life GoPro Toolchain**
> A local-first, scriptable CLI toolchain.

---

## Overview

GoPro's software ecosystem has steadily degraded for desktop and technical users:
- Desktop tooling was abandoned in favor of ad-heavy mobile applications.
- Bulk media downloads and multi-device workflows are gated behind subscription paywalls.
- Embedded telemetry (GPS and IMU sensor data) is locked inside binary formats, while webcam utilities frequently break with firmware updates.

**UEL-GoPro** provides a unified command-line toolchain for all GoPro operations: wired USB-C control, chapter-aware media ingest, lossless stream stitching, native GPMF telemetry extraction, optical QR automation, and live streaming.

---

## Key Features

- **USB CDC-ECM Auto-Detection:** Automatically discovers cameras at `172.2X.1XX.51:8080` without manual IP configuration.
- **32-Bit Firmware Bug Mitigation:** Bypasses GoPro firmware's `/gopro/media/list` 4 GB integer overflow bug by querying authoritative 64-bit HTTP `HEAD` `Content-Length`.
- **Resumable Downloader:** Parallel chunked downloads using `.partial` files, HTTP `Range` requests, and byte integrity validation.
- **Lossless Chapter Stitcher:** Concatenates split video chapters (`GX010042.MP4`, `GX020042.MP4`) via FFmpeg concat demuxer without re-encoding, preserving multi-channel audio, timecode, and `gpmd` telemetry tracks.
- **Native GPMF Telemetry Parser:** Decodes binary KLV metadata (GPS5, accelerometer, gyroscope) and exports to GPX, KML, GeoJSON, and CSV.
- **In-Terminal QR Generator:** Generates high-contrast Unicode half-block QR codes directly inside the terminal window for instant optical configuration via GoPro Labs firmware.
- **Live Streaming & Webcam:** Zero-latency preview streaming directly to `mpv` or `ffplay`, plus native 1080p/720p USB webcam mode.

---

## Requirements & Prerequisites

- **Python:** 3.11 or newer (Python 3.13 recommended)
- **uv:** Modern, fast Python package manager ([installation instructions](https://docs.astral.sh/uv/))
- **FFmpeg:** Required for chapter concatenation and GPMF telemetry extraction

---

## Installation

### Using `uv` (Recommended)

```bash
git clone https://github.com/StrangeSid/uel-gopro.git
cd uel-gopro
uv sync
```

### Standalone Executable (Zero Dependencies)

Build a self-contained executable that runs without Python:

```bash
uv run pyinstaller --onefile --name uel-gopro --clean src/uel_gopro/cli/main.py
./dist/uel-gopro --help
```

---

## CLI Command Reference

### Discovery & Status

```bash
# Auto-detect connected cameras over USB (GoPro Connect or MTP mode) and BLE
uel-gopro discover

# Scan for Bluetooth Low Energy (BLE) GoPro cameras
uel-gopro discover --ble

# Display real-time status dashboard (battery, storage, thermals, recording mode)
uel-gopro status

# Query real-time status wirelessly over Bluetooth Low Energy
uel-gopro status --ble

# Output status dashboard as structured JSON
uel-gopro status --json
```

> [!TIP]
> UEL-GoPro supports two USB connection modes:
> - **GoPro Connect (CDC-ECM):** Full camera control, shutter, webcam, live streaming, settings, and high-speed downloads (40 MB/s).
> - **MTP Mode:** File listing and media downloading without changing camera settings. Control commands fallback or prompt to switch to GoPro Connect.

### Recording & Shutter

```bash
# Start video recording or timelapse
uel-gopro record start

# Stop recording
uel-gopro record stop

# Capture a still photograph
uel-gopro record photo
```

### Camera Settings & Presets

```bash
# List available camera presets
uel-gopro preset list

# Activate a preset by ID
uel-gopro preset load 1000

# Inspect camera settings
uel-gopro config list
uel-gopro config get 2

# Update a camera setting (e.g., setting ID 2 to value 1)
uel-gopro config set 2 1
```

### Media Ingest & SD Card Management

```bash
# List media stored on the camera SD card
uel-gopro media list

# Download a video with progress tracking and size validation
uel-gopro media download GX010042.MP4 --dest ~/Videos/GoPro

# Delete a specific file from the SD card
uel-gopro media delete GX010042.MP4 --force
```

> [!WARNING]
> Formatting an SD card irreversibly erases all footage. UEL-GoPro requires explicit confirmation:
> ```bash
> uel-gopro media format --confirm
> ```

### Chapter Stitching & Post-Processing

GoPro splits long recordings into multiple chapter files. UEL-GoPro stitches them into a single contiguous file without re-encoding:

```bash
# Losslessly stitch chapters in a directory
uel-gopro process stitch /path/to/chapters/ --output stitched.mp4

# Synchronize file modification dates with true capture timestamps
uel-gopro process sync-dates GX010042.MP4
```

> [!TIP]
> Stitching uses stream copy mode (`-c copy -map 0`), preserving all embedded GPS and telemetry tracks for post-processing.

### GPMF Sensor Telemetry Extraction

Extract embedded sensor telemetry from GoPro MP4 files into standard geospatial formats:

```bash
# Export GPS track to GPX (for Strava, Garmin, or GIS tools)
uel-gopro telemetry export GX010042.MP4 --format gpx --output track.gpx

# Export to KML (Google Earth)
uel-gopro telemetry export GX010042.MP4 --format kml --output track.kml

# Export to GeoJSON
uel-gopro telemetry export GX010042.MP4 --format geojson --output track.geojson

# Export to tabular CSV
uel-gopro telemetry export GX010042.MP4 --format csv --output track.csv
```

### GoPro Labs QR Automation

Render optical macro programming codes directly on your screen without leaving the terminal:

```bash
# List available macro presets
uel-gopro labs presets

# Render a high-contrast half-block QR code in the terminal
uel-gopro labs qr bitrate_max
uel-gopro labs qr motion_detect
uel-gopro labs qr speed_trigger_50kmh

# Generate a custom Labs macro and save as PNG/SVG
uel-gopro labs qr "!M1*BITR=180" --save macro.png
```

### Live Preview & USB Webcam

```bash
# Launch zero-latency preview stream in mpv or ffplay
uel-gopro stream preview --player mpv

# Start 1080p USB webcam mode
uel-gopro stream webcam start --res 1080p

# Stop USB webcam mode
uel-gopro stream webcam stop
```

### GoPro Plus Cloud Sync (NAS Backup)

Bypass the official web interface's 25-file bulk download ceiling and mirror your complete GoPro Plus cloud library:

```bash
# Store your GoPro Plus authentication token
uel-gopro cloud auth --token <YOUR_BEARER_TOKEN>

# Browse cloud media assets with pagination
uel-gopro cloud list --page 1 --per-page 25

# Headless mirror of cloud assets to local storage or NAS
uel-gopro cloud sync --dest /mnt/nas/GoProCloudBackup --max-pages 100
```

> [!NOTE]
> Cloud sync uses atomic `.partial` staging buffers and checks file sizes, skipping assets that are already safely archived.

---

## Disclaimer

GoPro, HERO, and MAX are registered trademarks of GoPro, Inc. UEL-GoPro is an independent, community-driven open-source project and is not affiliated with, sponsored by, or endorsed by GoPro, Inc.
