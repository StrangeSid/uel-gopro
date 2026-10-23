from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sys
from pathlib import Path
from typing import Optional, List
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
from uel_gopro.core.exceptions import UelError
from uel_gopro.core.models import TransportType
from uel_gopro.media.downloader import download_file
from uel_gopro.media.exif import extract_creation_time, sync_file_time
from uel_gopro.media.stitcher import detect_chapters, stitch_chapters
from uel_gopro.transport.manager import resolve_camera
from uel_gopro.transport.usb import detect_usb_camera

console = Console()
err_console = Console(stderr=True)

app = typer.Typer(
    name="uel-gopro",
    help="UEL-GoPro: Unofficial Extended Life GoPro CLI Toolchain.\nLocal-first, open-source control.",
    add_completion=False,
)

# Sub-command groups
record_app = typer.Typer(name="record", help="Camera shutter & recording commands")
config_app = typer.Typer(name="config", help="Camera setting mutation commands")
preset_app = typer.Typer(name="preset", help="Camera preset selection")
media_app = typer.Typer(name="media", help="On-camera SD card media management")
process_app = typer.Typer(name="process", help="Local media post-processing (chapter stitch, EXIF)")
telemetry_app = typer.Typer(name="telemetry", help="GPMF telemetry parsing and export")
stream_app = typer.Typer(name="stream", help="Live preview streaming and USB webcam")
labs_app = typer.Typer(name="labs", help="GoPro Labs QR code generator")
cloud_app = typer.Typer(name="cloud", help="GoPro Plus Cloud subscription sync & backup")

app.add_typer(record_app)
app.add_typer(config_app)
app.add_typer(preset_app)
app.add_typer(media_app)
app.add_typer(process_app)
app.add_typer(telemetry_app)
app.add_typer(stream_app)
app.add_typer(labs_app)
app.add_typer(cloud_app)


def version_callback(value: bool):
    if value:
        console.print(f"[bold cyan]uel-gopro[/bold cyan] version [green]{__version__}[/green]")
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True, help="Show version and exit"
    ),
    verbose: bool = typer.Option(False, "--verbose", help="Enable verbose debug logging"),
):
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


# -----------------------------------------------------------------------------
# Discover & Status Commands
# -----------------------------------------------------------------------------

@app.command("discover")
def cmd_discover(
    scan_ble: bool = typer.Option(False, "--ble", "-b", help="Scan for nearby Bluetooth Low Energy (BLE) GoPro cameras"),
    json_output: bool = typer.Option(False, "--json", help="Output results in JSON format"),
    timeout: float = typer.Option(2.0, "--timeout", "-t", help="Scan timeout in seconds"),
):
    """Scan local network adapters (USB CDC-ECM) and BLE for GoPro cameras."""
    import asyncio
    from uel_gopro.transport.ble import GoProBleClient

    cam = detect_usb_camera(timeout_sec=timeout)
    ble_devices = []
    if scan_ble:
        console.print("[cyan]Scanning for GoPro BLE devices...[/cyan]")
        ble_devices = asyncio.run(GoProBleClient.scan(timeout=timeout))

    if json_output:
        results = []
        if cam:
            results.append(cam.model_dump())
        for d in ble_devices:
            results.append({
                "model_name": getattr(d, "name", "GoPro BLE"),
                "address": getattr(d, "address", ""),
                "transport": "ble",
            })
        typer.echo(json.dumps(results, indent=2))
        return

    table = Table(title="Discovered GoPro Devices", show_header=True, header_style="bold magenta")
    table.add_column("Interface / Address", style="cyan")
    table.add_column("Location / IP", style="green")
    table.add_column("Port / Channel", style="yellow")
    table.add_column("Transport", style="blue")

    found_any = False
    if cam:
        table.add_row(cam.interface_name or "usb", cam.ip_address, str(cam.port), cam.transport.value.upper())
        found_any = True

    for d in ble_devices:
        name = getattr(d, "name", "GoPro")
        addr = getattr(d, "address", "Unknown")
        table.add_row(addr, name, "BLE", "BLUETOOTH")
        found_any = True

    if found_any:
        console.print(table)
    else:
        console.print("[yellow]No GoPro cameras found.[/yellow]")
        console.print("[dim]Hint: For USB, connect via USB-C in 'GoPro Connect' mode. For BLE, pass --ble and put camera in pairing mode.[/dim]")


