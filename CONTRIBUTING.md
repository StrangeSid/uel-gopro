# Contributing to UEL-GoPro

Thank you for your interest in contributing to **UEL-GoPro** (Unofficial Extended Life GoPro Toolchain).

UEL-GoPro is a local-first, open-source CLI built to give GoPro hardware an extended life independent of mobile apps, cloud subscriptions, and vendor lock-in.

---

## Code of Conduct

We are committed to providing a welcoming, productive, and harassment-free environment for all contributors. Please be respectful, constructive, and considerate in all interactions.

---

## Getting Started

### Prerequisites

- **Python:** 3.11 or newer (Python 3.13 recommended)
- **uv:** Ultra-fast Python package and project manager ([installation guide](https://docs.astral.sh/uv/getting-started/installation/))
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **FFmpeg:** Required for media chapter stitching and telemetry extraction from MP4 containers
  - **macOS:** `brew install ffmpeg`
  - **Ubuntu / Debian:** `sudo apt-get install ffmpeg`
  - **Arch Linux:** `sudo pacman -S ffmpeg`

### Workspace Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/StrangeSid/uel-gopro.git
   cd uel-gopro
   ```

2. **Sync the virtual environment and dependencies:**
   ```bash
   uv sync
   ```

3. **Verify installation by running the test suite:**
   ```bash
   uv run pytest
   ```

4. **Run the local CLI binary in development mode:**
   ```bash
   uv run uel-gopro --help
   ```

---

## Development & Code Standards

### Python Standards

- **Python 3.11+ syntax:** Use modern standard library features and typing:
  - `from __future__ import annotations` at the top of every module.
  - Pipe union syntax: `str | None` instead of `Optional[str]`.
  - Built-in generics: `list[str]`, `dict[str, Any]` instead of `typing.List`, `typing.Dict`.
- **Strict type hints:** All public functions, methods, and classes must have complete type annotations.
- **Data models:** Use `pydantic` or `@dataclass` for typed data models and schemas.

### Karpathy Guidelines for Contributions

We follow surgical, simplicity-first engineering principles:

1. **Simplicity First:**
   - Solve the immediate problem with the minimum amount of code necessary.
   - Avoid speculative generalizations, premature abstractions, or unused configuration options.
   - If a solution requires 50 lines, do not write 200 lines.
2. **Surgical Changes:**
   - Touch only the code and files required to fulfill your change.
   - Do not reformat adjacent, unrelated lines or "clean up" unrelated files in feature PRs.
   - Keep pull requests tightly scoped to a single purpose.
3. **Surface Assumptions:**
   - Document any hardware quirks, firmware discrepancies, or protocol limitations you encounter.
   - Make verifiable claims backed by reproducible tests.

---

## Testing Without Physical Hardware

You do **not** need a physical GoPro connected to contribute or run tests. The test suite is designed to run 100% offline in CI environments and developer workstations.

### Mock Test Architecture

All hardware and network layers are isolated via mocks in `tests/`:

- **REST API & Network Calls (`httpx`):**
  We mock HTTP responses from the GoPro OpenGoPro HTTP daemon using `monkeypatch` or `pytest-mock`. Endpoints such as `/gopro/camera/state` and `/gopro/media/list` return synthetic JSON payloads.
  ```python
  def test_camera_status_mock(monkeypatch):
      class MockResponse:
          status_code = 200
          def json(self):
              return {"status": {"1": 100, "2": 0, "8": 0, "10": 0, "6": 128000}}
          def raise_for_status(self):
              pass

      class MockClient:
          def get(self, url, **kwargs):
              return MockResponse()

      monkeypatch.setattr("httpx.Client", MockClient)
  ```

- **Wired USB CDC-ECM Interface Scanning:**
  Network interface discovery via `psutil.net_if_addrs()` is mocked to simulate host network adapters assigned to the GoPro subnet (`172.2X.1XX.2`).
  
- **GPMF Binary Telemetry:**
  Synthetic binary streams with standard KLV blocks (`DEVC`, `STRM`, `GPS5`, `GPSU`, `SCAL`) are created in-memory to test the binary parser and exporters without needing multi-gigabyte video files.

- **FFmpeg Concat & Subprocess Calls:**
  `subprocess.run` is mocked to verify correct argument assembly (`-f concat -safe 0 -map 0 -c copy`) and error handling without spawning long-running video encode processes.

### Running Tests

Execute the full suite:
```bash
uv run pytest
```

Run tests with verbose output and coverage:
```bash
uv run pytest -v
```

Run a specific test file:
```bash
uv run pytest tests/test_media.py
```

---

## Architectural Pointers

Before making structural modifications, please read the architectural specification:

- **[Architecture Deep-Dive](docs/ARCHITECTURE.md):** Detailed documentation of the 5-layer system:
  1. Priority-based transport auto-negotiation (USB CDC-ECM -> COHN -> Wi-Fi AP -> BLE).
  2. The 32-bit integer file size firmware bug and HTTP `HEAD` mitigation.
  3. Lossless chapter concatenation mechanics via FFmpeg concat demuxer with `gpmd` telemetry preservation.
  4. GPMF binary KLV parser and coordinate decoding architecture.
  5. GoPro Labs QR code generation engine with terminal half-block rendering.

---

## Pull Request Guidelines

1. **Branch Naming:** Use descriptive branch names:
   - `feat/cohn-mdns-discovery`
   - `fix/gpmf-negative-elevation`
   - `docs/architecture-diagram`
2. **Commit Messages:** Follow the Conventional Commits specification:
   - `feat(media): add parallel download worker pool`
   - `fix(transport): handle cdc-ecm interface disconnection`
   - `docs(contributing): update testing instructions`
3. **Verify CI Checks:**
   - All tests pass: `uv run pytest`.
   - No untracked artifacts or temporary files are committed.
