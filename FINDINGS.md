# Deep Architectural Audit & Specification: GoPro Software Ecosystem & Unified CLI (`gopro-cli`)

**Target Project:** `gopro-cli`  
**Location:** `/Users/sid/Documents/proj/gopro-cli`  
**Date:** October 2026  
**Document Status:** Complete Architecture & Research Assessment  

---

## 1. Executive Summary & Problem Space

The action camera ecosystem for GoPro is severely fragmented. While GoPro hardware (HERO9 through HERO13, MAX) is capable of high-bandwidth wired control, BLE orchestration, local Wi-Fi station connectivity, telemetry extraction, and cloud synchronization, the software landscape consists of siloed, incompatible tools:

1. **Official SDKs (`gopro/OpenGoPro`)** provide reference protocol specifications and basic Python/Kotlin demos, but lack a unified, ergonomic command-line utility for power users and automation scripts.
2. **Legacy Reverse-Engineered Libraries (`KonradIT/gopro-py-api`)** support older cameras (HERO3–HERO8) through deprecated Wi-Fi GET queries, but lag on modern Protobuf-over-BLE and Wired USB-C interfaces.
3. **Local Ingestion Utilities (`fxstein/GoProX`, `omokage-code/GPTransfer`)** solve file chaptering and MTP transfer failures on macOS, but exist either as monolithic shell scripts or macOS-only GUI applications with zero camera control capabilities.
4. **Cloud Exporters (`itsankoff/gopro-plus`)** bypass web-portal file limits to scrape the GoPro Plus cloud subscription, but operate completely disconnected from local devices.
5. **Telemetry Tools (`gopro/gpmf-parser`, `JuanIrache/gopro-telemetry`)** extract binary GPMF sensor streams into GPX/CSV, but exist as detached C/JavaScript libraries.
6. **GoPro Labs Firmware (`gopro/labs`)** unlocks low-level camera behavior via QR code macros, but requires manual web-form generation.

### Goal of `gopro-cli`
`gopro-cli` will be an all-in-one, cross-platform terminal interface unifying **all non-GUI GoPro operations**: discovery, multi-transport connection (Wired USB, BLE, Wi-Fi AP, COHN Local LAN), real-time camera state control, high-speed chapter-aware media ingest, lossless stream stitching, telemetry extraction, terminal-based QR macro generation, and cloud backup.

---

## 2. Hardware Generations & Protocol Evolution

| Generation | Supported Transports | API Architecture | Notable Quirks & Constraints |
| :--- | :--- | :--- | :--- |
| **HERO3 / HERO3+** | Wi-Fi AP Only | BacPac HTTP GET (`/bacpac/...`) | Password-protected Wi-Fi. No BLE. |
| **HERO4 / HERO+** | Wi-Fi AP, Legacy BLE | Ambarella HTTP API (`/gp/gpControl/...`) | Early pairing handshake; basic status. |
| **HERO5 / HERO6 / HERO7** | Wi-Fi AP (5GHz/2.4GHz), BLE | Query string HTTP (`/gp/gpControl/command/...`) | First GPMF telemetry integration. GPS enabled. |
| **HERO8 Black / MAX** | Wi-Fi AP, BLE | Query string HTTP + BLE command characteristics | Firmware modified Wi-Fi keep-alive rules. |
| **HERO9 Black** | BLE, Wi-Fi AP, USB-C (FW >= v1.6) | OpenGoPro v1 Spec (Protobuf BLE, HTTP `/gopro/...`) | USB wired mode requires manual MTP/GoPro Connect toggle. |
| **HERO10 / HERO11 / 11 Mini** | BLE, Wi-Fi AP, USB-C Wired | OpenGoPro v2 Spec (Protobuf BLE, HTTP REST, CoAP) | High-speed CDC-ECM wired interface enabled by default. |
| **HERO12 Black** | BLE, Wi-Fi AP, Wi-Fi COHN (STA), USB-C | OpenGoPro v2 Spec + COHN (TLS/HTTPS over LAN) | **GPS hardware removed.** Bluetooth audio added. Native STA Wi-Fi. |
| **HERO13 Black** | BLE, Wi-Fi 6 AP, Wi-Fi COHN (STA), USB-C | OpenGoPro v2 Spec + Extended Protobuf | Lens Mod auto-detection, magnetic latch power, HB-series lenses. |

