from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from uel_gopro import __version__
from uel_gopro.core.exceptions import CameraNotFoundError, MediaError, TransportError, UelError
from uel_gopro.media.downloader import download_file
from uel_gopro.media.exif import extract_creation_time, sync_file_time
from uel_gopro.media.stitcher import detect_chapters, stitch_chapters
from uel_gopro.transport.manager import resolve_camera
from uel_gopro.transport.usb import detect_usb_camera

console = Console()
err_console = Console(stderr=True)
logger = logging.getLogger(__name__)

app = typer.Typer(
    name="uel-gopro",
    help="UEL-GoPro: Unofficial Extended Life GoPro CLI Toolchain.\nLocal-first, open-source control.",
    add_completion=False,
)

record_app = typer.Typer(name="record", help="Camera shutter & recording commands")
config_app = typer.Typer(name="config", help="Camera setting mutation commands")
preset_app = typer.Typer(name="preset", help="Camera preset selection")
media_app = typer.Typer(name="media", help="On-camera SD card media management")
process_app = typer.Typer(name="process", help="Local media post-processing (chapter stitch, EXIF)")
telemetry_app = typer.Typer(name="telemetry", help="GPMF telemetry parsing and export")
stream_app = typer.Typer(name="stream", help="Live preview streaming and USB webcam")
labs_app = typer.Typer(name="labs", help="GoPro Labs QR code generator")
cloud_app = typer.Typer(name="cloud", help="GoPro Plus Cloud sync & backup")

app.add_typer(record_app)
app.add_typer(config_app)
app.add_typer(preset_app)
app.add_typer(media_app)
app.add_typer(process_app)
app.add_typer(telemetry_app)
app.add_typer(stream_app)
app.add_typer(labs_app)
app.add_typer(cloud_app)


def version_callback(value: Optional[bool]) -> None:
    if value:
        console.print(f"[bold cyan]uel-gopro[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show version and exit"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose debug logging"),
) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# -----------------------------------------------------------------------------
# Discovery & status
# -----------------------------------------------------------------------------

@app.command("discover")
def cmd_discover(
    scan_ble: bool = typer.Option(False, "--ble", "-b", help="Scan for nearby BLE GoPro cameras"),
    json_output: bool = typer.Option(False, "--json", help="Output results in JSON format"),
    timeout: float = typer.Option(2.5, "--timeout", "-t", help="Scan timeout in seconds"),
) -> None:
    """Scan USB CDC-ECM, USB MTP, and optionally BLE for GoPro cameras."""
    import asyncio

    from uel_gopro.transport.ble import GoProBleClient

    cam = detect_usb_camera(timeout_sec=timeout)

    mtp_cam = None
    if not cam:
        mtp = None
        try:
            from uel_gopro.transport.mtp import MtpClient, is_mtp_available

            if is_mtp_available():
                mtp = MtpClient()
                mtp_cam = mtp.detect_camera(timeout_sec=timeout)
        except Exception as exc:  # MTP is an optional macOS-only backend
            logger.debug(f"MTP discovery failed: {exc}")
        finally:
            if mtp is not None:
                mtp.close()

    ble_devices = []
    if scan_ble:
        console.print("[cyan]Scanning for GoPro BLE devices...[/cyan]")
        try:
            ble_devices = asyncio.run(GoProBleClient.scan(timeout=timeout))
        except Exception as exc:
            raise TransportError(f"BLE scan failed: {exc}") from exc

    if json_output:
        results = []
        if cam:
            results.append(cam.model_dump())
        if mtp_cam:
            results.append(mtp_cam.model_dump())
        for device in ble_devices:
            results.append(
                {
                    "model_name": getattr(device, "name", "GoPro BLE"),
                    "address": getattr(device, "address", ""),
                    "transport": "ble",
                }
            )
        typer.echo(json.dumps(results, indent=2, default=str))
        return

    table = Table(title="Discovered GoPro Devices", show_header=True, header_style="bold magenta")
    table.add_column("Interface / Address", style="cyan")
    table.add_column("Location / Name", style="green")
    table.add_column("Port / Channel", style="yellow")
    table.add_column("Transport", style="blue")

    found_any = False
    if cam:
        table.add_row(cam.interface_name or "usb", cam.ip_address, str(cam.port), cam.transport.value.upper())
        found_any = True
    if mtp_cam:
        table.add_row("USB-MTP", mtp_cam.model_name, "PTP/MTP", "USB (MTP MODE)")
        found_any = True
    for device in ble_devices:
        table.add_row(
            getattr(device, "address", "Unknown"),
            getattr(device, "name", "GoPro"),
            "BLE",
            "BLUETOOTH",
        )
        found_any = True

    if found_any:
        console.print(table)
    else:
        console.print("[yellow]No GoPro cameras found.[/yellow]")
        console.print(
            "[dim]Hint: For USB, connect via USB-C in 'GoPro Connect' or 'MTP' mode. "
            "For BLE, pass --ble.[/dim]"
        )


