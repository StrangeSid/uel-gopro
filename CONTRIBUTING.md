# Contributing to UEL-GoPro

UEL-GoPro (Unofficial Extended Life GoPro Toolchain) is a local-first,
open-source CLI for OpenGoPro-compatible cameras. It is alpha software.
Correctness against real camera firmware matters more than adding features.

---

## Code of conduct

Be respectful, constructive, and considerate in all interactions. Harassment is
not tolerated.

---

## Getting started

### Prerequisites

- Python 3.11 or newer (3.13 recommended)
- uv ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))
- FFmpeg for chapter stitching and telemetry extraction
- mpv or ffplay for preview streaming (optional)

```bash
git clone https://github.com/StrangeSid/uel-gopro.git
cd uel-gopro
uv sync
uv run pytest -q
uv run ruff check src tests
uv run uel-gopro --help
```

---

## Development standards

- Keep changes surgical and scoped to one purpose.
- Prefer the standard library and existing dependencies over new ones.
- New code should use modern typing (`list[str]`, `str | None`) and
  `from __future__ import annotations`. Don't churn existing modules solely to
  change `Optional[...]` to `... | None`.
- Give every public function and method type hints and a useful docstring.
- Cite the protocol source in a comment or docstring whenever code talks to the
  camera (OpenGoPro HTTP spec, BLE status docs, or the official Python SDK).
- Never invent a camera endpoint or status ID. If it isn't documented, mark it
  as experimental and cover it with a test or a clear limitation in the docs.
- Don't add destructive commands (format, delete-all) without a documented,
  confirmed API and an explicit confirmation flow.

### Protocol references

- [OpenGoPro HTTP API](https://gopro.github.io/OpenGoPro/http/)
- [OpenGoPro BLE documentation](https://gopro.github.io/OpenGoPro/docs/ble)
- [Official Python SDK](https://github.com/gopro/OpenGoPro/tree/main/demos/python/sdk_wireless_camera_control)

When a protocol detail is ambiguous, prefer the official SDK's wire bytes and
schemas over community guesses.

---

## Testing without physical hardware

The suite runs offline. It mocks the hardware and network layers:

- REST and cloud tests use `httpx.MockTransport` or mocked clients.
- USB tests feed synthetic `psutil.net_if_addrs()` output.
- BLE tests use official-SDK packet vectors and a mocked `BleakClient`.
- GPMF tests build synthetic KLV streams, including real `type_size=4`
  GPS5/GPS9.
- MP4 tests build synthetic `ftyp`/`mdat`/`moov` boxes.
- FFmpeg tests mock `subprocess.run` to check arguments and manifests.
- MTP tests skip automatically when ImageCaptureCore is unavailable.

Run the suite:

```bash
uv run pytest -q
uv run pytest -v
uv run pytest tests/test_media.py
```

Lint:

```bash
uv run ruff check src tests
```

CI runs Python 3.11 through 3.13, Ruff, pytest, and a distribution build. The
publish workflow runs the same checks and verifies that the release tag matches
`pyproject.toml`.

---

## Architecture pointers

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) before changing transports,
GPMF parsing, or media handling. It lists the supported transports (USB
CDC-ECM, Wi-Fi AP, manual IP, macOS MTP media fallback, explicit BLE) and the
known limitations (no COHN, no SD format command, approximate GPS timestamps,
no IMU export).

---

## Pull request guidelines

1. Use descriptive branch names such as `fix/gpmf-gps9-stride`,
   `feat/webcam-fov`, or `docs/transport-support`.
2. Follow Conventional Commits, for example:
   - `fix(media): fall back to ranged GET when HEAD is rejected`
   - `fix(ble): frame command payloads once`
   - `docs(readme): document MTP limitations`
3. Before you open a PR:
   - `uv run pytest -q` passes.
   - `uv run ruff check src tests` passes.
   - `uv build` succeeds and the wheel and sdist include `COPYING`.
   - Documentation is updated if behavior or limitations change.
   - No build artifacts, tokens, or local config files are committed.

---

## Release process

1. Update `version` in `pyproject.toml` and `__version__` in
   `src/uel_gopro/__init__.py` (they must match).
2. Run the full test suite and `uv build`.
3. Commit, tag `vX.Y.Z`, and push the tag.
4. Publish a GitHub release. The `publish.yml` workflow tests, checks the tag
   against the package version, and publishes to PyPI via trusted publishing.
