# UEL-GoPro roadmap

This file plans work after the 0.1.1 source tree. 0.1.1 was tagged and published to GitHub and PyPI on 2026-10-28 on software checks only. The hardware matrix remains open. A hardware failure should ship as a 0.1.2 patch before 0.2.0.

Dates are relative weeks and assume one maintainer with access to HERO9 through HERO13, one macOS host, and one Linux host. Ordering is by risk.

## Current baseline

- The suite has 107 offline tests for protocol construction, parsers, mocked HTTP, and synthetic media. CI runs them on Linux only.
- Transports are USB CDC-ECM, Wi-Fi AP, and manual IP. MTP is macOS-only and media-only. The BLE client can send shutter and Wi-Fi AP commands, the CLI exposes shutter only, and there's no response parsing.
- Telemetry covers GPS5 and GPS9 points with SCAL and GPSU. GPSP is ignored. IMU streams are detected but not decoded.
- Media downloads are sequential and resumable, with byte-count checks. There are no checksums, free-space checks, or parallel transfers. Stitch uses FFmpeg stream copy.
- Distribution has no stable Homebrew tap, no signed binaries, no `py.typed`, and no coverage or type-check gate. The local PyInstaller spec is gitignored.

## 1. v0.1.1 publication and hardware gate

The software and publication gate is complete. The hardware matrix below was not run for 0.1.1 and now blocks 0.2.0. A hardware failure should ship as a 0.1.2 patch.

| Check | HERO9 | HERO10 | HERO11 | HERO12 | HERO13 |
|---|---|---|---|---|---|
| USB CDC-ECM: discover, status, record | run | run | run | run | run |
| Wi-Fi AP: discover, status, record | run | run | run | run | run |
| BLE shutter and Wi-Fi AP enable | run | run | run | run | run |
| Webcam 480p, 720p, 1080p | run | run | run | run | run |
| MTP list and download (macOS host) | run | run | run | run | run |
| Stitch two or more chapters | run | run | run | run | run |
| Real GPS5 or GPS9 track | run | run | run | run | run |

Legend: run means execute on that model and record pass, fail, or unsupported with the firmware or host reason.

Evidence lives in `docs/validation/0.1.1.md` and records date, host OS, camera model, firmware, command, result, and one output line. A fail on USB, Wi-Fi, BLE, stitch, or GPS blocks 0.2.0. Webcam and MTP may be unsupported only with a stated reason. At least one real GPS5 track and one real GPS9 track must pass, whichever models emit each format.

- [x] Run `uv sync`, `uv run pytest -q`, `uv run ruff check src tests`, and `uv build` on the release commit. All four pass; see [docs/validation/0.1.1.md](docs/validation/0.1.1.md).
- [x] Create annotated tag `v0.1.1` and push it. The publish workflow accepted the tag and version match.
- [x] Publish a GitHub release with changes since 0.1.0, the validation link, and known limitations. The release is public at https://github.com/StrangeSid/uel-gopro/releases/tag/v0.1.1.
- [x] Publish to PyPI through the trusted-publishing workflow. A clean install reports 0.1.1.
- [x] Decide Homebrew: HEAD-only for 0.1.1, with a stable tap deferred. The formula and README record the decision.
- [x] Attach wheel, sdist, and `SHA256SUMS` to the release. The release has all three assets.
- [ ] Test `install.sh` on both paths: git install from `main` and the PyPI fallback. Done when both produce a working 0.1.1 command.

## 2. Protocol work