---

## 3. Deep Analysis of Transport Protocols

### 3.1. Bluetooth Low Energy (BLE)
* **Primary Service UUID:** `0000FEA6-0000-1000-8000-00805F9B34FB` (16-bit short form: `0xFEA6`).
* **Company Identifier:** `0xF202` (GoPro, Inc.).
* **Key Characteristics:**
  * **Command Request (`b5f70072-...`):** Write Without Response. Encapsulates control packets (shutter, presets, Wi-Fi AP power on).
  * **Command Response (`b5f70073-...`):** Notification characteristic emitting status/ack codes.
  * **Setting Request (`b5f70074-...`):** Modify camera settings (resolution, FPS, FOV).
  * **Setting Response (`b5f70075-...`):** Notification of setting updates.
  * **Query Request (`b5f70076-...`):** Register for real-time status/setting updates.
  * **Query Response (`b5f70077-...`):** Async notification of status flags (battery %, SD space, recording time).
* **Wire Format:**
  * Modern cameras (HERO9+) use **Google Protocol Buffers (Protobuf)** serialized into chunked BLE frames (Header byte containing continuation bit + packet length).
  * Commands smaller than MTU fit in a single packet; larger packets require standard GoPro packet framing headers (`0x00`-`0x1F` continuation markers).
* **Role in `gopro-cli`:**
  * Waking camera from deep sleep (Keep-Alive ping every 3–4 seconds).
  * Triggering Wi-Fi AP power-on without touching physical buttons.
  * Rapid wireless shutter trigger and mode switches with minimal power consumption.

### 3.2. Wi-Fi AP Mode (Access Point)
* **Topology:** Camera hosts a Wi-Fi Access Point (`GP<serial>` or custom SSID). Host computer disconnects from local internet to connect to camera Wi-Fi.
* **Camera Gateway IP:** Fixed at `10.5.5.9`.
* **API Port:** `8080` (HTTP).
* **Keep-Alive Requirement:** Must send periodic HTTP GET to `/gopro/camera/keep_alive` or BLE keep-alive every 30 seconds, or camera Wi-Fi radio shuts down to conserve battery.
* **Limitations:** Interrupts host internet connectivity; high thermal load on camera.

### 3.3. Wi-Fi COHN (Camera on the Home Network / Station Mode)
* **Introduced:** HERO12 Black, HERO13 Black, and recent firmware updates.
* **Topology:** Camera connects as a client (STA mode) to the user's home Wi-Fi network or mobile hotspot.
* **Provisioning Mechanism:**
  1. BLE connection established.
  2. Host scans local SSIDs or sends credentials (`SSID`, `password`) via Protobuf message over BLE.
  3. Camera generates a self-signed TLS Certificate and exports its Root CA / public cert over BLE to the host.
  4. Camera connects to LAN and obtains local IP address via DHCP (e.g., `192.168.1.145`).
  5. API commands execute over **HTTPS** on port `8080` or `443` using mutual TLS / Basic Auth credentials provided during handshake.
* **Significance for `gopro-cli`:**
  * Revolutionary for CLI workflows: host machine **retains internet access** while sending control commands and downloading media across the local network.

