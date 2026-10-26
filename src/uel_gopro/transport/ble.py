from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakScanner

from uel_gopro.core.exceptions import TransportError

logger = logging.getLogger(__name__)

# GoPro BLE service and characteristics.
# Source: https://gopro.github.io/OpenGoPro/docs/ble
GOPRO_SERVICE_UUID = "0000fea6-0000-1000-8000-00805f9b34fb"
GOPRO_SERVICE_UUID_SHORT = 0xFEA6
GOPRO_MANUFACTURER_ID = 0x02F2

COMMAND_REQ = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
COMMAND_RSP = "b5f90073-aa8d-11e3-9046-0002a5d5c51b"
SETTINGS_REQ = "b5f90074-aa8d-11e3-9046-0002a5d5c51b"
SETTINGS_RSP = "b5f90075-aa8d-11e3-9046-0002a5d5c51b"
QUERY_REQ = "b5f90076-aa8d-11e3-9046-0002a5d5c51b"
QUERY_RSP = "b5f90077-aa8d-11e3-9046-0002a5d5c51b"

# Standard Bluetooth SIG device-information characteristics.
CHAR_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_SERIAL_NUMBER = "00002a25-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE_REV = "00002a26-0000-1000-8000-00805f9b34fb"
CHAR_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

BLE_MAX_PACKET_LEN = 20

# Command payloads (command ID + argument length + arguments).
# These are *payloads*: frame_ble_packet() adds the BLE transport header.
# Source: open_gopro.api.builders.BleWriteCommand._build_data
CMD_SHUTTER_START = bytes([0x01, 0x01, 0x01])  # SET_SHUTTER, 1 arg, start
CMD_SHUTTER_STOP = bytes([0x01, 0x01, 0x00])  # SET_SHUTTER, 1 arg, stop
CMD_POWER_ON_WIFI = bytes([0x17, 0x01, 0x01])  # SET_WIFI, 1 arg, enable AP


def frame_ble_packet(payload: bytes, max_packet_len: int = BLE_MAX_PACKET_LEN) -> list[bytes]:
    """Encode a GoPro BLE payload with transport headers and fragmentation.

    The official OpenGoPro SDK always uses the 13-bit extended header for
    writes (``0b001LLLLL LLLLLLLL``), followed by continuation packets with
    ``0b1000SSSS`` headers.  For payloads that do not fit in 13 bits, the
    16-bit extended header is used.

    Args:
        payload: Command bytes (command ID, argument length, arguments).
        max_packet_len: Maximum bytes per BLE write (20 by default).

    Returns:
        One or more complete BLE packets.
    """
    if not payload:
        raise ValueError("BLE payload cannot be empty")

    length = len(payload)
    if length < (2**13 - 1):
        header = bytes([0x20 | (length >> 8), length & 0xFF])
    elif length < (2**16 - 1):
        header = bytes([0x40, (length >> 8) & 0xFF, length & 0xFF])
    else:
        raise ValueError(f"BLE payload too long: {length} bytes")

    if max_packet_len <= len(header):
        raise ValueError("max_packet_len is too small for the BLE header")

    first_chunk_size = max_packet_len - len(header)
    packets = [header + payload[:first_chunk_size]]
    remaining = payload[first_chunk_size:]
    sequence = 0
    while remaining:
        cont_header = bytes([0x80 | (sequence % 16)])
        chunk_size = max_packet_len - len(cont_header)
        packets.append(cont_header + remaining[:chunk_size])
        remaining = remaining[chunk_size:]
        sequence += 1
    return packets


def deframe_ble_packets(packets: list[bytes]) -> bytes:
    """Reassemble a GoPro BLE payload from one or more received packets.

    Supports General (5-bit), extended 13-bit, and extended 16-bit headers.
    """
    if not packets:
        return b""

    first = packets[0]
    if not first:
        raise ValueError("First packet cannot be empty")
    if first[0] & 0x80:
        raise ValueError("First packet cannot be a continuation packet")

    header_type = (first[0] & 0x60) >> 5
    if header_type == 0:  # General header, 5-bit length
        expected_len = first[0] & 0x1F
        payload = bytearray(first[1:])
    elif header_type == 1:  # Extended 13-bit length
        if len(first) < 2:
            raise ValueError("Extended 13-bit header requires at least 2 bytes")
        expected_len = ((first[0] & 0x1F) << 8) | first[1]
        payload = bytearray(first[2:])
    elif header_type == 2:  # Extended 16-bit length
        if len(first) < 3:
            raise ValueError("Extended 16-bit header requires at least 3 bytes")
        expected_len = (first[1] << 8) | first[2]
        payload = bytearray(first[3:])
    else:
        raise ValueError(f"Unknown packet header type: {header_type}")

    for idx, packet in enumerate(packets[1:], start=1):
        if not packet:
            continue
        if packet[0] & 0x80 == 0:
            raise ValueError(f"Packet at index {idx} is missing continuation header (0x80)")
        payload.extend(packet[1:])

    if len(payload) < expected_len:
        raise ValueError(
            f"Incomplete packet frame: expected {expected_len} bytes, got {len(payload)}"
        )
    return bytes(payload[:expected_len])


