# UEL-GoPro System Architecture

This document details the architectural design and low-level mechanics of **UEL-GoPro** (Unofficial Extended Life GoPro Toolchain).

```
                      +-----------------------------+
                      |      uel-gopro CLI          |
                      |   (Typer + Rich Engine)     |
                      +-----------------------------+
                                     |
              +----------------------+----------------------+
              |                      |                      |
              v                      v                      v
     +-----------------+    +-----------------+    +-----------------+
     | Transport Layer |    | Media Pipeline  |    | Telemetry / Labs|
     | Auto-Negotiate  |    | (Ingest/Stitch) |    |  (GPMF & QR)    |
     +-----------------+    +-----------------+    +-----------------+
```

---

## The 5-Layer Core Architecture

### 1. Transport Auto-Negotiation Layer

GoPro cameras communicate over multiple heterogeneous physical and link-layer transports. UEL-GoPro implements a priority-based auto-negotiation resolver:

```
                  +---------------------------+
                  |  Resolve Camera Transport |
                  +---------------------------+
                                |
             +------------------v------------------+
             | User explicit --ip specified?       |
             +------------------+------------------+
                       | YES             | NO
                       v                 v
            [ Probe target IP ]    [ 1. Probe USB CDC-ECM ]
                                   (172.2X.1XX.51:8080)
                                         |
                                         v Found?
                                  +------+------+
                                  | YES         | NO
                                  v             v
                             [ Connect ]   [ 2. Probe COHN LAN ]
                                           (Home Wi-Fi mDNS / DHCP)
                                                |
                                                v Found?
                                         +------+------+
                                         | YES         | NO
                                         v             v
                                    [ Connect ]   [ 3. Probe Wi-Fi AP ]
                                                  (10.5.5.9:8080)
                                                       |
                                                       v Found?
                                                +------+------+
                                                | YES         | NO
                                                v             v
                                           [ Connect ]   [ 4. BLE GATT / Fail ]
```

#### Priorities:
1. **USB CDC-ECM (Ethernet over USB):**
   - **Throughput:** ~30–40 MB/s.
   - **Mechanics:** When connected via USB-C in GoPro Connect / MTP mode, the camera enumerates as a USB CDC-ECM Ethernet adapter. The host machine is assigned an IP in a dynamic subnet (`172.2X.1XX.2`), while the camera binds strictly to `.51` on port `8080` (e.g. `172.24.162.51:8080`).
   - **Detection:** `uel_gopro.transport.usb.detect_usb_camera()` scans all active network interfaces using `psutil.net_if_addrs()` matching `^172\.(2[0-9])\.(\d{1,3})\.(\d{1,3})$`, infers the camera IP, and performs an HTTP probe against `/gopro/camera/state`.
2. **COHN (Camera on Home Network):**
   - **Throughput:** ~10–20 MB/s (Local Wi-Fi).
   - **Mechanics:** Introduced in HERO12/13 firmware. The camera joins the user's local Wi-Fi router (station mode). It obtains an IP via home DHCP and advertises via mDNS (`_gopro-web._tcp.local`) or can be targeted directly by IP.
3. **Wi-Fi Access Point (Station Mode on Host):**
   - **Throughput:** ~8–15 MB/s.
   - **Mechanics:** The camera acts as a software AP broadcasting an SSID. When the host joins, the camera gateway is fixed at `10.5.5.9:8080`.
4. **Bluetooth Low Energy (BLE GATT):**
   - **Throughput:** Low-bandwidth command/control (~few KB/s).
   - **Mechanics:** Used for waking up Wi-Fi AP, issuing shutter commands, or initial Wi-Fi provisioning without active IP connection.

---

### 2. 32-Bit Integer File Size Bug & HTTP HEAD Mitigation

#### The Firmware Bug:
In modern GoPro firmware (HERO9 through HERO13), the camera's internal media server exposes `/gopro/media/list` returning JSON records of media on the SD card:

```json
{
  "id": "100GOPRO",
  "media": [
    {
      "d": "100GOPRO",
      "fs": [
        {
          "n": "GX010450.MP4",
          "s": "4294967295"
        }
      ]
    }
  ]
}
```