### 3.4. Wired USB-C Control (CDC-ECM / RNDIS / NCM)
* **Driver Standard:** Emulates a USB Ethernet adapter (CDC-ECM on macOS/Linux, RNDIS on Windows).
* **IP Scheme:** Camera hosts an internal DHCP server, issuing the host an IP on subnet `172.2X.1XX.0/24` (where `X` depends on serial number), with the camera resting at `.51` (e.g., `http://172.20.150.51:8080` or `http://172.24.162.51:8080`).
* **Throughput:** ~30 to 42 MB/s sustained transfer rate (USB 2.0 / USB 3.0 controller limits depending on model).
* **Power:** Camera charges continuously while connected.
* **Control:** Full OpenGoPro HTTP REST API accessible over the USB Ethernet IP without wireless latency or interference.

---

## 4. In-Depth Audit of Existing Open-Source Implementations

### 4.1. `gopro/OpenGoPro` (Official Reference)
* **Repository:** `https://github.com/gopro/OpenGoPro`
* **Language/Stack:** Python (Bleak, Requests, FastAPI for mocking), Kotlin (KMP), Swift.
* **Capabilities:**
  * Authoritative OpenAPI / Protobuf specs for HERO9 through HERO13.
  * BLE discovery, Wi-Fi AP bootstrapping, and COHN provisioning scripts.
  * Comprehensive endpoint mapping: Shutter, Presets, Settings, Status, Media list, Stream initiation.
* **Deficiencies & Blindspots:**
  * **Not a functional CLI utility:** Demos are isolated monolithic scripts (`cohn.py`, `wifi_stream.py`, `photo.py`).
  * No chapter concatenation or media assembly.
  * No telemetry extraction or format conversion.
  * Heavy dependency footprint (`bleak`, `protobuf`, `pydantic`, `rich`).
  * Zero backward compatibility with pre-HERO9 cameras.

### 4.2. `fxstein/GoProX`
* **Repository:** `https://github.com/fxstein/GoProX`
* **Language/Stack:** Shell (Bash/Zsh), Homebrew tap, `launchd` service agent.
* **Capabilities:**
  * Automated detection of mounted GoPro SD cards / volumes on macOS.
  * **Smart Chapter Joining:** Seamlessly stitches 4GB segmented chapters (`GX010001.MP4`, `GX020001.MP4`) into a single file without re-encoding using `ffmpeg` stream copying.
  * **Metadata & EXIF Preservation:** Corrects file modification and creation timestamps using GPMF metadata to prevent NLE timeline scrambling.
  * Checksum verification (SHA-256) before SD card purge.
* **Deficiencies & Blindspots:**
  * Strictly macOS-dependent (`launchd`, macOS filesystem mount assumptions).
  * No camera control, BLE, Wi-Fi, or live streaming capabilities.
  * Cannot interface with camera over MTP or network sockets directly (relies on mounted mass storage volumes).

### 4.3. `omokage-code/GPTransfer`
* **Repository:** `https://github.com/omokage-code/GPTransfer`
* **Language/Stack:** Swift, macOS AppKit / SwiftUI.
* **Capabilities:**
  * Direct USB connection transfer via macOS ImageCapture / MTP protocol.
  * Prevents OS-level kernel panics and transfer aborts on 4GB+ GoPro MP4s.
  * Safe staging architecture: downloads files to `.partial` buffers, validates byte size, and atomically moves to final destination.
  * Ingests sidecar files (`.WAV`, `.GPR`, `.THM`, `.LRV`).
* **Deficiencies & Blindspots:**
  * GUI only; no CLI flags or scriptable automation.
  * macOS only.
  * No camera control, telemetry parsing, or cloud syncing.

### 4.4. `itsankoff/gopro-plus`
* **Repository:** `https://github.com/itsankoff/gopro-plus`
* **Language/Stack:** Python, Docker.
* **Capabilities:**
  * Interacts directly with GoPro Cloud (Plus subscription) REST backend.
  * Bypasses the 25-file bulk download ceiling imposed by the official web portal.
  * Paged queries to `https://api.gopro.com/media` with original high-bitrate media and sidecar downloads.
  * Headless Dockerized container ideal for Synology/Unraid NAS automated backups.