@app.command("status")
def cmd_status(
    ip: Optional[str] = typer.Option(None, "--ip", help="Manual camera IP"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Connect and query camera state over BLE"),
    json_output: bool = typer.Option(False, "--json", help="Output status in JSON format"),
) -> None:
    """Display camera state: battery, SD space, mode, firmware, and thermals."""
    import asyncio

    from uel_gopro.transport.ble import GoProBleClient

    if use_ble:
        console.print("[cyan]Connecting to GoPro over Bluetooth Low Energy...[/cyan]")

        async def query_ble():
            devices = await GoProBleClient.scan(timeout=3.0)
            if not devices:
                raise UelError("No GoPro cameras discovered over BLE. Ensure the camera is awake.")
            target = devices[0]
            client = GoProBleClient(address=target.address)
            await client.connect()
            try:
                battery = await client.get_battery_level()
                info = await client.get_device_info()
            finally:
                try:
                    if client.is_connected:
                        await client.disconnect()
                except Exception:
                    pass
            return target, battery, info

        try:
            target, battery, dev_info = asyncio.run(query_ble())
        except UelError:
            raise
        except Exception as exc:
            raise TransportError(f"BLE status query failed: {exc}") from exc

        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "transport": "ble",
                        "device_name": getattr(target, "name", "GoPro"),
                        "address": target.address,
                        "battery_percent": battery,
                        **dev_info,
                    },
                    indent=2,
                )
            )
            return

        battery_str = f"{battery}%"
        if battery < 20:
            battery_str = f"[bold red]{battery_str}[/bold red]"
        else:
            battery_str = f"[bold green]{battery_str}[/bold green]"

        panel_text = (
            f"[bold cyan]Camera:[/bold cyan]       {getattr(target, 'name', 'GoPro')} "
            f"({dev_info.get('model', 'Unknown model')})\n"
            f"[bold cyan]Address:[/bold cyan]      {target.address} (BLE)\n"
            f"[bold cyan]Battery:[/bold cyan]      {battery_str}\n"
            f"[bold cyan]Firmware:[/bold cyan]     {dev_info.get('firmware', 'Unknown')}\n"
            f"[bold cyan]Serial:[/bold cyan]       {dev_info.get('serial', 'Unknown')}"
        )
        console.print(Panel(panel_text, title="[bold]GoPro BLE Dashboard[/bold]", border_style="cyan"))
        return

    info, client = resolve_camera(target_ip=ip)
    status = client.get_status()

    try:
        details = client.get_camera_info() or {}
        info.model_name = details.get("model_name") or info.model_name
        info.firmware_version = details.get("firmware_version") or info.firmware_version
        info.serial_number = details.get("serial_number") or info.serial_number
    except UelError as exc:
        # /gopro/camera/info is unavailable on HERO9-11; state info still works.
        logger.debug(f"Camera info endpoint unavailable: {exc}")

    if json_output:
        typer.echo(
            json.dumps(
                {"camera": info.model_dump(), "status": status.model_dump()},
                indent=2,
                default=str,
            )
        )
        return

    if status.battery_percent is not None:
        battery_str = f"{status.battery_percent}%"
    elif status.battery_bars is not None and 0 <= status.battery_bars <= 3:
        battery_str = f"{status.battery_bars}/3 bars"
    else:
        battery_str = "Unknown"

    if status.is_charging:
        battery_str += " ⚡ [green](Charging)[/green]"
    elif status.battery_percent is not None and status.battery_percent < 20:
        battery_str = f"[bold red]{battery_str}[/bold red]"

    recording = "[bold red]● RECORDING[/bold red]" if status.is_recording else "[dim]Standby[/dim]"
    free_mb = f"{status.sd_remaining_mb:,} MB free" if status.sd_remaining_mb is not None else "free space unknown"
    preset_line = f" (preset {status.current_preset})" if status.current_preset else ""

    remaining_parts = []
    if status.sd_remaining_photos is not None:
        remaining_parts.append(f"{status.sd_remaining_photos:,} photos")
    if status.sd_remaining_video_time_sec is not None:
        total_seconds = max(0, status.sd_remaining_video_time_sec)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        remaining_parts.append(f"{hours:d}:{minutes:02d}:{seconds:02d} video")
    remaining_str = " / ".join(remaining_parts) if remaining_parts else "unknown"

    panel_text = (
        f"[bold cyan]Camera:[/bold cyan]     {info.model_name}\n"
        f"[bold cyan]Link:[/bold cyan]       {info.ip_address}:{info.port} ({info.transport.value.upper()})\n"
        f"[bold cyan]Firmware:[/bold cyan]   {info.firmware_version}\n"
        f"[bold cyan]Serial:[/bold cyan]     {info.serial_number or 'Unknown'}\n"
        f"[bold cyan]Battery:[/bold cyan]    {battery_str}\n"
        f"[bold cyan]State:[/bold cyan]      {recording}\n"
        f"[bold cyan]Mode:[/bold cyan]       {status.current_mode}{preset_line}\n"
        f"[bold cyan]SD card:[/bold cyan]    {status.sd_status} ({free_mb})\n"
        f"[bold cyan]Remaining:[/bold cyan]  {remaining_str}\n"
        f"[bold cyan]Thermals:[/bold cyan]   "
        f"{'[bold red]OVERHEAT WARNING[/bold red]' if status.system_hot else '[green]Nominal[/green]'}"
    )
    console.print(Panel(panel_text, title="[bold]GoPro Status[/bold]", border_style="cyan"))


