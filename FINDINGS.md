# GoPro ecosystem audit and `uel-gopro` specification

- Target project: `uel-gopro` (Unofficial Extended Life GoPro)
- Location: `/Users/sid/Documents/proj/uel-gopro`
- Date: October 2026
- Document status: ecosystem and protocol audit

> Scope note (2026-10): This document is a broad audit of the GoPro
> ecosystem and protocol surface, not a description of the current UEL-GoPro
> implementation. The implemented feature set and its limitations are
> documented in [README.md](README.md) and
> [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). In particular, the current
> CLI does not implement COHN/mDNS, SD-card formatting, IMU export,
> parallel downloads, or BLE response/ack handling.

---

## 1. Summary and mission

UEL stands for Unofficial Extended Life. GoPro has deprecated open desktop tools and moved core features behind paywalls and mobile apps:

1. GoPro abandoned the Quik desktop app or rewrote it as an ad-filled subscription gateway for mobile devices. Desktop users on macOS, Linux, and Windows have no official first-class tools.
2. GoPro puts cloud backup, multi-device sync, and full-resolution offloading behind the GoPro Premium subscription, and the web portal caps manual downloads at 25 items.
3. The official GoPro Webcam utility for macOS and Windows is unstable, proprietary, and unsupported on Linux. Firmware updates regularly break webcam endpoints, including HERO13 Black regressions.
4. GPS and IMU telemetry extraction (speedometer, maps, g-force, Gyroflow stabilization) sits inside proprietary formats. Creators who want that data have to use closed tools.
5. The official `OpenGoPro` program provides only separate Python and Kotlin demo scripts. Users have no single cohesive tool.

### Mission of `uel-gopro`

`uel-gopro` is an independent, open-source, local-first CLI toolchain. It aims to give GoPro hardware an Unofficial Extended Life and return control of the camera to its owner. It combines the reverse-engineered and official interfaces in one terminal utility that configures, controls, ingests, processes, and extracts data from GoPro cameras without cloud subscriptions, proprietary apps, or mobile devices.

---

## 2. Hardware generations and protocol evolution

| Generation | Supported Transports | API Architecture | Firmware Gotchas & Limitations |
| :--- | :--- | :--- | :--- |
| **HERO3 / HERO3+** | Wi-Fi AP Only | BacPac HTTP GET (`/bacpac/...`) | Password-protected Wi-Fi. No BLE. |
| **HERO4 / HERO+** | Wi-Fi AP, Legacy BLE | Ambarella HTTP API (`/gp/gpControl/...`) | Early pairing handshake; basic status. |
| **HERO5 / HERO6 / HERO7** | Wi-Fi AP (5GHz/2.4GHz), BLE | Query string HTTP (`/gp/gpControl/command/...`) | First GPMF telemetry integration. GPS enabled. |
| **HERO8 Black / MAX** | Wi-Fi AP, BLE | Query string HTTP + BLE command characteristics | Firmware modified Wi-Fi keep-alive rules. |
| **HERO9 Black** | BLE, Wi-Fi AP, USB-C (FW >= v1.6) | OpenGoPro v1 Spec (Protobuf BLE, HTTP `/gopro/...`) | USB wired mode requires manual MTP/GoPro Connect toggle. |
| **HERO10 / HERO11 / 11 Mini** | BLE, Wi-Fi AP, USB-C Wired | OpenGoPro v2 Spec (Protobuf BLE, HTTP REST, CoAP) | High-speed CDC-ECM wired interface enabled by default. HERO11 (v01.10.00) wired bug after update. |
| **HERO12 Black** | BLE, Wi-Fi AP, Wi-Fi COHN (STA), USB-C | OpenGoPro v2 Spec + COHN (TLS/HTTPS over LAN) | **GPS hardware removed.** Bluetooth audio added. Native STA Wi-Fi. |
| **HERO13 Black** | BLE, Wi-Fi 6 AP, Wi-Fi COHN (STA), USB-C | OpenGoPro v2 Spec + Extended Protobuf | Lens Mod auto-detection. **Webcam endpoints changed/broken**; mDNS discovery dropouts. |
| **LIT HERO / MISSION / MAX 2** | BLE, Wi-Fi AP/STA, USB-C | OpenGoPro v2 Spec (FW >= v01.10.00) | Standardized on OpenGoPro v2 Protobuf & REST schema. |

---

## 3. Transport protocols and firmware bugs