* **Deficiencies & Blindspots:**
  * Authentication requires manual extraction of `AUTH_TOKEN` and `USER_ID` from web browser developer tools (cookies).
  * Cloud-only; zero local hardware interaction.
  * No chapter stitching or telemetry parsing on downloaded assets.

### 4.5. `KonradIT/gopro-py-api` & `goprowifihack`
* **Repository:** `https://github.com/KonradIT/gopro-py-api`
* **Language/Stack:** Python.
* **Capabilities:**
  * Extensive documentation and wrapper methods for HERO3 through HERO8 cameras.
  * Live preview UDP streaming pipeline (`udp://10.5.5.9:8554`).
* **Deficiencies & Blindspots:**
  * Legacy code structure; inconsistent error handling across firmware variants.
  * Lacks support for modern Protobuf BLE commands and COHN.

### 4.6. Telemetry & Sensors: `gopro/gpmf-parser` & `JuanIrache/gopro-telemetry`
* **Repository:** `https://github.com/gopro/gpmf-parser` (C) & `https://github.com/JuanIrache/gopro-telemetry` (Node.js)
* **Capabilities:**
  * GoPro embeds a separate telemetry track (`gpmd` track) in MP4 containers.
  * Streams parsed:
    * `GPS5`: Latitude, longitude, altitude, 2D speed, 3D speed (sampled at 18 Hz).
    * `ACCL`: 3-axis accelerometer (sampled at ~200 Hz).
    * `GYRO`: 3-axis gyroscope (sampled at ~200–400 Hz for Gyroflow stabilization).
    * `SHUT`, `ISOG`: Optical exposure parameters.
    * `CORI`: Camera orientation quaternions.
    * `GRAV`: Gravity vectors.
* **Deficiencies & Blindspots:**
  * Exists as raw libraries without end-to-end command-line pipelines for video creators.

### 4.7. GoPro Labs Firmware: `gopro/labs`
* **Architecture:** Custom firmware overlays running on HERO7 through HERO13.
* **Mechanism:** Optical QR code scanner parses encoded text strings when camera lens views the code.
* **Capabilities:**
  * Motion detection capture triggers (`!M...`).
  * Speed / GPS geofence triggers (`!S...`).
  * Bitrate boosts up to 180–200 Mbps (`*BITR=...`).
  * Scheduled wake/sleep timers.
  * Custom on-screen burn-in text / overlays.
* **CLI Potential:** Terminal CLI can generate instant ASCII / ANSI QR codes directly in the terminal window, enabling zero-connection camera programming.

---

## 5. Architectural Blueprint for `gopro-cli`

### 5.1. Core Command Hierarchy

```
gopro-cli
├── discover                     # Multi-transport scan (USB CDC-ECM, BLE 0xFEA6, LAN/COHN)
├── pair                         # Interactive BLE pairing & profile generator
├── status                       # Real-time dashboard: battery, SD space, temp, preset, state
├── record                       # Shutter control (start, stop, photo, timelapse, burst)
├── config                       # Get/set resolution, fps, fov, iso, shutter, ev, wb, bitrate
├── preset                       # List, switch, and create camera presets
├── stream                       # Live streaming & webcam control
│   ├── preview                  # Launch low-latency preview player (mpv / ffplay)
│   ├── live                     # Broadcast RTMP stream to YouTube/Twitch/custom URL
│   └── webcam                   # Start/stop USB webcam mode
├── media                        # In-camera SD card operations
│   ├── list                     # List files (filterable by date, type, resolution; JSON/Table)
│   ├── download                 # Parallel chunked download with resume & verification
│   ├── delete                   # Safe delete with confirmation flag
│   └── format                   # SD card format with protective safety lock
├── process                      # Local media post-processing
│   ├── stitch                   # Lossless chapter concatenation (MP4 stream copy)
│   ├── sync-dates               # Fix EXIF/creation timestamps using GPMF internal time
│   └── verify                   # Validate media file integrity
├── telemetry                    # Sensor data extraction
│   ├── extract                  # Extract GPMF to GPX, KML, GeoJSON, or CSV
│   └── gyro                     # Export raw gyro/accel data for Gyroflow
├── labs                         # GoPro Labs QR code engine
│   ├── qr                       # Render ANSI QR code in terminal or export PNG/SVG
│   └── preset                   # Common macro templates (motion detect, max bitrate, etc.)
├── cohn                         # Camera-on-Home-Network management
│   ├── scan                     # Scan available Wi-Fi networks via camera BLE
│   ├── provision                # Connect camera to home Wi-Fi and install TLS certs
│   └── info                     # Display LAN IP, TLS fingerprint, and connection state
└── cloud                        # GoPro Plus Cloud synchronization
    ├── auth                     # Save session tokens securely
    ├── list                     # Browse cloud media assets
    └── sync                     # Headless multi-threaded mirror to local NAS directory
```

