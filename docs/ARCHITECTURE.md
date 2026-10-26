# UEL-GoPro architecture

UEL-GoPro talks to cameras through the [OpenGoPro HTTP API](https://gopro.github.io/OpenGoPro/http/)
and the OpenGoPro BLE protocol. The transports are USB CDC-ECM, camera Wi-Fi
AP, and manual IP. On macOS the CLI can also read media over MTP, and BLE
handles scanning and commands.

## High-level layout

```
┌──────────────────────────────────────────────────────────────┐
│ CLI (Typer + Rich)                                          │
│ discover, status, record, config, preset, media, process,   │
│ telemetry, stream, labs, cloud                              │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
┌───────────────▼──────────────┐   ┌────────────▼──────────────┐
│ Transport                    │   │ Local processing          │
│ - USB CDC-ECM discovery      │   │ - FFmpeg chapter stitching│
│ - Wi-Fi AP / manual IP       │   │ - MP4 timestamp parsing   │
│ - MTP media fallback (macOS) │   │ - GPMF GPS parsing        │
│ - BLE scanner/commands       │   │ - QR rendering            │
└───────────────┬──────────────┘   └────────────┬──────────────┘
                │                               │
┌───────────────▼───────────────────────────────▼──────────────┐
│ Core: Pydantic models, exceptions, REST client               │
└──────────────────────────────────────────────────────────────┘
```

There is no global configuration file. Camera settings live on the camera,
cloud credentials live in `~/.config/uel-gopro/cloud.json`, and download/output
paths are CLI options.

## 1. Transport resolution

`transport/manager.py` resolves a camera in this order:

1. An explicit `--ip` address: plain HTTP on port 8080.
2. USB CDC-ECM: scan host interfaces for addresses that start with `172.20.`
   through `172.29.`, then probe the camera's `.51` address on port 8080.
3. Camera Wi-Fi AP: probe `10.5.5.9:8080`.

`transport/usb.py` calls `psutil.net_if_addrs()`, builds the camera address
from the host subnet (`.51`), and probes `/gopro/camera/state` before it
accepts a match. The probe uses a 2-second timeout by default.

### Explicit fallbacks

- MTP backs only `media list` and `media download`, and only when HTTP
  resolution raises `CameraNotFoundError`. It uses ImageCaptureCore through
  PyObjC, so it is macOS-only. Camera-control commands never fall back to MTP.
- BLE runs only when the user passes `--ble`. It is not part of automatic
  transport negotiation.
- COHN (camera on the home network) and mDNS are not implemented. The tree has
  no HTTPS or certificate handling and no mDNS discovery.

## 2. Status and settings

`api/rest.py` parses `/gopro/camera/state` with the current OpenGoPro status
IDs:

| ID | Meaning | Use |
|---|---|---|
| 2 | Internal battery bars (4 = charging) | `battery_bars`, `is_charging` |
| 6 | Overheating | `system_hot` |
| 8 | Busy | diagnostic only |
| 10 | Encoding | `is_recording`, `encoding_active` |
| 33 | Primary storage (`-1/0/1/2/3/4/8`) | `sd_status` |
| 34 | Remaining photos | `sd_remaining_photos` |
| 35 | Remaining video time | `sd_remaining_video_time_sec` |
| 54 | SD card remaining (KB) | `sd_remaining_mb` |
| 70 | Internal battery percentage | `battery_percent` (fallback: bars) |
| 96 | Preset group (`1000` video, `1001` photo, `1002` timelapse, `2000` general) | `current_mode` |
| 97 | Preset ID | `current_preset` |

The parser accepts numeric strings and skips fields it cannot convert. Real
camera state contains strings and empty strings (for example, `29` is the
connected Wi-Fi SSID), so one bad field must not break the status output.

`/gopro/camera/info` is optional: it is used by `status` when available
(HERO12+) and failures are ignored on older cameras.

Settings are written with:

```
GET /gopro/camera/setting?setting=<id>&option=<value>
```

The parameter is `option`, not `opt`. The CLI exposes modern aliases
(`resolution=2`, `fps=3`, `fov=121`, `bitrate=182`); callers can pass a numeric
ID when a camera uses a different setting.

## 3. Media download

`media/downloader.py` implements:

1. Authoritative size lookup. `HEAD` the download URL. If the camera rejects
   `HEAD` (405/501) or omits `Content-Length`, fall back to a one-byte ranged
   `GET` and read `Content-Range`/`Content-Length`. This avoids trusting the
   32-bit `s` field in `/gopro/media/list`.
2. Resume. Existing `.partial` bytes produce `Range: bytes=N-`.
3. Restart handling. A `200` response to a ranged request resets the buffer; a
   `416` restarts from zero.
4. Verification. The final byte count must match the authoritative size.
5. Atomic publish. The `.partial` file is renamed to the destination only after
   verification.

Downloads are sequential; there's no parallel chunk scheduler.

`media download --dest` treats a non-existent path without a suffix as a
directory and creates it. An existing file, or a path with a suffix, is used as
the target file.

## 4. Chapter stitching

GoPro chapter naming:

- Modern: `GX010123.MP4`, `GH020123.MP4`, `GL010123.LRV`, `GS010123.360`
- Legacy: `GOPR0789.MP4`, `GP010789.MP4`

`media/stitcher.py` groups by base ID and concatenates with:

```bash
ffmpeg -y -nostdin -f concat -safe 0 -i manifest.txt -map 0 -c copy out.mp4
```

`-map 0` preserves secondary tracks such as `tmcd` and `gpmd`; `-c copy` avoids
re-encoding. FFmpeg writes to a temporary `*.partial.*` file, which is renamed
only on success. So a failed run doesn't truncate an existing output.

FFmpeg's concat demuxer does not preserve `mvhd` creation time. The CLI
therefore reads the first chapter's creation time and applies it to the
stitched file with `os.utime`. If no timestamp can be recovered (common for
GoPro files with a zero `mvhd` time), it prints a warning.

`process stitch --output` is rejected for multiple chapter groups; without
`--output`, one `STITCH_<base>.mp4` is written per group.

## 5. GPMF telemetry

`telemetry/gpmf.py` parses GPMF KLV structures:

- Header: 4-byte FourCC, 1-byte type, 1-byte type size, 2-byte repeat,
  big-endian, payload padded to 4 bytes.
- Containers: `DEVC`, `STRM`, and type `0` are parsed recursively.
- Scalar types: `c`, `U`, `F`, `b/B`, `s/S`, `l/L`, `f`, `d`, `j/J`.
- GPS streams: `GPS5` (5 values/sample) and `GPS9` (9 values/sample). The
  fourcc is authoritative; the parser doesn't guess between 5 and 9 based
  only on divisibility.
- Scale: `SCAL` values are applied to latitude, longitude, altitude, and speed.
- Time: `GPS9` (and 7-field synthetic `GPS5`) carries days/seconds. Plain
  `GPS5` uses the most recent `GPSU` and a nominal 18 Hz sample interval.

Known limitations:

- `GPSP` (precision time) isn't parsed, so sub-second timestamps from plain
  `GPS5` are approximate.
- `ACCL` and `GYRO` streams only set `has_accel` / `has_gyro`; sample values are
  not decoded or exported.
- The exporter set is GPS-only: GPX, KML, GeoJSON, CSV. GeoJSON includes a
  `bbox` and uses `Point` for a single-point track.

`extract_gpmf_from_mp4` uses FFmpeg to copy the `GoPro MET` data track and
falls back to the first data stream and alternate muxers. Raw `.bin`, `.raw`,
and `.gpmf` files are passed through directly.

## 6. GoPro Labs QR rendering

`labs/qr.py` renders the QR matrix with Unicode half-blocks, two matrix rows
per terminal row. The quiet zone is four modules. The default is standard
polarity (black modules on a white background) via `30;47`; `--invert` uses
white modules on black via `97;40` for dark terminals. PNG/SVG output is
delegated to `segno`.

The printed code is a convenience. Check that it scans before you rely on a
Labs macro.

## 7. Cloud sync

`cloud/client.py` uses GoPro's undocumented media API with a bearer token. The
token file is written atomically with mode `0600`. Sync behavior:

- Pagination stops when the API returns the same page twice.
- Sync skips a file that already exists with the expected size.
- The client saves a different asset with the same filename under an asset ID
  prefix.
- The client keeps `.partial` buffers after a network error, so the next run
  resumes.
- A size mismatch deletes the invalid partial buffer.

There is no OAuth flow and no official API guarantee. Treat cloud support as
best-effort.

## 8. CLI error model

`uel_gopro.cli.main:main()` wraps the Typer app and converts `UelError` and
`OSError` into a single red error line with exit code 1. `KeyboardInterrupt`
exits 130. Command validation uses `typer.Exit(1)`. Click itself returns 2 for
usage errors such as an unknown command or option.

The CLI emits JSON for `discover`, `status`, `preset list`, `config get/list`,
`media list`, and `cloud list` with `typer.echo` rather than Rich, so you can
pipe it into other tools.

## 9. Testing

The suite runs offline:

- REST and cloud tests use `httpx.MockTransport` or mocked clients.
- Status tests use a captured OpenGoPro state payload plus string and
  empty-field cases.
- BLE tests assert the official SDK's wire bytes (`20 03 01 01 01` for shutter
  start).
- Media tests build synthetic MP4 boxes and cover HEAD fallback, resume, size
  mismatch, and atomic rename.
- GPMF tests build synthetic KLV streams for GPS5 (real type-size 4), GPS9
  (9 values/sample), GPSU accumulation, and exporters.
- Stitcher tests verify the manifest, FFmpeg arguments, temporary output, and
  error paths.

MTP tests skip when ImageCaptureCore is unavailable (for example on Linux).