The `s` (size in bytes) field is formatted as an unsigned 32-bit integer (`uint32_t`, max value $2^{32} - 1 = 4,294,967,295$ bytes). When recording long 4K/5.3K video clips with high bitrates or SD cards formatted with exFAT (where chapter limits can reach ~12 GB in newer firmware), file sizes exceeding 4 GB either:
1. **Truncate / Wrap around modulo $2^{32}$** (e.g., a 5.2 GB file reports as ~905 MB).
2. **Clamp to `4294967295`** ($4 \text{ GiB} - 1 \text{ byte}$).

If a downloader relies on `/gopro/media/list` for progress tracking, verification, or chunk calculation, the downloaded file is either prematurely truncated or flagged as corrupt.

#### The Mitigation:
UEL-GoPro never trusts the file size in the media listing. Instead:
1. `uel_gopro.media.downloader.get_remote_file_size(url)` issues an **HTTP HEAD** request directly to `/videos/DCIM/{directory}/{filename}`.
2. The camera's embedded HTTP daemon correctly returns the 64-bit size in the standard `Content-Length` header.
3. Downloads are written to a `.partial` file in chunks using HTTP `Range` headers, verified against the HEAD content length, and atomically renamed to `.MP4` upon completion.

---

### 3. Lossless Chapter Stitching Mechanics

#### Chaptering Structure:
GoPro cameras split long recordings into chapters to minimize data loss in the event of power cuts or file system corruption:
- **Modern Naming (HERO6 through HERO13):**
  - Pattern: `G{X|H|S|L}{chap:02d}{base:04d}.{MP4|LRV|360}`
  - Example: Base recording `0123` produces `GX010123.MP4` (Chapter 1), `GX020123.MP4` (Chapter 2), `GX030123.MP4` (Chapter 3).
  - Prefix `GX` = HEVC (H.265), `GH` = AVC (H.264), `GL` = Low Resolution Video, `GS` = MAX 360 Video.
- **Legacy Naming (HERO5 and older):**
  - Chapter 1: `GOPR0789.MP4`
  - Chapter 2+: `GP010789.MP4`, `GP020789.MP4`, etc.

#### Concatenation Mechanics:
Transcoding or naive re-encoding degrades video quality, consumes massive CPU/GPU time, and strips embedded metadata.

UEL-GoPro uses the **FFmpeg Concat Demuxer** in stream copy mode:

1. **Manifest Generation:**
   A temporary concat manifest is written with escaped file paths:
   ```
   file '/absolute/path/to/GX010123.MP4'
   file '/absolute/path/to/GX020123.MP4'
   file '/absolute/path/to/GX030123.MP4'
   ```
2. **Stream-Copy Invocation:**
   ```bash
   ffmpeg -y -f concat -safe 0 -i manifest.txt -map 0 -c copy output.mp4
   ```
3. **Preserving `gpmd` Telemetry:**
   The `-map 0` flag is critical: standard FFmpeg concatenation maps only default video and audio streams. GoPro MP4 files contain additional metadata tracks:
   - Stream 0:0: H.264 / HEVC Video.
   - Stream 0:1: AAC Audio.
   - Stream 0:2: `tmcd` (QuickTime Timecode).
   - Stream 0:3: `gpmd` (GoPro Metadata Format binary stream).
   Using `-map 0 -c copy` ensures that the `gpmd` track is passed through verbatim and remains contiguous across all joined chapters, allowing post-stitching GPS/gyroscope extraction.

---

### 4. GPMF Binary KLV Parser Architecture

GoPro embeds telemetry directly in the MP4 container as a binary track with FourCC handler `gpmd`.

#### Container Extraction:
UEL-GoPro uses `ffmpeg` to extract the raw GPMF byte payload without demuxing overhead:
```bash
ffmpeg -y -i input.mp4 -map 0:m:handler_name:"GoPro MET" -c copy -f rawvideo gpmf.bin
```
*(With automatic fallback to `-map 0:d:0` or stream index search).*