### 3.1. Bluetooth Low Energy (BLE)
* Primary service UUID: `0000FEA6-0000-1000-8000-00805F9B34FB` (16-bit short form: `0xFEA6`).
* Company identifier: `0x02F2` (GoPro, Inc.).
* Key characteristics:
  * Command request (`b5f90072-...`): Write Without Response. Encapsulates control packets (shutter, presets, Wi-Fi AP power on).
  * Command response (`b5f90073-...`): notification characteristic that sends status and ack codes.
  * Setting request (`b5f90074-...`): changes camera settings (resolution, FPS, FOV).
  * Setting response (`b5f90075-...`): notifies the host of setting updates.
  * Query request (`b5f90076-...`): registers for real-time status and setting updates.
  * Query response (`b5f90077-...`): sends asynchronous notifications of status flags (battery %, SD space, recording time).
* Packet framing:
  * GoPro splits BLE payloads that exceed the MTU (typically 20 or 244 bytes, depending on OS negotiation) with a header:
    * General header: top bits `000` plus a 5-bit length for payloads up to 31 bytes.
    * Extended 13-bit header: top bits `001` plus a 13-bit length. The official SDK uses this form for writes.
    * Extended 16-bit header: top bits `010` plus a 16-bit length.
    * Continuation packet: top bit `1` plus a 4-bit sequence index.
  * `uel-gopro` writes the command payload (`command ID`, argument length, arguments) once and adds the 13-bit header. For shutter start the wire bytes are `20 03 01 01 01`.

### 3.2. Firmware bugs and edge cases

The cases below come from the OpenGoPro FAQ and field audits.

1. 32-bit file size overflow in `/gopro/media/list`.
   * On several firmware builds, the file size field `s` overflows 32-bit signed or unsigned bounds for files over 4GB (common on 4K/5.3K captures) and reports a corrupted size, such as a negative number or a value truncated modulo $2^{32}$.
   * Workaround for `uel-gopro`: never trust `s` in `/gopro/media/list` for downloads. Query HTTP `HEAD /videos/DCIM/100GOPRO/<filename>`, or use a one-byte ranged GET when the camera rejects `HEAD`.
2. Wi-Fi AP keep-alive dropouts.
   * The camera AP drops the connection without warning if it receives no keep-alive within 30 seconds.
   * Recommended approach: ping `/gopro/camera/keep_alive` during long sessions. The current CLI does not run a daemon for this.
3. HERO13 Black webcam and mDNS flaws.
   * The older `/gopro/webcam/start` endpoint fails or hangs on certain HERO13 builds.
   * mDNS discovery packets are sometimes dropped. Probing the USB subnet directly (`172.2X.1XX.51`) works more reliably than resolving the `.local` hostname.
4. CDC-ECM network routing conflict on macOS and Linux.
   * Connecting a GoPro over USB-C can send default-gateway traffic to the camera's internal DHCP gateway (`172.2X.1XX.1`) and cut off the host's internet access.
   * Recommended host-side workaround: set a route or interface metric so only `172.20.0.0/14` traffic uses the camera interface. This keeps the primary WAN gateway, and the current CLI does not automate it.

### 3.3. Wi-Fi COHN (camera on the home network, station mode)
* Topology: the camera joins the user's existing Wi-Fi LAN or WLAN.
* Mechanism:
  1. The host provisions the SSID and WPA passphrase over BLE.
  2. The camera creates a self-signed TLS certificate and shares its fingerprints over BLE.
  3. The camera gets a DHCP lease from the home router (`192.168.x.x`).
  4. The host sends commands over HTTPS, either bypassing TLS validation or importing the self-signed certificate.
* Advantage: the camera no longer needs an AP tether, and the computer keeps its internet connection while it batch downloads or scripts multi-camera rigs.

### 3.4. Wired USB-C (CDC-ECM, RNDIS, and NCM)
* Performance: direct IP over the USB link gives 30 to 42 MB/s.
* Camera endpoint: `http://172.2X.1XX.51:8080/`.
* Power: the link charges the camera continuously, so 24/7 timelapse and monitoring setups can run.

---

## 4. Existing open-source implementations

### 4.1. `gopro/OpenGoPro` (official reference)
* Repository: `https://github.com/gopro/OpenGoPro`
* Language and stack: Python (Bleak, Requests, FastAPI for mocking), Kotlin (KMP), Swift.
* Capabilities:
  * Authoritative OpenAPI and Protobuf specs for HERO9 through HERO13.
  * BLE discovery, Wi-Fi AP bootstrapping, and COHN provisioning scripts.
  * Broad endpoint mapping: shutter, presets, settings, status, media list, and stream initiation.
* Limitations:
  * The project has no functional CLI. Its demos are separate scripts (`cohn.py`, `wifi_stream.py`, `photo.py`).
  * No chapter concatenation or media assembly.
  * No telemetry extraction or format conversion.
  * Large dependency footprint (`bleak`, `protobuf`, `pydantic`, `rich`).
  * No backward compatibility with pre-HERO9 cameras.

