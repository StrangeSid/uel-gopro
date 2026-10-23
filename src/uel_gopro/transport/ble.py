from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional
from bleak import BleakClient, BleakScanner

from uel_gopro.core.exceptions import TransportError

logger = logging.getLogger(__name__)

# Service and Characteristic UUIDs
GOPRO_SERVICE_UUID = "0000fea6-0000-1000-8000-00805f9b34fb"
GOPRO_SERVICE_UUID_SHORT = 0xFEA6
GOPRO_MANUFACTURER_ID = 0x02F2

# Standard GoPro BLE Service and Characteristic UUIDs (b5f9...)
COMMAND_REQ = "b5f90072-aa8d-11e3-9046-0002a5d5c51b"
COMMAND_RSP = "b5f90073-aa8d-11e3-9046-0002a5d5c51b"
SETTINGS_REQ = "b5f90074-aa8d-11e3-9046-0002a5d5c51b"
SETTINGS_RSP = "b5f90075-aa8d-11e3-9046-0002a5d5c51b"
QUERY_REQ = "b5f90076-aa8d-11e3-9046-0002a5d5c51b"
QUERY_RSP = "b5f90077-aa8d-11e3-9046-0002a5d5c51b"

# Standard Bluetooth SIG Characteristics
CHAR_BATTERY_LEVEL = "00002a19-0000-1000-8000-00805f9b34fb"
CHAR_MODEL_NUMBER = "00002a24-0000-1000-8000-00805f9b34fb"
CHAR_SERIAL_NUMBER = "00002a25-0000-1000-8000-00805f9b34fb"
CHAR_FIRMWARE_REV = "00002a26-0000-1000-8000-00805f9b34fb"
CHAR_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

# Command Byte Sequences
CMD_SHUTTER_START = bytes([0x03, 0x01, 0x01, 0x01])
CMD_SHUTTER_STOP = bytes([0x03, 0x01, 0x01, 0x00])
CMD_POWER_ON_WIFI = bytes([0x03, 0x17, 0x01, 0x01])
CMD_KEEP_ALIVE = bytes([0x03, 0x5B, 0x01, 0x42])


def frame_ble_packet(payload: bytes, max_packet_len: int = 20) -> list[bytes]:
    """Encodes payload with GoPro header framing.

    - Length <= 31: single packet `bytes([len(payload)]) + payload`
    - Length > 31 and <= 8191: two-byte header `bytes([0x20 | (len(payload) >> 8), len(payload) & 0xFF])` + chunks,
      continuation packets start with `bytes([0x80 | (seq % 16)])`.
    """
    length = len(payload)
    if length <= 31:
        return [bytes([length]) + payload]
    elif length <= 8191:
        header = bytes([0x20 | (length >> 8), length & 0xFF])
        first_chunk_size = max_packet_len - len(header)
        packets = [header + payload[:first_chunk_size]]
        remaining = payload[first_chunk_size:]
        seq = 0
        while remaining:
            cont_header = bytes([0x80 | (seq % 16)])
            cont_chunk_size = max_packet_len - len(cont_header)
            packets.append(cont_header + remaining[:cont_chunk_size])
            remaining = remaining[cont_chunk_size:]
            seq += 1
        return packets
    else:
        # Extended 16-bit header for payload > 8191
        header = bytes([0x40, (length >> 8) & 0xFF, length & 0xFF])
        first_chunk_size = max_packet_len - len(header)
        packets = [header + payload[:first_chunk_size]]
        remaining = payload[first_chunk_size:]
        seq = 0
        while remaining:
            cont_header = bytes([0x80 | (seq % 16)])
            cont_chunk_size = max_packet_len - len(cont_header)
            packets.append(cont_header + remaining[:cont_chunk_size])
            remaining = remaining[cont_chunk_size:]
            seq += 1
        return packets