---

## 6. Transport Selection & Auto-Negotiation Strategy

`gopro-cli` will implement a priority-based **Auto-Negotiation Transport Layer**:

```
                 +---------------------------+
                 | gopro-cli Command Trigger |
                 +---------------------------+
                               |
               Is Wired USB (CDC-ECM) Present?
                               |
                   +-----------+-----------+
                 YES                       NO
                   |                       |
        [Use Wired USB HTTP]     Is COHN (LAN HTTPS) Reachable?
        (Fastest, zero power drain)         |
                                   +-------+-------+
                                 YES               NO
                                   |               |
                         [Use COHN LAN HTTPS]  Is BLE Device Nearby?
                         (Retains Host Internet)   |
                                           +-------+-------+
                                         YES               NO
                                           |               |
                                  Is Fast Transfer    [Error: Camera]
                                     Required?        [Not Reachable]
                                           |
                                   +-------+-------+
                                 YES               NO
                                   |               |
                          [Power on Wi-Fi AP]  [Execute via BLE]
                          [Connect Host Wi-Fi] (Ultra low power)
```

1. **Tier 1 (Wired USB-C):** Default if cable connected. Highest bandwidth (40 MB/s), instant response, zero Wi-Fi hopping.
2. **Tier 2 (Wi-Fi COHN):** If wireless and camera provisioned on local LAN. Allows control and media download without breaking PC internet.
3. **Tier 3 (Wi-Fi AP):** If camera remote and large file download/streaming required. BLE triggers camera AP; host Wi-Fi negotiates link.
4. **Tier 4 (Pure BLE):** For status polling, shutter trigger, and quick setting changes when bandwidth is not required. Saves battery.

---

## 7. Media Processing & Ingest Pipeline Specifications

### 7.1. Chapter Stitching Specification
* **Problem:** Files split at 4,294,967,296 bytes (4GB FAT32 legacy boundary). A 45-minute 4K clip generates `GX010042.MP4`, `GX020042.MP4`, `GX030042.MP4`.
* **Standard Concat Bug:** Naive `ffmpeg -f concat` strips GPMF telemetry track or causes audio/video desync due to non-zero starting DTS timestamps on subsequent chapters.
* **`gopro-cli` Stitching Engine:**
  1. Inspect MP4 container tracks (`ffprobe -show_streams`).
  2. Map Track 0 (Video), Track 1 (Audio), Track 2 (Timecode/Spatial Audio), and Track 3 (`gpmd` telemetry).
  3. Generate dynamic FFmpeg concat filter or call `MP4Box -cat` to perform lossless stream copying:
     ```bash
     ffmpeg -f concat -safe 0 -i chapter_list.txt -map 0:v -map 0:a -map 0:m:handler_name:"GoPro MET" -c copy output.mp4
     ```
  4. Verify byte count and check that overall duration equals the sum of chapters.