@app.command("status")
def cmd_status(
    ip: Optional[str] = typer.Option(None, "--ip", help="Manual camera IP"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Connect and query camera state over BLE"),
    json_output: bool = typer.Option(False, "--json", help="Output status in JSON format"),
):
    """Display real-time camera state: battery, SD space, mode, and temperature."""
    import asyncio
    from uel_gopro.transport.ble import GoProBleClient

    if use_ble:
        console.print("[cyan]Connecting to GoPro over Bluetooth Low Energy...[/cyan]")

        async def _query_ble():
            devices = await GoProBleClient.scan(timeout=3.0)
            if not devices:
                raise UelError("No GoPro cameras discovered over BLE. Ensure camera is awake / in pairing mode.")
            target = devices[0]
            client = GoProBleClient(address=target.address)
            await client.connect()
            bat = await client.get_battery_level()
            info = await client.get_device_info()
            await client.disconnect()
            return target, bat, info

        try:
            target, bat, dev_info = asyncio.run(_query_ble())
        except Exception as exc:
            err_console.print(f"[bold red]BLE Error:[/bold red] {exc}")
            raise typer.Exit(code=1)

        if json_output:
            typer.echo(json.dumps({
                "transport": "ble",
                "device_name": getattr(target, "name", "GoPro"),
                "address": target.address,
                "battery_percent": bat,
                **dev_info,
            }, indent=2))
            return

        bat_str = f"{bat}%"
        if bat < 20:
            bat_str = f"[bold red]{bat_str}[/bold red]"
        else:
            bat_str = f"[bold green]{bat_str}[/bold green]"

        panel_text = (
            f"[bold cyan]Camera:[/bold cyan]       {getattr(target, 'name', 'GoPro')} ({dev_info.get('manufacturer', 'GoPro')})\n"
            f"[bold cyan]Address:[/bold cyan]      {target.address} (BLE)\n"
            f"[bold cyan]Battery:[/bold cyan]      {bat_str}\n"
            f"[bold cyan]Firmware:[/bold cyan]     {dev_info.get('firmware', 'Unknown')}\n"
            f"[bold cyan]Serial:[/bold cyan]       {dev_info.get('serial', 'Unknown')}"
        )
        console.print(Panel(panel_text, title="[bold]GoPro Real-Time BLE Dashboard[/bold]", border_style="cyan"))
        return

    try:
        info, client = resolve_camera(target_ip=ip)
        status = client.get_status()
    except UelError as exc:
        err_console.print(f"[bold red]Error:[/bold red] {exc}")
        raise typer.Exit(code=1)

    if json_output:
        typer.echo(status.model_dump_json(indent=2))
        return

    # Render pretty dashboard panel
    bat_str = f"{status.battery_percent}%" if status.battery_percent is not None else "Unknown"
    if status.is_charging:
        bat_str += " ⚡ [green](Charging)[/green]"
    elif status.battery_percent and status.battery_percent < 20:
        bat_str = f"[bold red]{bat_str}[/bold red]"

    rec_str = "[bold red]● RECORDING[/bold red]" if status.is_recording else "[dim]Standby[/dim]"
    sd_mb = f"{status.sd_remaining_mb:,} MB" if status.sd_remaining_mb is not None else "Unknown"

    panel_text = (
        f"[bold cyan]Camera Link:[/bold cyan] {info.ip_address}:{info.port} ({info.transport.value.upper()})\n"
        f"[bold cyan]Battery:[/bold cyan]     {bat_str}\n"
        f"[bold cyan]State:[/bold cyan]       {rec_str}\n"
        f"[bold cyan]Mode:[/bold cyan]        {status.current_mode}\n"
        f"[bold cyan]SD Card:[/bold cyan]     {status.sd_status} (Free: {sd_mb})\n"
        f"[bold cyan]Thermals:[/bold cyan]    {'[bold red]OVERHEAT WARNING[/bold red]' if status.system_hot else '[green]Nominal[/green]'}"
    )
    console.print(Panel(panel_text, title="[bold]GoPro Status Dashboard[/bold]", border_style="cyan"))


# -----------------------------------------------------------------------------
# Record Commands
# -----------------------------------------------------------------------------

async def _dispatch_ble_shutter(start: bool):
    from uel_gopro.transport.ble import GoProBleClient
    devices = await GoProBleClient.scan(timeout=3.0)
    if not devices:
        raise UelError("No GoPro cameras discovered over BLE.")
    client = GoProBleClient(address=devices[0].address)
    await client.connect()
    if start:
        await client.shutter_start()
    else:
        await client.shutter_stop()
    await client.disconnect()


@record_app.command("start")
def cmd_record_start(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger shutter via Bluetooth Low Energy"),
):
    """Start video recording or timelapse."""
    import asyncio
    if use_ble:
        asyncio.run(_dispatch_ble_shutter(start=True))
        console.print("[bold red]● Shutter Started over BLE (Recording)[/bold red]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.shutter_start()
    console.print("[bold red]● Shutter Started (Recording)[/bold red]")


@record_app.command("stop")
def cmd_record_stop(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger shutter via Bluetooth Low Energy"),
):
    """Stop video recording."""
    import asyncio
    if use_ble:
        asyncio.run(_dispatch_ble_shutter(start=False))
        console.print("[green]■ Shutter Stopped over BLE[/green]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.shutter_stop()
    console.print("[green]■ Shutter Stopped[/green]")


@record_app.command("photo")
def cmd_record_photo(
    ip: Optional[str] = typer.Option(None, "--ip"),
    use_ble: bool = typer.Option(False, "--ble", "-b", help="Trigger photo capture via Bluetooth Low Energy"),
):
    """Trigger photo capture."""
    import asyncio
    if use_ble:
        asyncio.run(_dispatch_ble_shutter(start=True))
        console.print("[green]📸 Photo captured over BLE[/green]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.shutter_start()
    console.print("[green]📸 Photo captured[/green]")


# -----------------------------------------------------------------------------
# Preset Commands
# -----------------------------------------------------------------------------

@preset_app.command("list")
def cmd_preset_list(
    ip: Optional[str] = typer.Option(None, "--ip"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List presets configured on camera."""
    _, client = resolve_camera(target_ip=ip)
    presets = client.get_presets()
    if as_json:
        console.print(json.dumps(presets, indent=2))
        return

    table = Table(title="GoPro Presets", border_style="cyan")
    table.add_column("Group / Name", style="bold white")
    table.add_column("Preset ID", justify="right", style="cyan")
    table.add_column("Type", style="dim")

    for grp in presets.get("presetGroupArray", []):
        for p in grp.get("presets", []):
            table.add_row(
                p.get("title", "Unknown"),
                str(p.get("id", "-")),
                "User" if p.get("userDefined") else "Factory",
            )
    console.print(table)


@preset_app.command("load")
def cmd_preset_load(
    preset_id: int = typer.Argument(..., help="Preset ID to activate"),
    ip: Optional[str] = typer.Option(None, "--ip"),
):
    """Load and activate a specific preset by ID."""
    _, client = resolve_camera(target_ip=ip)
    client.load_preset(preset_id)
    console.print(f"[green]✓ Loaded preset ID {preset_id}[/green]")


# -----------------------------------------------------------------------------
# Config Commands
# -----------------------------------------------------------------------------

SETTING_ALIASES = {
    "resolution": 2,
    "res": 2,
    "fps": 3,
    "framerate": 3,
    "fov": 4,
    "lens": 4,
    "bitrate": 102,
}

@config_app.command("set")
def cmd_config_set(
    setting: str = typer.Argument(..., help="Setting name (e.g. resolution, fps, fov, bitrate) or numeric ID"),
    value: int = typer.Argument(..., help="Value integer code"),
    ip: Optional[str] = typer.Option(None, "--ip"),
):
    """Set a camera setting value."""
    _, client = resolve_camera(target_ip=ip)
    setting_id = SETTING_ALIASES.get(setting.lower(), None)
    if setting_id is None:
        try:
            setting_id = int(setting)
        except ValueError:
            err_console.print(f"[bold red]Unknown setting:[/bold red] '{setting}'. Valid aliases: {list(SETTING_ALIASES.keys())}")
            raise typer.Exit(code=1)

    client.set_setting(setting_id, value)
    console.print(f"[green]✓ Set setting {setting} ({setting_id}) -> {value}[/green]")


@config_app.command("get")
def cmd_config_get(
    setting: Optional[str] = typer.Argument(None, help="Optional setting name or numeric ID"),
    ip: Optional[str] = typer.Option(None, "--ip"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Get camera settings."""
    _, client = resolve_camera(target_ip=ip)
    raw = client.get_raw_state()
    settings_dict = raw.get("settings", {})

    if setting:
        setting_id = str(SETTING_ALIASES.get(setting.lower(), setting))
        val = settings_dict.get(setting_id)
        if val is None:
            err_console.print(f"[yellow]Setting {setting} (ID {setting_id}) not found or not active.[/yellow]")
            return
        console.print(f"[cyan]{setting}[/cyan] = [bold white]{val}[/bold white]")
        return

    if as_json:
        console.print(json.dumps(settings_dict, indent=2))
        return

    table = Table(title="GoPro Active Settings", border_style="cyan")
    table.add_column("Setting ID", style="cyan")
    table.add_column("Value", style="bold white")
    for k, v in settings_dict.items():
        table.add_row(str(k), str(v))
    console.print(table)


# -----------------------------------------------------------------------------
# Streaming & Webcam Commands
# -----------------------------------------------------------------------------

@stream_app.command("preview")
def cmd_stream_preview(
    ip: Optional[str] = typer.Option(None, "--ip"),
    player: Optional[str] = typer.Option(None, "--player", "-p", help="Player to launch (mpv or ffplay)"),
):
    """Launch low-latency live preview stream."""
    from uel_gopro.stream.preview import launch_preview_stream

    _, client = resolve_camera(target_ip=ip)
    console.print("[cyan]Starting camera preview stream...[/cyan]")
    proc = launch_preview_stream(client, player=player)
    if proc:
        proc.wait()


@stream_app.command("webcam")
def cmd_stream_webcam(
    action: str = typer.Argument("start", help="Action: 'start' or 'stop'"),
    resolution: str = typer.Option("1080p", "--res", "-r", help="Resolution: 1080p or 720p"),
    ip: Optional[str] = typer.Option(None, "--ip"),
):
    """Toggle USB webcam mode on the GoPro."""
    from uel_gopro.stream.webcam import start_webcam, stop_webcam

    _, client = resolve_camera(target_ip=ip)
    if action.lower() == "start":
        start_webcam(client, resolution=resolution)
        console.print(f"[green]GoPro USB webcam started at {resolution}.[/green]")
    elif action.lower() == "stop":
        stop_webcam(client)
        console.print("[yellow]GoPro USB webcam stopped.[/yellow]")
    else:
        err_console.print(f"[red]Unknown action: {action}. Use 'start' or 'stop'.[/red]")
        raise typer.Exit(code=1)



# -----------------------------------------------------------------------------
# Media Commands
# -----------------------------------------------------------------------------

@media_app.command("list")
def cmd_media_list(
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """List all media stored on camera SD card."""
    _, client = resolve_camera(target_ip=ip)
    items = client.get_media_list()
    if as_json:
        console.print(json.dumps([item.model_dump() for item in items], indent=2))
        return

    table = Table(title="GoPro SD Card Media Listing", border_style="cyan")
    table.add_column("Directory", style="dim")
    table.add_column("Filename", style="bold white", no_wrap=True)
    table.add_column("Type", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Base ID", style="magenta")
    table.add_column("Chapter", justify="right")
    table.add_column("Modified", style="dim")

    for it in items:
        mb = it.size_bytes / (1024 * 1024)
        size_str = f"{mb:.1f} MB" if mb < 1024 else f"{mb / 1024:.2f} GB"
        mod_str = (
            str(datetime.fromtimestamp(it.mod_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M"))
            if it.mod_time
            else "Unknown"
        )
        chap_str = str(it.chapter_num) if it.is_chapter or it.chapter_num > 1 else "-"
        table.add_row(
            it.directory,
            it.filename,
            it.media_type.value.upper(),
            size_str,
            it.base_id or "-",
            chap_str,
            mod_str,
        )

    console.print(table)


@media_app.command("download")
def cmd_media_download(
    filename: str = typer.Argument(..., help="Filename on camera to download"),
    destination: Path = typer.Option(Path("."), "--dest", "-d", help="Destination folder or file path"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
):
    """Download a file from camera SD card with resume and size verification."""
    info, client = resolve_camera(target_ip=ip)
    items = client.get_media_list()
    matching = [it for it in items if it.filename.lower() == filename.lower()]
    if not matching:
        err_console.print(f"[bold red]Error:[/bold red] File '{filename}' not found on camera.")
        raise typer.Exit(code=1)

    item = matching[0]
    dest_path = destination / item.filename if destination.is_dir() else destination
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

        def on_progress(downloaded: int, total: int):
            if total > 0:
                progress.update(task_id, completed=downloaded, total=total)
            else:
                progress.update(task_id, completed=downloaded)

        completed_path = download_file(
            url,
            dest_path,
            progress_callback=on_progress,
        )

    if item.mod_time:
        sync_file_time(completed_path, timestamp=item.mod_time)

    console.print(f"[green]✓ Download complete:[/green] {completed_path}")


@media_app.command("delete")
def cmd_media_delete(
    filename: str = typer.Argument(..., help="Filename on camera to delete"),
    directory: str = typer.Option("100GOPRO", "--dir", help="Directory name on SD card"),
    force: bool = typer.Option(False, "--force", "-f", help="Force deletion without interactive confirmation"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
):
    """Delete a file from the camera SD card."""
    if not force:
        confirm = typer.confirm(f"Are you sure you want to permanently delete {directory}/{filename} from camera?")
        if not confirm:
            console.print("[yellow]Aborted.[/yellow]")
            return

    _, client = resolve_camera(target_ip=ip)
    client.delete_file(directory=directory, filename=filename)
    console.print(f"[green]✓ Deleted {directory}/{filename} from camera.[/green]")


@media_app.command("format")
def cmd_media_format(
    confirm: bool = typer.Option(False, "--confirm", help="Must be passed to confirm formatting the SD card"),
    ip: Optional[str] = typer.Option(None, "--ip", help="Target camera IP"),
):
    """Format the camera SD card. WARNING: Irreversibly deletes all media!"""
    if not confirm:
        err_console.print("[bold red]Safety Check:[/bold red] You must supply --confirm to format the SD card.")
        raise typer.Exit(code=1)

    double_check = typer.confirm("DANGER: This will erase the ENTIRE SD card. Do you really want to proceed?")
    if not double_check:
        console.print("[yellow]Aborted.[/yellow]")
        return

    _, client = resolve_camera(target_ip=ip)
    client.format_sd_card()
    console.print("[bold green]✓ Camera SD card format requested.[/bold green]")


# -----------------------------------------------------------------------------
# Process Commands (Stitch & EXIF)
# -----------------------------------------------------------------------------

@process_app.command("stitch")
def cmd_process_stitch(
    input_files: List[Path] = typer.Argument(..., help="Chapter video files or directory to stitch"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
    ffmpeg: str = typer.Option("ffmpeg", "--ffmpeg", help="Path to FFmpeg binary"),
):
    """Losslessly stitch GoPro video chapters preserving all streams and telemetry."""
    expanded_files: List[Path] = []
    for f in input_files:
        if f.is_dir():
            expanded_files.extend(list(f.glob("*.MP4")) + list(f.glob("*.mp4")))
        elif f.is_file():
            expanded_files.append(f)
        else:
            err_console.print(f"[bold red]Error:[/bold red] Path not found: {f}")
            raise typer.Exit(code=1)

    if not expanded_files:
        err_console.print("[bold red]Error:[/bold red] No video files found to stitch.")
        raise typer.Exit(code=1)

    grouped = detect_chapters(expanded_files)
    if not grouped:
        err_console.print("[bold red]Error:[/bold red] No GoPro video chapters detected in provided files.")
        raise typer.Exit(code=1)

    for base_id, chapters in grouped.items():
        if len(chapters) <= 1 and output is None:
            console.print(f"[dim]Skipping base {base_id} (only 1 chapter: {chapters[0].name})[/dim]")
            continue

        out_path = output if output else chapters[0].parent / f"STITCH_{base_id}.mp4"
        console.print(f"[cyan]Stitching base ID {base_id} ({len(chapters)} chapters) -> {out_path.name}...[/cyan]")
        stitched = stitch_chapters(chapters, out_path, ffmpeg_path=ffmpeg)
        sync_file_time(stitched)
        console.print(f"[bold green]✓ Stitched successfully:[/bold green] {stitched}")


@process_app.command("sync-dates")
def cmd_process_sync_dates(
    files: List[Path] = typer.Argument(..., help="Media files to sync filesystem modification time from MP4 metadata"),
):
    """Synchronize file modification timestamps with MP4 container creation time."""
    for f in files:
        if not f.is_file():
            err_console.print(f"[dim]Skipping {f} (not a file)[/dim]")
            continue

        created_dt = extract_creation_time(f)
        if created_dt:
            sync_file_time(f, timestamp=created_dt)
            console.print(f"[green]✓ Synced {f.name}:[/green] {created_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        else:
            err_console.print(f"[yellow]⚠ Could not extract creation timestamp for {f.name}[/yellow]")


# -----------------------------------------------------------------------------
# GoPro Labs QR Commands
# -----------------------------------------------------------------------------

@labs_app.command("qr")
def cmd_labs_qr(
    code: str = typer.Argument(..., help="Labs code or preset name (e.g. bitrate_max, motion_detect, gyro_logging)"),
    invert: bool = typer.Option(False, "--invert", "-i", help="Invert QR display colors for light terminals"),
    save: Optional[Path] = typer.Option(None, "--save", "-s", help="Save QR code to image file (PNG/SVG)"),
):
    """Generate and display a GoPro Labs QR code directly in the terminal."""
    from uel_gopro.labs.qr import render_terminal_qr, save_qr_image, resolve_code, PRESETS

    resolved = resolve_code(code)
    console.print(f"[bold cyan]GoPro Labs QR Code:[/bold cyan] [yellow]{resolved}[/yellow]")
    if code in PRESETS:
        console.print(f"[dim]Preset alias: {code}[/dim]")

    rendered = render_terminal_qr(code, invert=invert)
    console.print(rendered)

    if save:
        out_path = save_qr_image(code, save)
        console.print(f"[green]✓ Saved QR code to {out_path}[/green]")


@labs_app.command("presets")
def cmd_labs_presets():
    """List all built-in GoPro Labs QR presets."""
    from uel_gopro.labs.qr import PRESETS

    table = Table(title="GoPro Labs Macro Presets", border_style="cyan")
    table.add_column("Preset Name", style="bold cyan")
    table.add_column("GoPro Labs Command", style="yellow")
    for name, cmd in PRESETS.items():
        table.add_row(name, cmd)
    console.print(table)


# -----------------------------------------------------------------------------
# Telemetry Commands
# -----------------------------------------------------------------------------

@telemetry_app.command("export")
def cmd_telemetry_export(
    input_file: Path = typer.Argument(..., help="Path to GoPro MP4 video or raw GPMF file"),
    format: str = typer.Option("gpx", "--format", "-f", help="Export format: gpx, kml, geojson, csv"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path"),
):
    """Extract GPMF telemetry track from GoPro MP4 and export as GPX, KML, GeoJSON, or CSV."""
    from uel_gopro.telemetry.gpmf import extract_gpmf_from_mp4, parse_gpmf_stream
    from uel_gopro.telemetry.exporters import export_gpx, export_kml, export_geojson, export_csv

    if not input_file.is_file():
        err_console.print(f"[bold red]Error:[/bold red] Input file not found: {input_file}")
        raise typer.Exit(code=1)

    console.print(f"[cyan]Extracting GPMF telemetry from {input_file.name}...[/cyan]")
    raw_bytes = extract_gpmf_from_mp4(input_file)
    track = parse_gpmf_stream(raw_bytes)

    if not track.gps_points:
        console.print("[yellow]Warning: No GPS points found in telemetry stream.[/yellow]")

    fmt = format.lower()
    default_ext = {"gpx": ".gpx", "kml": ".kml", "geojson": ".geojson", "csv": ".csv"}
    if fmt not in default_ext:
        err_console.print(f"[bold red]Error:[/bold red] Unsupported format: {fmt}. Use gpx, kml, geojson, or csv.")
        raise typer.Exit(code=1)

    out_path = output if output else input_file.with_suffix(default_ext[fmt])

    if fmt == "gpx":
        export_gpx(track, out_path)
    elif fmt == "kml":
        export_kml(track, out_path)
    elif fmt == "geojson":
        export_geojson(track, out_path)
    elif fmt == "csv":
        export_csv(track, out_path)

    console.print(f"[bold green]✓ Exported {len(track.gps_points)} telemetry points to {out_path}[/bold green]")


# -----------------------------------------------------------------------------
# Cloud Commands (GoPro Plus)
# -----------------------------------------------------------------------------

@cloud_app.command("auth")
def cmd_cloud_auth(
    token: Optional[str] = typer.Option(None, "--token", "-t", help="GoPro Plus Bearer auth token"),
    user_id: Optional[str] = typer.Option("", "--user-id", "-u", help="GoPro Plus User ID"),
):
    """Authenticate and store GoPro Plus Cloud credentials."""
    from uel_gopro.cloud.client import save_cloud_auth

    auth_token = token
    if not auth_token:
        auth_token = typer.prompt("Enter your GoPro Plus Bearer Auth Token", hide_input=True)

    save_cloud_auth(token=auth_token, user_id=user_id or "")
    console.print("[bold green]✓ GoPro Plus credentials saved successfully.[/bold green]")


@cloud_app.command("list")
def cmd_cloud_list(
    page: int = typer.Option(1, "--page", "-p", help="Page number (1-based)"),
    per_page: int = typer.Option(25, "--per-page", "-n", help="Items per page"),
    as_json: bool = typer.Option(False, "--json", help="Output as raw JSON"),
):
    """List media assets in your GoPro Plus Cloud library."""
    from uel_gopro.cloud.client import GoProCloudClient

    client = GoProCloudClient()
    items = client.list_media(page=page, per_page=per_page)

    if as_json:
        console.print(json.dumps(items, indent=2))
        return

    table = Table(title=f"GoPro Plus Cloud Library (Page {page})", border_style="cyan")
    table.add_column("Asset ID", style="dim")
    table.add_column("Filename", style="bold white")
    table.add_column("Type", style="cyan")
    table.add_column("Captured At", style="yellow")
    table.add_column("Size (MB)", justify="right")

    for it in items:
        mb = it.get("file_size", 0) / (1024 * 1024)
        table.add_row(
            it.get("id", "-"),
            it.get("filename", "Unknown"),
            it.get("type", "video").upper(),
            it.get("captured_at", "-"),
            f"{mb:.1f}" if mb > 0 else "-",
        )

    console.print(table)


@cloud_app.command("sync")
def cmd_cloud_sync(
    dest: Path = typer.Option(Path("./gopro_cloud_backup"), "--dest", "-d", help="Destination folder for backup"),
    max_pages: int = typer.Option(100, "--max-pages", help="Max pages to scan"),
):
    """Mirror all GoPro Plus Cloud media assets to local storage (NAS backup)."""
    from uel_gopro.cloud.client import GoProCloudClient

    client = GoProCloudClient()
    console.print(f"[cyan]Syncing GoPro Plus cloud media to {dest}...[/cyan]")

    def on_progress(dl: int, total: int):
        pass

    downloaded = client.sync_all(dest_dir=dest, max_pages=max_pages, progress_callback=on_progress)
    console.print(f"[bold green]✓ Cloud sync finished. Processed {len(downloaded)} assets.[/bold green]")


def main():
    app()


if __name__ == "__main__":
    main()
