# UEL-GoPro (Unofficial Extended Life)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Tests: 63 Passing](https://img.shields.io/badge/tests-63%20passing-brightgreen.svg)]()

> **Unofficial Extended Life GoPro Toolchain**  
> An open-source, local-first CLI toolchain built to reclaim complete control of GoPro cameras. No mobile apps, no cloud paywalls, no proprietary software.

---

## 🎯 Philosophical Mission

GoPro's software ecosystem has steadily degraded for desktop users:
1. **Desktop Abandonment:** The official Quik desktop app was abandoned/crippled in favor of ad-heavy mobile applications.
2. **Cloud Paywalls:** Basic multi-device backup and bulk exports are gated behind GoPro Premium subscriptions, while the official web interface limits bulk downloads to 25 files.
3. **Firmware & Telemetry Siloing:** GPS and IMU data are locked inside proprietary formats, and webcam utilities regularly break with firmware releases.

**UEL-GoPro** provides a unified, scriptable, cross-platform terminal interface for all GoPro camera operations: wired USB-C control, high-speed chapter-aware media ingest, lossless stream stitching, sensor telemetry extraction, terminal-based QR macro programming, and live streaming.

---

## ⚡ Features

* 🔌 **Wired USB-C CDC-ECM Auto-Detection:** Automatically locates GoPro camera at `172.2X.1XX.51:8080` without manual IP configuration.
* 🛡️ **32-Bit Integer Overflow Workaround:** Bypasses GoPro firmware's `/gopro/media/list` 4GB file size truncation bug by querying authoritative HTTP `HEAD` `Content-Length`.
* ⚡ **Resumable Parallel Downloader:** Staged downloads using `.partial` files, HTTP `Range` chunking, and size verification.
* 🧵 **Lossless Chapter Stitcher:** Concat split 4GB chapters (`GX010042.MP4`, `GX020042.MP4`) into a single file via FFmpeg without re-encoding, preserving multi-channel audio and `gpmd` telemetry tracks.
* 🧭 **Native GPMF Telemetry Parser:** Decodes embedded binary sensor streams (GPS5, accelerometer, gyroscope) and exports to **GPX**, **KML**, **GeoJSON**, and **CSV**.
* 🏁 **GoPro Labs QR Code Generator:** Renders high-contrast Unicode half-block QR codes directly inside the terminal window for instant optical camera programming (max bitrate, motion triggers, scheduled wake).
* 🎥 **Live Streaming & Webcam:** Launch zero-latency preview streams directly in `mpv` or `ffplay`, and start/stop 1080p/720p USB webcam mode.

---

## 📦 Installation

Requirements:
* Python 3.11+
* [FFmpeg](https://ffmpeg.org/) (for chapter stitching and telemetry extraction from MP4)

Using `uv` (recommended):
```bash
git clone https://github.com/your-username/uel-gopro.git
cd uel-gopro
uv sync
```

Or install in editable mode:
```bash
pip install -e .
```

---

## 🚀 Quick Start & Command Reference

### 1. Camera Discovery & Status
```bash
# Auto-detect connected cameras over USB CDC-ECM network
uel-gopro discover

# Display status dashboard (battery, recording state, storage, thermals)
uel-gopro status

# Output status as machine-readable JSON
uel-gopro status --json
```

### 2. Shutter & Recording Controls
```bash
# Start video recording or timelapse
uel-gopro record start

# Stop recording
uel-gopro record stop

# Capture a photo
uel-gopro record photo
```

### 3. Presets & Settings
```bash
# List available camera presets
uel-gopro preset list

# Activate a preset by ID
uel-gopro preset load 1000

# Inspect camera settings
uel-gopro config get
uel-gopro config get resolution

# Modify a setting (e.g. resolution: 1=4K, 100=5.3K)
uel-gopro config set resolution 1
```

### 4. SD Card Media Management
```bash
# List media files on camera SD card
uel-gopro media list

# Download a video with resume and size verification
uel-gopro media download GX010042.MP4 --dest ~/Movies/GoPro

# Delete a file from camera
uel-gopro media delete GX010042.MP4 --force

# Format camera SD card (requires confirmation flag)
uel-gopro media format --confirm
```

### 5. Chapter Stitching & Post-Processing
```bash
# Losslessly stitch split chapters in a folder preserving GPS and audio
uel-gopro process stitch /path/to/chapters/ --output stitched.mp4

# Synchronize file modification dates with true capture timestamps
uel-gopro process sync-dates GX010042.MP4
```

### 6. GPMF Telemetry Extraction
```bash
# Export embedded GPS track to GPX (for Strava / Garmin)
uel-gopro telemetry export GX010042.MP4 --format gpx --output track.gpx

# Export to KML (Google Earth), GeoJSON (GIS), or CSV
uel-gopro telemetry export GX010042.MP4 --format kml --output track.kml
uel-gopro telemetry export GX010042.MP4 --format geojson --output track.geojson
uel-gopro telemetry export GX010042.MP4 --format csv --output track.csv
```

### 7. GoPro Labs In-Terminal QR Codes
```bash
# List built-in GoPro Labs macro presets
uel-gopro labs presets

# Render high-contrast QR code directly in the terminal
uel-gopro labs qr bitrate_max
uel-gopro labs qr motion_detect
uel-gopro labs qr speed_trigger_50kmh

# Custom Labs code and save to PNG/SVG
uel-gopro labs qr "!M1*BITR=180" --save macro.png
```

### 8. Live Preview & Webcam
```bash
# Launch zero-latency preview stream in mpv or ffplay
uel-gopro stream preview --player mpv

# Start 1080p USB webcam mode
uel-gopro stream webcam start --res 1080p

# Stop webcam
uel-gopro stream webcam stop
```

---

## 🛠️ Testing

Run the comprehensive test suite (63 unit tests):
```bash
uv run pytest
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
GoPro, HERO, and MAX are registered trademarks of GoPro, Inc. UEL-GoPro is an independent open-source project and is not affiliated with or endorsed by GoPro, Inc.