- [ ] BLE responses: subscribe to `COMMAND_RSP`, reassemble multi-packet notifications, decode response ID and status, and match them to the request with a timeout. Done when shutter returns a typed ack or error and tests cover ack, error, fragmentation, and timeout.
- [ ] BLE pairing: use the backend pairing call where available and document OS-level pairing otherwise. Add `--pair`. Done when a fresh macOS host and a fresh Linux host pair and send shutter.
- [ ] BLE selection: add `--ble-address` and a clear error when several cameras advertise. Done when a two-camera scan can target one device.
- [ ] COHN: decide implement or drop by the end of Phase 1. Criteria are HTTPS certificate handling, mDNS on macOS and Linux, one test camera, and a provisioning path. Done when the decision is written down; if implemented, add a transport with tests; if dropped, remove COHN from the README transport table and add it to section 7.
- [ ] GPSP: parse precision time and use it to anchor GPS5 sample times instead of the nominal 18 Hz interval. Done when a real GPS5 fixture matches the GPSP second and sub-second fields and the README limitation is removed.
- [ ] IMU: decode ACCL and GYRO with SCAL and stream timestamps. Add `telemetry export --stream imu --format csv|json`. Done when units (g, deg/s), sample counts, and a real fixture are documented and tested.
- [ ] Grouped media: add `media list --grouped` and a `groups` array in JSON. Done when `GX010042` and `GX020042` collapse into one group and the schema doc is updated.
- [ ] Webcam status: add `stream webcam status` using the existing REST call, exit 0 when active and 3 when idle. Done when a mocked test and a hardware check pass.
- [ ] Webcam exit: add a test that `stream webcam stop` exits cleanly when the camera is already idle. Done when no traceback appears.
- [ ] Preview readiness: poll the preview status endpoint before launching a player, with a bounded wait and an actionable timeout. Add `--rtsp` only if the camera exposes a usable RTSP URL. Done when the player starts only after ready and the timeout path is tested.
- [ ] Legacy scope: set the control boundary at HERO9. HERO8 and older keep file-name parsing only. Done when control commands reject unsupported models with a message that names the model and the minimum, and the README says so.

## 3. Reliability and performance

- [ ] Retries: bounded exponential backoff with jitter for GETs and downloads on connection errors, 408, 429, and 5xx. Honor `Retry-After`. Don't retry settings writes. Done when each class has a transport test and `--retries` is documented.
- [ ] Connection reuse: hold one `httpx.Client` per CLI invocation and close it in a finally block. Keep the injected-client path for tests. Done when a test asserts one client and a close.
- [ ] Keep-alive: optional timer during long downloads and preview, with the interval below the camera idle timeout. Done when a 30 minute Wi-Fi download completes without reconnecting.
- [ ] Parallel downloads: `--jobs N`, default 1, cap 3, one file per worker, per-file `.partial` files, atomic rename. Done when a three-file test shows no interleaved writes and matching digests.
- [ ] Checksums: compute SHA-256 while streaming, write `<file>.sha256`, and add `media verify`. The camera API has no checksum endpoint, so this proves local integrity after resume. Done when a resumed download matches a fresh digest.
- [ ] Free space: check `disk_usage` against the authoritative size plus a small margin before opening a partial file. Add `--force` to override. Done when a mocked low-space test fails early with the needed bytes.
- [ ] Cloud auth: choose OAuth device flow or token capture. If OAuth isn't viable for an undocumented API, add `cloud auth --token-stdin`, warn on expiry, and document browser capture. Done when the decision is recorded and no token appears in shell history or logs.
- [ ] Rate limiting: conservative configurable requests per second and a page-size cap for cloud calls, with 429 backoff. Done when a 429 then success test passes and no burst exceeds the limit.

## 4. UX and tooling

- [ ] JSON schema: add `schema_version: 1`, stable keys, ISO 8601 UTC timestamps, and a JSON error object on stderr when `--json` is set. Document the envelope in `docs/json.md`. Done when snapshot tests cover each JSON command.
- [ ] Completions: turn on Typer completion and document bash, zsh, and fish install. Done when `uel-gopro --show-completion zsh` works and the docs list the setup.
- [ ] Batch: `media download --all --match`, `telemetry export --recursive`, and `process stitch --recursive`. Done when each has a test and `--dry-run` prints the plan.
- [ ] Dry-run: `--dry-run` for `media delete`, `media download`, `process stitch`, and `cloud sync`. Done when no mutation or file write occurs and the plan is printed.
- [ ] Logging: `--log-file` and `--verbose`, with tokens redacted. Done when a test proves a token never appears in log output.
- [ ] Config file: keep no global config through 0.2.0. Use flags and documented `UEL_GOPRO_*` environment variables. Revisit only when three or more commands repeat the same settings. Done when README and architecture agree and no dead config module exists.
- [ ] TUI: keep it out of core. If pursued, build a separate package against the REST and media APIs. Done when no TUI dependency enters `pyproject.toml`.