# -----------------------------------------------------------------------------
# Record commands
# -----------------------------------------------------------------------------

async def _dispatch_ble_shutter(start: bool) -> None:
    from uel_gopro.transport.ble import GoProBleClient

    devices = await GoProBleClient.scan(timeout=3.0)
    if not devices:
        raise UelError("No GoPro cameras discovered over BLE.")
    client = GoProBleClient(address=devices[0].address)
    try:
        await client.connect()
        if start:
            await client.shutter_start()
        else:
            await client.shutter_stop()
    except UelError:
        raise
    except Exception as exc:
        raise TransportError(f"BLE shutter command failed: {exc}") from exc
    finally:
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass


@record_app.command("start")
def cmd_record_start(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger shutter via BLE"),
) -> None:
    """Start video recording or timelapse in the current camera mode."""
    import asyncio

    if use_ble:
        asyncio.run(_dispatch_ble_shutter(start=True))
        console.print("[bold red]● Shutter started over BLE[/bold red]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.shutter_start()
    console.print("[bold red]● Shutter started[/bold red]")


@record_app.command("stop")
def cmd_record_stop(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger shutter via BLE"),
) -> None:
    """Stop video recording."""
    import asyncio

    if use_ble:
        asyncio.run(_dispatch_ble_shutter(start=False))
        console.print("[green]■ Shutter stopped over BLE[/green]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.shutter_stop()
    console.print("[green]■ Shutter stopped[/green]")


@record_app.command("photo")
def cmd_record_photo(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger shutter via BLE"),
    force: bool = typer.Option(False, "--force", help="Trigger even when the camera is not in Photo mode"),
) -> None:
    """Capture a photo (requires the camera to be in Photo mode)."""
    import asyncio

    if use_ble:
        if not force:
            console.print(
                "[yellow]BLE shutter triggers the camera's current mode. "
                "Ensure a Photo preset is selected; this cannot be verified over BLE.[/yellow]"
            )
        asyncio.run(_dispatch_ble_shutter(start=True))
        console.print("[green]📸 Shutter triggered over BLE[/green]")
        return

    _, client = resolve_camera(target_ip=ip)
    status = client.get_status()
    if status.current_mode.lower() != "photo" and not force:
        err_console.print(
            f"[bold red]Error:[/bold red] camera is in {status.current_mode} mode. "
            "Select a Photo preset first (see `uel-gopro preset list`) or pass --force."
        )
        raise typer.Exit(code=1)

    client.shutter_start()
    console.print("[green]📸 Photo captured[/green]")


# -----------------------------------------------------------------------------
# Presets
# -----------------------------------------------------------------------------

@preset_app.command("list")
def cmd_preset_list(
    ip: Optional[str] = typer.Option(None, "--ip"),
    as_json: bool = typer.Option(False, "--json", help="Output the raw API response as JSON"),
) -> None:
    """List presets configured on the camera."""
    _, client = resolve_camera(target_ip=ip)
    presets = client.get_presets()
    if as_json:
        typer.echo(json.dumps(presets, indent=2, default=str))
        return

    groups = presets.get("presetGroupArray") or []
    table = Table(title="GoPro Presets", border_style="cyan")
    table.add_column("Group / Name", style="bold white")
    table.add_column("Preset ID", justify="right", style="cyan")
    table.add_column("Type", style="dim")

    rows = 0
    for group in groups:
        group_name = str(group.get("id", "")).replace("PRESET_GROUP_ID_", "").replace("_", " ").title()
        for preset in group.get("presetArray") or group.get("presets") or []:
            title = (
                preset.get("customName")
                or preset.get("title")
                or preset.get("titleId")
                or f"Preset {preset.get('id', '-')}"
            )
            title = str(title).replace("PRESET_TITLE_", "").replace("_", " ").title()
            table.add_row(
                f"{group_name} / {title}" if group_name else title,
                str(preset.get("id", "-")),
                "User" if preset.get("userDefined") else "Factory",
            )
            rows += 1

    if rows:
        console.print(table)
    else:
        console.print("[yellow]The camera returned no presets.[/yellow]")


@preset_app.command("load")
def cmd_preset_load(
    preset_id: int = typer.Argument(..., help="Preset ID to activate"),
    ip: Optional[str] = typer.Option(None, "--ip"),
) -> None:
    """Load and activate a specific preset by ID."""
    _, client = resolve_camera(target_ip=ip)
    client.load_preset(preset_id)
    console.print(f"[green]✓ Loaded preset ID {preset_id}[/green]")


# -----------------------------------------------------------------------------
# Camera settings
# -----------------------------------------------------------------------------

# Modern OpenGoPro setting IDs. Older cameras may use different IDs for
# field-of-view and bitrate; pass a numeric ID to override.
SETTING_ALIASES = {
    "resolution": 2,
    "res": 2,
    "fps": 3,
    "framerate": 3,
    "fov": 121,
    "lens": 121,
    "bitrate": 182,
}


def _get_settings(ip: Optional[str]) -> dict:
    _, client = resolve_camera(target_ip=ip)
    raw = client.get_raw_state()
    return raw.get("settings", {}) or {}


def _render_settings(settings: dict, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(settings, indent=2, default=str))
        return
    table = Table(title="GoPro Active Settings", border_style="cyan")
    table.add_column("Setting ID", style="cyan")
    table.add_column("Value", style="bold white")
    for key, value in settings.items():
        table.add_row(str(key), str(value))
    console.print(table)


@config_app.command("list")
def cmd_config_list(
    ip: Optional[str] = typer.Option(None, "--ip"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all active camera settings."""
    _render_settings(_get_settings(ip), as_json)


@config_app.command("get")
def cmd_config_get(
    setting: Optional[str] = typer.Argument(None, help="Optional setting name or numeric ID"),
    ip: Optional[str] = typer.Option(None, "--ip"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Get camera settings, or one setting by alias/ID."""
    settings = _get_settings(ip)
    if not setting:
        _render_settings(settings, as_json)
        return

    setting_id = str(SETTING_ALIASES.get(setting.lower(), setting))
    value = settings.get(setting_id)
    if value is None:
        err_console.print(f"[yellow]Setting {setting} (ID {setting_id}) not found or not active.[/yellow]")
        return
    if as_json:
        typer.echo(json.dumps({setting_id: value}, indent=2, default=str))
    else:
        console.print(f"[cyan]{setting}[/cyan] = [bold white]{value}[/bold white]")


@config_app.command("set")
def cmd_config_set(
    setting: str = typer.Argument(..., help="Setting name (resolution, fps, fov, bitrate) or numeric ID"),
    value: int = typer.Argument(..., help="Value integer code"),
    ip: Optional[str] = typer.Option(None, "--ip"),
) -> None:
    """Set a camera setting value."""
    setting_id = SETTING_ALIASES.get(setting.lower())
    if setting_id is None:
        try:
            setting_id = int(setting)
        except ValueError:
            err_console.print(
                f"[bold red]Unknown setting:[/bold red] '{setting}'. "
                f"Valid aliases: {', '.join(SETTING_ALIASES)}"
            )
            raise typer.Exit(code=1)

    _, client = resolve_camera(target_ip=ip)
    client.set_setting(setting_id, value)
    console.print(f"[green]✓ Set setting {setting} ({setting_id}) -> {value}[/green]")


# -----------------------------------------------------------------------------
# Streaming & webcam
# -----------------------------------------------------------------------------

@stream_app.command("preview")
def cmd_stream_preview(
    ip: Optional[str] = typer.Option(None, "--ip"),
    player: Optional[str] = typer.Option(None, "--player", "-p", help="Player to launch (mpv or ffplay)"),
    no_player: bool = typer.Option(False, "--no-player", help="Start the stream without launching a player"),
) -> None:
    """Start the low-latency preview stream and optionally launch a player."""
    from uel_gopro.stream.preview import launch_preview_stream

    _, client = resolve_camera(target_ip=ip)
    console.print("[cyan]Starting camera preview stream...[/cyan]")
    proc = launch_preview_stream(client, player=player, spawn_player=not no_player)
    if proc:
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            raise
        finally:
            try:
                client.stop_preview_stream()
            except Exception:
                logger.debug("Could not stop the preview stream", exc_info=True)


@stream_app.command("webcam")
def cmd_stream_webcam(
    action: str = typer.Argument("start", help="Action: 'start' or 'stop'"),
    resolution: str = typer.Option("1080p", "--res", "-r", help="Resolution: 1080p, 720p, or 480p"),
    fov: str = typer.Option("wide", "--fov", help="Field of view: wide, linear, narrow, or superview"),
    ip: Optional[str] = typer.Option(None, "--ip"),
) -> None:
    """Toggle USB webcam mode on the GoPro."""
    from uel_gopro.stream.webcam import start_webcam, stop_webcam

    _, client = resolve_camera(target_ip=ip)
    if action.lower() == "start":
        start_webcam(client, resolution=resolution, fov=fov)
        console.print(f"[green]GoPro USB webcam started at {resolution} ({fov}).[/green]")
    elif action.lower() == "stop":
        stop_webcam(client)
        console.print("[yellow]GoPro USB webcam stopped.[/yellow]")
    else:
        err_console.print(f"[red]Unknown action: {action}. Use 'start' or 'stop'.[/red]")
        raise typer.Exit(code=1)


# -----------------------------------------------------------------------------
# Media
# -----------------------------------------------------------------------------

def _destination_directory(destination: Path) -> Path:
    if destination.exists() and destination.is_file():
        return destination.parent
    if not destination.exists() and destination.suffix:
        return destination.parent
    return destination


def _safe_media_filename(filename: str) -> str:
    name = Path(filename).name
    if name in ("", ".", ".."):
        raise MediaError(f"Refusing unsafe media filename: {filename!r}")
    return name


def _destination_file(destination: Path, filename: str) -> Path:
    if destination.exists():
        return destination / filename if destination.is_dir() else destination
    if destination.suffix:
        return destination
    destination.mkdir(parents=True, exist_ok=True)
    return destination / filename


@media_app.command("list")
def cmd_media_list(
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all media stored on the camera SD card."""
    items = []
    mtp_detected = False
    try:
        _, client = resolve_camera(target_ip=ip)
        items = client.get_media_list()
    except CameraNotFoundError:
        mtp_error: Optional[Exception] = None
        if not ip:
            try:
                from uel_gopro.transport.mtp import MtpClient, is_mtp_available

                if is_mtp_available():
                    with MtpClient() as mtp:
                        if mtp.detect_camera(timeout_sec=2.5):
                            mtp_detected = True
                            console.print("[cyan]Querying media list via USB MTP mode...[/cyan]")
                            items = mtp.list_media()
            except Exception as exc:
                mtp_error = exc
                logger.debug(f"MTP list fallback failed: {exc}")
        if mtp_error is not None:
            raise MediaError(f"MTP media listing failed: {mtp_error}") from mtp_error
        if not mtp_detected and not items:
            raise

    if as_json:
        typer.echo(json.dumps([item.model_dump() for item in items], indent=2, default=str))
        return

    table = Table(title="GoPro SD Card Media", border_style="cyan")
    table.add_column("Directory", style="dim")
    table.add_column("Filename", style="bold white", no_wrap=True)
    table.add_column("Type", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Base ID", style="magenta")
    table.add_column("Chapter", justify="right")
    table.add_column("Modified", style="dim")

    for item in items:
        size_mb = item.size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
        modified = (
            datetime.fromtimestamp(item.mod_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            if item.mod_time
            else "Unknown"
        )
        chapter = str(item.chapter_num) if item.is_chapter or item.chapter_num > 1 else "-"
        table.add_row(
            item.directory,
            item.filename,
            item.media_type.value.upper(),
            size_str,
            item.base_id or "-",
            chapter,
            modified,
        )
    console.print(table)


@media_app.command("download")
def cmd_media_download(
    filename: str = typer.Argument(..., help="Filename on camera to download"),
    destination: Path = typer.Option(Path("."), "--dest", "-d", help="Destination folder or file path"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
) -> None:
    """Download a file from the camera with resume and size verification."""
    try:
        info, client = resolve_camera(target_ip=ip)
        items = client.get_media_list()
    except CameraNotFoundError:
        mtp_error: Optional[Exception] = None
        if not ip:
            try:
                from uel_gopro.transport.mtp import MtpClient, is_mtp_available

                if is_mtp_available():
                    with MtpClient() as mtp:
                        if mtp.detect_camera(timeout_sec=2.5):
                            console.print(f"[cyan]Downloading {filename} via USB MTP mode...[/cyan]")
                            dest_dir = _destination_directory(destination)
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            out = mtp.download_file(filename=filename, dest_dir=dest_dir)
                            console.print(f"[bold green]✓ Download complete via MTP:[/bold green] {out}")
                            return
            except Exception as exc:
                mtp_error = exc
                logger.debug(f"MTP download fallback failed: {exc}")
        if mtp_error is not None:
            raise MediaError(f"MTP download failed: {mtp_error}") from mtp_error
        raise

    matching = [item for item in items if item.filename.lower() == filename.lower()]
    if not matching:
        err_console.print(f"[bold red]Error:[/bold red] File '{filename}' not found on camera.")
        raise typer.Exit(code=1)

    item = matching[0]
    dest_path = _destination_file(destination, _safe_media_filename(item.filename))
    url = f"http://{info.ip_address}:{info.port}{item.download_url_path}"

    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task(f"Downloading {item.filename}", total=item.size_bytes or None)

        def on_progress(downloaded: int, total: int) -> None:
            if total > 0:
                progress.update(task_id, completed=downloaded, total=total)
            else:
                progress.update(task_id, completed=downloaded)

        completed_path = download_file(url, dest_path, progress_callback=on_progress)

    if item.mod_time:
        sync_file_time(completed_path, timestamp=item.mod_time)
    console.print(f"[green]✓ Download complete:[/green] {completed_path}")


@media_app.command("delete")
def cmd_media_delete(
    filename: str = typer.Argument(..., help="Filename on camera to delete"),
    directory: str = typer.Option("100GOPRO", "--dir", help="Directory name on SD card"),
    force: bool = typer.Option(False, "--force", "-f", help="Force deletion without confirmation"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
) -> None:
    """Delete a file from the camera SD card."""
    if not force:
        if not typer.confirm(f"Permanently delete {directory}/{filename} from the camera?"):
            console.print("[yellow]Aborted.[/yellow]")
            return

    _, client = resolve_camera(target_ip=ip)
    client.delete_file(directory=directory, filename=filename)
    console.print(f"[green]✓ Deleted {directory}/{filename} from camera.[/green]")


# -----------------------------------------------------------------------------
# Local processing
# -----------------------------------------------------------------------------

@process_app.command("stitch")
def cmd_process_stitch(
    input_files: List[Path] = typer.Argument(..., help="Chapter video files or a directory to stitch"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    ffmpeg: str = typer.Option("ffmpeg", "--ffmpeg", help="Path to the FFmpeg binary"),
) -> None:
    """Losslessly stitch GoPro chapters, preserving all tracks and telemetry."""
    expanded_files: List[Path] = []
    for path in input_files:
        if path.is_dir():
            expanded_files.extend(path.glob("*.MP4"))
            expanded_files.extend(path.glob("*.mp4"))
        elif path.is_file():
            expanded_files.append(path)
        else:
            err_console.print(f"[bold red]Error:[/bold red] Path not found: {path}")
            raise typer.Exit(code=1)

    if not expanded_files:
        err_console.print("[bold red]Error:[/bold red] No video files found to stitch.")
        raise typer.Exit(code=1)

    grouped = detect_chapters(expanded_files)
    if not grouped:
        err_console.print("[bold red]Error:[/bold red] No GoPro chapters detected in the provided files.")
        raise typer.Exit(code=1)

    if output is not None and len(grouped) > 1:
        err_console.print(
            "[bold red]Error:[/bold red] --output can only be used with a single chapter group. "
            "Omit --output to create one STITCH_<base>.mp4 per group."
        )
        raise typer.Exit(code=1)

    for base_id, chapters in grouped.items():
        if len(chapters) <= 1 and output is None:
            console.print(f"[dim]Skipping base {base_id} (only one chapter: {chapters[0].name})[/dim]")
            continue

        out_path = output if output else chapters[0].parent / f"STITCH_{base_id}.mp4"
        source_time = extract_creation_time(chapters[0])
        console.print(f"[cyan]Stitching base {base_id} ({len(chapters)} chapters) -> {out_path.name}...[/cyan]")
        stitched = stitch_chapters(chapters, out_path, ffmpeg_path=ffmpeg)
        if source_time and sync_file_time(stitched, timestamp=source_time):
            console.print(f"[dim]Restored timestamp: {source_time.isoformat()}[/dim]")
        else:
            console.print("[yellow]Warning: could not restore the original capture timestamp.[/yellow]")
        console.print(f"[bold green]✓ Stitched successfully:[/bold green] {stitched}")


@process_app.command("sync-dates")
def cmd_process_sync_dates(
    files: List[Path] = typer.Argument(..., help="Media files to timestamp from MP4 metadata"),
) -> None:
    """Synchronize filesystem modification times with MP4 container creation time."""
    for path in files:
        if not path.is_file():
            err_console.print(f"[dim]Skipping {path} (not a file)[/dim]")
            continue
        created = extract_creation_time(path)
        if created and sync_file_time(path, timestamp=created):
            console.print(f"[green]✓ Synced {path.name}:[/green] {created.isoformat()}")
        else:
            err_console.print(f"[yellow]⚠ Could not determine a creation timestamp for {path.name}[/yellow]")


# -----------------------------------------------------------------------------
# GoPro Labs QR
# -----------------------------------------------------------------------------

@labs_app.command("qr")
def cmd_labs_qr(
    code: str = typer.Argument(..., help="Labs code or preset name (bitrate_max, motion_detect, ...)"),
    invert: bool = typer.Option(False, "--invert", "-i", help="Render white modules on a black background"),
    save: Optional[Path] = typer.Option(None, "--save", "-s", help="Save the QR code to PNG/SVG"),
) -> None:
    """Generate and display a GoPro Labs QR code in the terminal."""
    from uel_gopro.labs.qr import PRESETS, render_terminal_qr, resolve_code, save_qr_image

    resolved = resolve_code(code)
    console.print(f"[bold cyan]GoPro Labs QR Code:[/bold cyan] [yellow]{resolved}[/yellow]")
    if code in PRESETS:
        console.print(f"[dim]Preset alias: {code}[/dim]")

    console.print(render_terminal_qr(code, invert=invert))
    if save:
        out_path = save_qr_image(code, save)
        console.print(f"[green]✓ Saved QR code to {out_path}[/green]")


@labs_app.command("presets")
def cmd_labs_presets() -> None:
    """List all built-in GoPro Labs QR presets."""
    from uel_gopro.labs.qr import PRESETS

    table = Table(title="GoPro Labs Macro Presets", border_style="cyan")
    table.add_column("Preset Name", style="bold cyan")
    table.add_column("GoPro Labs Command", style="yellow")
    for name, command in PRESETS.items():
        table.add_row(name, command)
    console.print(table)


# -----------------------------------------------------------------------------
# Telemetry
# -----------------------------------------------------------------------------

@telemetry_app.command("export")
def cmd_telemetry_export(
    input_file: Path = typer.Argument(..., help="GoPro MP4 or raw GPMF file"),
    format: str = typer.Option("gpx", "--format", "-f", help="Export format: gpx, kml, geojson, csv"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
) -> None:
    """Extract GPS telemetry from a GoPro MP4 and export it."""
    from uel_gopro.telemetry.exporters import export_csv, export_geojson, export_gpx, export_kml
    from uel_gopro.telemetry.gpmf import extract_gpmf_from_mp4, parse_gpmf_stream

    if not input_file.is_file():
        err_console.print(f"[bold red]Error:[/bold red] Input file not found: {input_file}")
        raise typer.Exit(code=1)

    fmt = format.lower()
    extensions = {"gpx": ".gpx", "kml": ".kml", "geojson": ".geojson", "csv": ".csv"}
    if fmt not in extensions:
        err_console.print(
            f"[bold red]Error:[/bold red] Unsupported format: {fmt}. Use gpx, kml, geojson, or csv."
        )
        raise typer.Exit(code=1)

    console.print(f"[cyan]Extracting GPMF telemetry from {input_file.name}...[/cyan]")
    track = parse_gpmf_stream(extract_gpmf_from_mp4(input_file))

    if not track.gps_points:
        console.print("[yellow]Warning: no GPS points found in the telemetry stream.[/yellow]")

    out_path = output if output else input_file.with_suffix(extensions[fmt])
    exporters = {"gpx": export_gpx, "kml": export_kml, "geojson": export_geojson, "csv": export_csv}
    exporters[fmt](track, out_path)
    console.print(f"[bold green]✓ Exported {len(track.gps_points)} telemetry points to {out_path}[/bold green]")


# -----------------------------------------------------------------------------
# GoPro Plus cloud
# -----------------------------------------------------------------------------

@cloud_app.command("auth")
def cmd_cloud_auth(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GoPro Plus bearer token"),
    user_id: Optional[str] = typer.Option("", "--user-id", "-u", help="GoPro Plus user ID"),
) -> None:
    """Store GoPro Plus credentials in ``~/.config/uel-gopro/cloud.json``."""
    from uel_gopro.cloud.client import save_cloud_auth

    auth_token = token
    if not auth_token:
        auth_token = typer.prompt("Enter your GoPro Plus bearer token", hide_input=True)
    path = save_cloud_auth(token=auth_token, user_id=user_id or "")
    console.print(f"[bold green]✓ GoPro Plus credentials saved to {path}[/bold green]")


@cloud_app.command("list")
def cmd_cloud_list(
    page: int = typer.Option(1, "--page", "-p", help="Page number (1-based)"),
    per_page: int = typer.Option(25, "--per-page", "-n", help="Items per page"),
    as_json: bool = typer.Option(False, "--json", help="Output as raw JSON"),
) -> None:
    """List media assets in the GoPro Plus cloud library."""
    from uel_gopro.cloud.client import GoProCloudClient

    items = GoProCloudClient().list_media(page=page, per_page=per_page)
    if as_json:
        typer.echo(json.dumps(items, indent=2, default=str))
        return

    table = Table(title=f"GoPro Plus Cloud Library (Page {page})", border_style="cyan")
    table.add_column("Asset ID", style="dim")
    table.add_column("Filename", style="bold white")
    table.add_column("Type", style="cyan")
    table.add_column("Captured At", style="yellow")
    table.add_column("Size (MB)", justify="right")

    for item in items:
        try:
            size_mb = int(item.get("file_size") or 0) / (1024 * 1024)
        except (TypeError, ValueError):
            size_mb = 0
        table.add_row(
            str(item.get("id", "-")),
            str(item.get("filename", "Unknown")),
            str(item.get("type", "video")).upper(),
            str(item.get("captured_at", "-")),
            f"{size_mb:.1f}" if size_mb > 0 else "-",
        )
    console.print(table)


@cloud_app.command("sync")
def cmd_cloud_sync(
    dest: Path = typer.Option(Path("./gopro_cloud_backup"), "--dest", "-d", help="Backup destination"),
    max_pages: int = typer.Option(100, "--max-pages", help="Maximum pages to scan"),
) -> None:
    """Mirror GoPro Plus cloud media to local storage."""
    from uel_gopro.cloud.client import GoProCloudClient

    client = GoProCloudClient()
    console.print(f"[cyan]Syncing GoPro Plus cloud media to {dest}...[/cyan]")
    with console.status("[cyan]Downloading cloud assets...[/cyan]"):
        downloaded = client.sync_all(dest_dir=dest, max_pages=max_pages)
    console.print(f"[bold green]✓ Cloud sync finished. {len(downloaded)} assets available locally.[/bold green]")


def main() -> None:
    """Console-script entry point with clean user-facing error handling."""
    try:
        app()
    except UelError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        err_console.print("\n[yellow]Aborted.[/yellow]")
        raise SystemExit(130) from None
    except OSError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