### 4.2. `fxstein/GoProX`
* Repository: `https://github.com/fxstein/GoProX`
* Language and stack: shell (Bash/Zsh), a Homebrew tap, and a `launchd` service agent.
* Capabilities:
  * Detects mounted GoPro SD cards and volumes on macOS.
  * Chapter joining: stitches segmented 4GB chapters (`GX010001.MP4`, `GX020001.MP4`) into one file without re-encoding, using `ffmpeg` stream copy.
  * Metadata and EXIF preservation: corrects file modification and creation timestamps from GPMF metadata to keep NLE timelines in order.
  * Verifies SHA-256 checksums before it purges the SD card.
* Limitations:
  * macOS-only (`launchd` and macOS filesystem mount assumptions).
  * No camera control, BLE, Wi-Fi, or live streaming.
  * Can't talk to the camera over MTP or network sockets directly; it relies on mounted mass storage volumes.

### 4.3. `omokage-code/GPTransfer`
* Repository: `https://github.com/omokage-code/GPTransfer`
* Language and stack: Swift, macOS AppKit and SwiftUI.
* Capabilities:
  * Transfers over a direct USB connection through macOS ImageCapture and MTP.
  * Prevents OS-level kernel panics and transfer aborts on 4GB and larger GoPro MP4s.
  * Staging: downloads to `.partial` buffers, validates the byte size, and moves the file to its final destination atomically.
  * Also ingests sidecar files (`.WAV`, `.GPR`, `.THM`, `.LRV`).
* Limitations:
  * It has a GUI only and no CLI flags or scriptable automation.
  * It runs only on macOS.
  * No camera control, telemetry parsing, or cloud syncing.

### 4.4. `itsankoff/gopro-plus`
* Repository: `https://github.com/itsankoff/gopro-plus`
* Language and stack: Python, Docker.
* Capabilities:
  * Talks directly to the GoPro Cloud REST backend for Plus subscriptions.
  * Bypasses the 25-file bulk download ceiling on the official web portal.
  * Sends paged queries to `https://api.gopro.com/media` and downloads original high-bitrate media and sidecars.
  * Runs as a headless Docker container for automated backups on Synology or Unraid NAS.
* Limitations:
  * Authentication requires manual extraction of `AUTH_TOKEN` and `USER_ID` from browser developer tools (cookies).
  * It works only with the cloud and has no local hardware interaction.
  * No chapter stitching or telemetry parsing on downloaded assets.

### 4.5. `KonradIT/gopro-py-api` and `goprowifihack`
* Repository: `https://github.com/KonradIT/gopro-py-api`
* Language and stack: Python.
* Capabilities:
  * Covers HERO3 through HERO8 with extensive documentation and wrapper methods.
  * Provides a live preview UDP stream (`udp://10.5.5.9:8554`).
* Limitations:
  * Legacy code structure and inconsistent error handling across firmware variants.
  * No support for modern Protobuf BLE commands or COHN.

### 4.6. Telemetry and sensors: `gopro/gpmf-parser` and `JuanIrache/gopro-telemetry`
* Repository: `https://github.com/gopro/gpmf-parser` (C) and `https://github.com/JuanIrache/gopro-telemetry` (Node.js).
* Capabilities:
  * GoPro embeds a separate telemetry track (the `gpmd` track) in MP4 containers.
  * The tools parse these streams:
    * `GPS5`: latitude, longitude, altitude, 2D speed, 3D speed (sampled at 18 Hz).
    * `ACCL`: 3-axis accelerometer (sampled at about 200 Hz).
    * `GYRO`: 3-axis gyroscope (sampled at about 200 to 400 Hz for Gyroflow stabilization).
    * `SHUT`, `ISOG`: optical exposure parameters.
    * `CORI`: camera orientation quaternions.
    * `GRAV`: gravity vectors.
* Limitations:
  * These are raw libraries with no end-to-end command-line pipeline for video creators.

### 4.7. GoPro Labs firmware: `gopro/labs`
* Architecture: custom firmware overlays that run on HERO7 through HERO13.
* Mechanism: an optical QR scanner reads encoded text when the camera lens points at the code.
* Capabilities:
  * Motion detection capture triggers (`!M...`).
  * Speed and GPS geofence triggers (`!S...`).
  * Bitrate boosts in the 180 to 200 Mbps range (`*BITR=...`).
  * Scheduled wake and sleep timers.
  * Custom on-screen burn-in text and overlays.
* CLI potential: a terminal CLI can generate ASCII or ANSI QR codes directly in the terminal window, so the user can program the camera without a connection.

---

## 5. Planned architecture for `uel-gopro` (not current behavior)

### 5.1. Core command hierarchy