## 5. Distribution

- [ ] PyInstaller: commit a spec, since the current one is gitignored, and build macOS arm64, macOS x86_64, and Linux x86_64. Smoke test `--help` and `--version`. Done when artifacts run on clean hosts and BLE and MTP caveats are documented.
- [ ] Signing: macOS Developer ID with hardened runtime, notarization, and stapling; Linux Sigstore or minisign signatures. Done when `spctl -a -vv` accepts the app and `cosign verify-blob` passes.
- [ ] Release workflow: on tag, build sdist, wheel, binaries, and `SHA256SUMS`, attach them to the GitHub release, then publish PyPI after tests. Add a `workflow_dispatch` dry run. Done when a dry run produces artifacts without publishing.
- [ ] `py.typed`: ship the marker in the wheel and add a mypy job for `src` with `disallow_untyped_defs`. Done when the marker is in the wheel and CI is green.
- [ ] Coverage: add pytest-cov, report the number, and enforce a floor at the current level, raised by 5 points per minor release. Done when CI fails below the floor.
- [ ] Dependency scanning: Dependabot for pip and Actions, weekly `pip-audit`, and `uv lock --check` in CI. Done when alerts are on and the audit job is green.

## 6. Security

- [ ] Path sanitization: parameterized tests for `..`, absolute paths, drive letters, NUL, trailing dots and spaces, reserved Windows names, and unicode in `media download`, MTP, and cloud filenames. Done when no write escapes `--dest` and the error names the rejected input.
- [ ] TLS for COHN: only if COHN is implemented. Use system trust plus an optional SPKI pin; never `verify=False`. Done when a wrong pin fails, a right pin passes, and tests cover both.
- [ ] Keyring: store the cloud token in the OS keyring through an optional `keyring` extra, with a 0600 file fallback and a warning. Migrate `cloud.json`. Done when macOS and Linux use the keyring and `--no-keyring` keeps the file path.
- [ ] Signed releases: Sigstore bundles or minisign signatures for artifacts, plus GitHub attestations. Done when the README verification steps pass on a clean machine.

## 7. Non-goals and deferred work

- Windows support. Not planned through 0.3. Supported hosts are macOS and Linux.
- SD-card formatting. No documented endpoint exists, so keep the CLI out of it.
- Firmware updates.
- Official GoPro Plus support. The endpoint is undocumented and can change.
- TUI and multi-camera synchronized trigger. Separate projects.
- Gyroflow integration. Revisit after IMU export ships.
- MAX 360 reframing and equirectangular processing.
- Background daemon, watch folders, and automatic upload.
- RTMP or SRT live streaming.

## 8. Sequencing

| Phase | Window | Work | Exit criteria |
|---|---|---|---|
| 0 | week 1 | v0.1.1 gate | software checks and publication complete; hardware matrix open; HEAD-only Homebrew recorded |
| 1 | weeks 2-3 | BLE ack and pairing, GPSP, webcam status, preview readiness, legacy scope, COHN decision | hardware rows pass, tests added, decision written |
| 2 | weeks 3-4 | retries, reuse, keep-alive, free space, checksums, parallel downloads | soak test passes with no regression |
| 3 | weeks 5-6 | JSON schema, completions, batch, dry-run, logging, config decision | docs and snapshot tests merge |
| 4 | weeks 6-7 | PyInstaller, signing, py.typed, coverage, scanning | signed artifacts verify and CI gates are green |
| 5 | week 8 | 0.2.0 release | same gate as 0.1.1, plus the protocol items |

Phase 1 and Phase 2 may overlap after the 0.1.1 tag. Phase 4 depends on the release workflow from Phase 0.

0.2.0 is done when BLE acks, GPSP, IMU export, checksums, JSON schema v1, and signed artifacts ship, and COHN is either implemented or removed from the docs.