def deframe_ble_packets(packets: list[bytes]) -> bytes:
    """Reassembles multi-packet frames from GoPro BLE packets."""
    if not packets:
        return b""

    first = packets[0]
    if not first:
        raise ValueError("First packet cannot be empty")

    if first[0] & 0x80 != 0:
        raise ValueError("First packet cannot be a continuation packet")

    hdr_type = (first[0] & 0x60) >> 5

    if hdr_type == 0:  # General header (5-bit length <= 31)
        expected_len = first[0] & 0x1F
        payload = bytearray(first[1:])
    elif hdr_type == 1:  # EXT_13 header (13-bit length <= 8191)
        if len(first) < 2:
            raise ValueError("Extended 13-bit header requires at least 2 bytes")
        expected_len = ((first[0] & 0x1F) << 8) | first[1]
        payload = bytearray(first[2:])
    elif hdr_type == 2:  # EXT_16 header (16-bit length)
        if len(first) < 3:
            raise ValueError("Extended 16-bit header requires at least 3 bytes")
        expected_len = (first[1] << 8) | first[2]
        payload = bytearray(first[3:])
    else:
        raise ValueError(f"Unknown packet header type: {hdr_type}")

    for idx, pkt in enumerate(packets[1:], start=1):
        if not pkt:
            continue
        if pkt[0] & 0x80 == 0:
            raise ValueError(f"Packet at index {idx} is missing continuation header (0x80)")
        payload.extend(pkt[1:])

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
        """Discovers BLE devices advertising 0xFEA6 (GOPRO_SERVICE_UUID) or GoPro manufacturer ID."""
        devices = await BleakScanner.discover(
            timeout=timeout,
            return_adv=True,
        )
        gopros = []
        if isinstance(devices, dict):
            for d, adv in devices.values():
                if GOPRO_SERVICE_UUID in adv.service_uuids or GOPRO_MANUFACTURER_ID in adv.manufacturer_data:
                    if not d.name and adv.local_name:
                        d.name = adv.local_name
                    gopros.append(d)
        else:
            gopros = list(devices)
        return gopros

    async def connect(self, address: Optional[str] = None) -> None:
        """Connects to GoPro camera by BLE address."""
        if address:
            self.address = address
        if not self.address and self._client is None:
            raise ValueError("BLE address or client required to connect")

        if self._client is None:
            self._client = BleakClient(self.address)

        await self._client.connect()
        self._is_connected = True

    async def disconnect(self) -> None:
        """Disconnects from the BLE device."""
        if self._client is not None:
            await self._client.disconnect()
            self._is_connected = False

    @property
    def is_connected(self) -> bool:
        """Check whether BLE client is currently connected."""
        if self._client is not None:
            return getattr(self._client, "is_connected", self._is_connected)
        return self._is_connected

    async def send_command(self, cmd: bytes, response: bool = True) -> None:
        """Send a framed command to the camera via COMMAND_REQ characteristic."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")

        packets = frame_ble_packet(cmd)
        for packet in packets:
            await self._client.write_gatt_char(COMMAND_REQ, packet, response=response)

    async def shutter_start(self) -> None:
        """Start shutter (recording/photo capture)."""
        await self.send_command(CMD_SHUTTER_START)

    async def shutter_stop(self) -> None:
        """Stop shutter (recording/photo capture)."""
        await self.send_command(CMD_SHUTTER_STOP)

    async def power_on_wifi(self) -> None:
        """Power on camera Wi-Fi Access Point."""
        await self.send_command(CMD_POWER_ON_WIFI)

    async def keep_alive(self) -> None:
        """Send keep-alive packet."""
        await self.send_command(CMD_KEEP_ALIVE)

    async def get_battery_level(self) -> int:
        """Reads the battery level percentage over BLE."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")
        data = await self._client.read_gatt_char(CHAR_BATTERY_LEVEL)
        return int(data[0]) if data else 0

    async def get_device_info(self) -> dict[str, str]:
        """Reads camera model, serial, and firmware revision strings over BLE."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")

        async def _read_str(char_uuid: str) -> str:
            try:
                raw = await self._client.read_gatt_char(char_uuid)
                return raw.decode("utf-8", errors="ignore").strip("\x00")
            except Exception:
                return "Unknown"

        return {
            "manufacturer": await _read_str(CHAR_MANUFACTURER),
            "model": await _read_str(CHAR_MODEL_NUMBER),
            "firmware": await _read_str(CHAR_FIRMWARE_REV),
            "serial": await _read_str(CHAR_SERIAL_NUMBER),
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