#### KLV Structure:
The stream is encoded in big-endian Key-Length-Value (KLV) structures:
- **FourCC (4 bytes):** ASCII identifier (e.g., `DEVC`, `STRM`, `GPS5`, `SCAL`, `SIUN`).
- **Type Character (1 byte):** Data type:
  - `'c'`: 8-bit signed char.
  - `'s'`: 16-bit signed integer.
  - `'S'`: 16-bit unsigned integer.
  - `'l'`: 32-bit signed integer (`>i4`).
  - `'L'`: 32-bit unsigned integer (`>u4`).
  - `'f'`: 32-bit IEEE-754 float (`>f4`).
  - `'U'`: UTC date/time string.
  - `'\x00'`: Complex container or nested KLV list.
- **Type Size (1 byte):** Byte size of a single unit.
- **Repeat Count (2 bytes):** Number of elements in the sample.
- **Payload (`Type Size * Repeat` bytes, padded to 32-bit boundary):**
  - If `Type == 0`, the payload contains nested child KLV elements.

```
+--------------------+---------+-----------+--------------+--------------------------+
| FourCC (4B)        | Type(1B)| Size (1B) | Repeat (2B)  | Payload (Size * Repeat)  |
| "GPS5"             | 'l' (0x6C)| 4       | 5 * N        | [Lat, Lon, Alt, Spd, 2D] |
+--------------------+---------+-----------+--------------+--------------------------+
```

#### Coordinate & Scale Decoding:
- `SCAL`: Scale factors associated with subsequent sensors.
- `GPS5`: Samples formatted as 5 signed 32-bit integers:
  $$\text{Latitude} = \frac{\text{raw}_0}{\text{scale}_{\text{lat}}}, \quad \text{Longitude} = \frac{\text{raw}_1}{\text{scale}_{\text{lon}}}$$
  $$\text{Altitude (m)} = \frac{\text{raw}_2}{\text{scale}_{\text{alt}}}, \quad \text{2D Speed (m/s)} = \frac{\text{raw}_3}{\text{scale}_{\text{spd}}}, \quad \text{3D Speed} = \frac{\text{raw}_4}{\text{scale}_{\text{3d}}}$$
- `GPSU`: Base UTC timestamp (e.g. `YYMMDDHHMMSS.sss`). Offsets for individual samples within each second are linearly interpolated based on sample count.

#### Exporter Pipeline:
The parsed `TelemetryTrack` object is fed to zero-dependency serialization exporters:
- **GPX:** Standard `<trk>` and `<trkpt>` XML with elevation, speed, and ISO UTC timestamps.
- **KML:** Google Earth `<LineString>` and coordinates tuple `<coordinates>lon,lat,alt ...</coordinates>`.
- **GeoJSON:** RFC 7946 `LineString` feature with coordinate array `[lon, lat, alt]` and bounding box properties.
- **CSV:** Tabular record `timestamp_iso,lat,lon,alt,speed_mps,fix`.

---

### 5. GoPro Labs QR Code Generation & Terminal Half-Blocks

GoPro Labs firmware interprets QR codes to configure deep camera settings and automation macros (e.g. `*BITR=180` for 180 Mbps high bitrate, `!M1` for optical motion detection, or `!08:00N` for scheduled wake-up).

```
  Top row module    --> ▀ (U+2580) Upper half block
  Bottom row module --> ▄ (U+2584) Lower half block
```

#### The Problem:
Standard QR codes rendered with ASCII full blocks `██` or spaces `  ` in terminal emulators produce a 2:1 vertical distortion because terminal font glyphs are typically twice as tall as they are wide. Cameras fail to scan distorted codes.

#### Terminal Half-Block Engine:
`uel_gopro.labs.qr.render_terminal_qr` computes an exact 1:1 square module aspect ratio by grouping pairs of vertical matrix rows:
1. Two vertical pixels $(x, y)$ and $(x, y+1)$ are mapped into a single terminal character cell using Unicode half-blocks:
   - Top light, bottom light $\rightarrow$ `' '` (space)
   - Top dark, bottom dark $\rightarrow$ `'█'` (full block `U+2588`)
   - Top dark, bottom light $\rightarrow$ `'▀'` (upper half block `U+2580`)
   - Top light, bottom dark $\rightarrow$ `'▄'` (lower half block `U+2584`)
2. ANSI background and foreground escape codes are configured for high-contrast scanning under camera lenses.
3. Polarities can be inverted (`--invert`) to support both dark-background and light-background terminal themes.