class GoProBleClient:
    """Cross-platform BLE client for GoPro cameras using bleak."""

    def __init__(
        self,
        address: Optional[str] = None,
        client: Optional[BleakClient] = None,
    ):
        self.address = address
        self._client = client
        self._is_connected = False

    @classmethod
    async def scan(cls, timeout: float = 3.0) -> list[Any]:
        """Discover BLE devices advertising the GoPro service or manufacturer ID."""
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        gopros: list[Any] = []
        if isinstance(devices, dict):
            for device, adv in devices.values():
                service_uuids = {str(uuid).lower() for uuid in (adv.service_uuids or [])}
                manufacturer_data = adv.manufacturer_data or {}
                if GOPRO_SERVICE_UUID in service_uuids or GOPRO_MANUFACTURER_ID in manufacturer_data:
                    if not device.name and adv.local_name:
                        device.name = adv.local_name
                    gopros.append(device)
        else:  # pragma: no cover - bleak >= 0.19 always returns a dict with return_adv=True
            gopros = list(devices)
        return gopros

    async def connect(self, address: Optional[str] = None) -> None:
        """Connect to a GoPro camera by BLE address."""
        if address:
            self.address = address
        if not self.address and self._client is None:
            raise ValueError("BLE address or client required to connect")
        if self._client is None:
            self._client = BleakClient(self.address)
        await self._client.connect()
        self._is_connected = True

    async def disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self._client is not None:
            await self._client.disconnect()
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        """Check whether the BLE client is currently connected."""
        if self._client is not None:
            return bool(getattr(self._client, "is_connected", self._is_connected))
        return self._is_connected

    async def send_command(self, payload: bytes, response: bool = True) -> None:
        """Send a command payload to the camera over the Command characteristic.

        ``payload`` must be the command payload (command ID, argument length,
        arguments).  It is framed here exactly once.
        """
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")
        for packet in frame_ble_packet(payload):
            await self._client.write_gatt_char(COMMAND_REQ, packet, response=response)

    async def shutter_start(self) -> None:
        """Start shutter (recording or photo capture in the current mode)."""
        await self.send_command(CMD_SHUTTER_START)

    async def shutter_stop(self) -> None:
        """Stop shutter/recording."""
        await self.send_command(CMD_SHUTTER_STOP)

    async def power_on_wifi(self) -> None:
        """Power on the camera's Wi-Fi access point."""
        await self.send_command(CMD_POWER_ON_WIFI)

    async def get_battery_level(self) -> int:
        """Read the battery level percentage over the standard GATT characteristic."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")
        data = await self._client.read_gatt_char(CHAR_BATTERY_LEVEL)
        return int(data[0]) if data else 0

    async def get_device_info(self) -> dict[str, str]:
        """Read model, serial, firmware, and manufacturer strings over BLE."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")

        async def read_str(char_uuid: str) -> str:
            try:
                raw = await self._client.read_gatt_char(char_uuid)
                return raw.decode("utf-8", errors="ignore").strip("\x00")
            except Exception:
                return "Unknown"

        return {
            "manufacturer": await read_str(CHAR_MANUFACTURER),
            "model": await read_str(CHAR_MODEL_NUMBER),
            "firmware": await read_str(CHAR_FIRMWARE_REV),
            "serial": await read_str(CHAR_SERIAL_NUMBER),
        }

    async def start_notifications(self, callback: Callable[[Any, bytearray], None]) -> None:
        """Register a notification callback on COMMAND_RSP."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")
        await self._client.start_notify(COMMAND_RSP, callback)

    async def stop_notifications(self) -> None:
        """Unregister notifications on COMMAND_RSP."""
        if not self.is_connected or self._client is None:
            return
        await self._client.stop_notify(COMMAND_RSP)

    async def __aenter__(self) -> GoProBleClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