```
uel-gopro
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
    └── sync                     # Headless mirror to local NAS directory (planned)
```

---

## 6. Transport selection and auto-negotiation

The long-term design uses a priority order for transport selection. The current code does not implement that layer, and its resolver checks manual IP, then USB, then Wi-Fi AP. The diagram below shows the longer-term priority, not the current resolver:

```
                 +---------------------------+
                 | uel-gopro Command Trigger |
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

1. Tier 1 (wired USB-C): the default when a cable is connected. Highest bandwidth (40 MB/s), instant response, no Wi-Fi hopping.
2. Tier 2 (Wi-Fi COHN): used when the camera is wireless and provisioned on the local LAN. It allows control and media download without breaking the PC's internet connection.
3. Tier 3 (Wi-Fi AP): used when the camera is remote and a large download or stream is required. BLE starts the camera AP, and the host Wi-Fi connects to it.
4. Tier 4 (pure BLE): used for status polling, shutter triggers, and quick setting changes when bandwidth isn't required. It saves battery.

---

## 7. Media processing and ingest pipeline

### 7.1. Chapter stitching
* Problem: files split at 4,294,967,296 bytes (the 4GB FAT32 legacy boundary). A 45-minute 4K clip generates `GX010042.MP4`, `GX020042.MP4`, and `GX030042.MP4`.
* Standard concat bug: a naive `ffmpeg -f concat` strips the GPMF telemetry track or causes audio/video desync because subsequent chapters start with non-zero DTS timestamps.
* Current `uel-gopro` implementation:
  1. Group chapter files by GoPro base ID.
  2. Write an FFmpeg concat manifest.
  3. Run `ffmpeg -y -nostdin -f concat -safe 0 -i manifest -map 0 -c copy`.
  4. Write to a temporary output file, verify it is non-empty, then rename it.
  5. Restore the first chapter's capture timestamp when the MP4 exposes one.

  There's no `ffprobe` preflight or duration verification yet. A future
  improvement could map tracks explicitly and verify the sum of durations.

### 7.2. Download engine (current implementation)
* Direct HTTP GET to `http://<ip>:8080/videos/DCIM/<directory>/<filename>`.
* Authoritative size lookup with `HEAD`, and a one-byte ranged-GET fallback when
  `HEAD` is rejected. This avoids trusting the 32-bit size in `/gopro/media/list`.
* Resumable downloads use `Range: bytes=N-`, a `.partial` file, and an atomic
  rename after size verification.
* Downloads are sequential, not multi-threaded. There's no SHA-256 digest yet.

---

## 8. GoPro Labs QR generator

`uel-gopro labs qr` renders QR codes to standard output with Unicode block elements (`▀`, `▄`, `█`) or truecolor ANSI escapes.

Supported macro presets:
* Max bitrate: `*BITR=180` (boosts 4K/5.3K recording bitrate).
* Motion detection: `!M1` (starts recording when it detects optical motion, pauses when the scene is still).
* Speed trigger: `!S50` (starts recording once GPS speed exceeds 50 km/h).
* Scheduled capture: `!08:00N` (wakes and records at 08:00 AM).
* Custom overlay: `oT%m/%d/%y %H:%M:%S` (burns a real-time timestamp into the video feed).

---

## 9. Technology stack recommendation

| Consideration | Python (Click / Typer + Bleak) | Go (Cobra + TinyGo BLE) | Rust (Clap + Btleplug) |
| :--- | :--- | :--- | :--- |
| **Portability** | Requires Python runtime, pip dependencies. | Single compiled binary. Zero dependencies. | Single compiled binary. Zero dependencies. |
| **Official SDK Re-use**| Direct reuse of `open-gopro` models. | Re-implements Protobuf / REST. | Re-implements Protobuf / REST. |
| **Cross-Platform BLE** | `bleak` is mature across macOS/Linux/Win. | OS BLE libraries have edge quirks on Linux. | `btleplug` solid on macOS/Win/Linux. |
| **Media Concat / FFmpeg**| Subprocess to `ffmpeg` or `av` bindings. | Subprocess to `ffmpeg`. | Subprocess or static `ffmpeg-sys`. |
| **Concurrency (Download)**| Asyncio / ThreadPool. | Native Goroutines (excellent). | Tokio async runtime (excellent). |

### Recommended architecture
* Core language: Python 3.11+ with `Typer` and `Rich`, `bleak` for BLE, `httpx` for HTTP/2 multi-stream downloads, and Protobuf schema bindings.
* Packaging: build standalone binaries with `PyInstaller` or `Nuitka` and distribute zero-dependency executables (`uel-gopro`) through Homebrew and GitHub releases.

---

## 10. Execution roadmap

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