### 7.2. High-Speed Download Engine
* Direct HTTP GET to `http://<ip>:8080/videos/DCIM/100GOPRO/<filename>`.
* Support `Range: bytes=X-Y` headers to spawn multi-threaded chunked downloads across USB/Wi-Fi.
* Staging strategy: write to `.download.part` file; atomic rename upon full SHA-256 / size verification.

---

## 8. GoPro Labs QR Generator Specification

`gopro-cli labs qr` will directly render QR codes into terminal standard output using Unicode block elements (`▀`, `▄`, `█`) or truecolor ANSI escapes.

**Supported Macro Presets:**
* **Max Bitrate:** `*BITR=180` (Boosts 4K/5.3K recording bitrate).
* **Motion Detection:** `!M1` (Begins recording only when optical motion detected; pauses when still).
* **Speed Trigger:** `!S50` (Starts recording once GPS speed exceeds 50 km/h).
* **Scheduled Capture:** `!08:00N` (Wake and record at 08:00 AM).
* **Custom Overlay:** `oT%m/%d/%y %H:%M:%S` (Burn real-time timestamp into video feed).

---

## 9. Technology Stack Recommendation for Implementation

| Consideration | Python (Click / Typer + Bleak) | Go (Cobra + TinyGo BLE) | Rust (Clap + Btleplug) |
| :--- | :--- | :--- | :--- |
| **Portability** | Requires Python runtime, pip dependencies. | Single compiled binary. Zero dependencies. | Single compiled binary. Zero dependencies. |
| **Official SDK Re-use**| Direct reuse of `open-gopro` models. | Re-implements Protobuf / REST. | Re-implements Protobuf / REST. |
| **Cross-Platform BLE** | `bleak` is mature across macOS/Linux/Win. | OS BLE libraries have edge quirks on Linux. | `btleplug` solid on macOS/Win/Linux. |
| **Media Concat / FFmpeg**| Subprocess to `ffmpeg` or `av` bindings. | Subprocess to `ffmpeg`. | Subprocess or static `ffmpeg-sys`. |
| **Concurrency (Download)**| Asyncio / ThreadPool. | Native Goroutines (excellent). | Tokio async runtime (excellent). |

### Recommended Phased Architecture
* **Core Language:** Python 3.11+ using `Typer` / `Rich` for rapid feature completeness, leveraging `bleak` for BLE, `httpx` for HTTP/2 multi-stream downloads, and Protobuf schema bindings.
* **Packaging:** Standalone binaries compiled via `PyInstaller` or `Nuitka` to distribute zero-dependency executables (`gopro-cli`) via Homebrew and direct GitHub releases.

---

## 10. Execution Roadmap

```
[Phase 1: Foundation & USB Control]
  ├── Project structure, CLI parser (Typer/Rich)
  ├── USB Network adapter auto-detection (172.2X.1XX.51)
  ├── Basic HTTP REST control (Status, Battery, Shutter Start/Stop)
  └── Media listing and fast chunked download engine

[Phase 2: Ingest & Post-Processing Pipeline]
  ├── Chapter auto-discovery and lossless FFmpeg stitching
  ├── Timestamp/EXIF timezone restoration
  ├── Embedded GPMF telemetry extraction to GPX/GeoJSON/CSV
  └── Terminal ASCII GoPro Labs QR code generator

[Phase 3: Wireless Transports (BLE & COHN)]
  ├── Cross-platform BLE scanner and pairing handshake
  ├── Protobuf BLE command dispatch (low-power wake/trigger)
  ├── COHN Wi-Fi provisioning and HTTPS local network communication
  └── Live preview streaming (RTSP/UDP) pipe to mpv/ffplay

[Phase 4: Cloud & Extensions]
  ├── GoPro Plus cloud authentication & NAS mirroring daemon
  ├── Multi-camera broadcast synchronization
  └── Future GUI / TUI companion exploration
```
