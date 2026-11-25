from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from bleak import BleakClient, BleakScanner

from uel_gopro.api.rest import parse_camera_status
from uel_gopro.core.exceptions import CommandError, TransportError, UelError
from uel_gopro.core.models import CameraStatus

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

# OpenGoPro BLE query opcodes (sent via QUERY_REQ / QUERY_RSP).
QUERY_GET_SETTING_VALUES = 0x12
QUERY_GET_STATUS_VALUES = 0x13
QUERY_GET_AVAILABLE_SETTINGS = 0x32
DEFAULT_STATUS_QUERY_IDS = [2, 6, 8, 10, 33, 34, 35, 54, 70, 96, 97]


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


class _IncompleteBleFrameError(ValueError):
    """Internal signal that more BLE notification packets are needed."""


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
        raise _IncompleteBleFrameError(
            f"Incomplete packet frame: expected {expected_len} bytes, got {len(payload)}"
        )
    return bytes(payload[:expected_len])


def parse_ble_tlv_response(raw: bytes) -> tuple[int, int, dict[int, list[int]]]:
    """Parse an OpenGoPro BLE query TLV response ``[query_id, status_code, id, len, val...]``."""
    if len(raw) < 2:
        raise ValueError(f"BLE TLV response too short: expected at least 2 bytes, got {len(raw)}")

    query_id = raw[0]
    status_code = raw[1]
    values: dict[int, list[int]] = {}
    i = 2
    while i < len(raw):
        if i + 2 > len(raw):
            raise ValueError(f"Truncated BLE TLV entry header at offset {i}")
        entry_id = raw[i]
        length = raw[i + 1]
        if i + 2 + length > len(raw):
            raise ValueError(
                f"Truncated BLE TLV entry for ID {entry_id}: expected {length} bytes, "
                f"got {len(raw) - (i + 2)}"
            )
        bucket = values.setdefault(entry_id, [])
        if length > 0:
            val_bytes = raw[i + 2 : i + 2 + length]
            bucket.append(int.from_bytes(val_bytes, "big"))
        i += 2 + length

    return query_id, status_code, values


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
        self._response_locks: dict[str, asyncio.Lock] = {}

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
            try:
                await self._client.disconnect()
            finally:
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

    async def _await_ble_response(
        self,
        req_uuid: str,
        rsp_uuid: str,
        payload: bytes,
        timeout_sec: float = 5.0,
    ) -> bytes:
        """Send a framed BLE payload on ``req_uuid`` and reassemble the response from ``rsp_uuid``."""
        if not self.is_connected or self._client is None:
            raise TransportError("BLE client is not connected")

        lock = self._response_locks.setdefault(rsp_uuid, asyncio.Lock())
        async with lock:
            if not self.is_connected or self._client is None:
                raise TransportError("BLE client is not connected")

            packets_to_send = frame_ble_packet(payload)
            rx_packets: list[bytes] = []
            assembled: Optional[bytes] = None
            assemble_error: Optional[Exception] = None
            done = asyncio.Event()

            def _on_notify(_sender: Any, data: bytearray) -> None:
                nonlocal assembled, assemble_error
                if done.is_set() or not data:
                    return
                pkt = bytes(data)
                if (pkt[0] & 0x80) == 0:
                    rx_packets.clear()
                elif not rx_packets:
                    return
                rx_packets.append(pkt)
                try:
                    assembled = deframe_ble_packets(rx_packets)
                except _IncompleteBleFrameError:
                    return
                except ValueError as exc:
                    assemble_error = exc
                    done.set()
                else:
                    done.set()

            try:
                await self._client.start_notify(rsp_uuid, _on_notify)
            except UelError:
                raise
            except Exception as exc:
                raise TransportError(f"Failed to subscribe to BLE notifications on {rsp_uuid}: {exc}") from exc

            try:
                for packet in packets_to_send:
                    try:
                        await self._client.write_gatt_char(req_uuid, packet, response=True)
                    except UelError:
                        raise
                    except Exception as exc:
                        raise TransportError(f"BLE write to {req_uuid} failed: {exc}") from exc
                try:
                    await asyncio.wait_for(done.wait(), timeout=timeout_sec)
                except asyncio.TimeoutError as exc:
                    raise TransportError(
                        f"Timed out waiting for BLE response on {rsp_uuid} after {timeout_sec:.1f}s"
                    ) from exc
            finally:
                try:
                    await self._client.stop_notify(rsp_uuid)
                except Exception:
                    pass

            if assemble_error is not None:
                raise TransportError(f"Invalid BLE response frame: {assemble_error}") from assemble_error
            assert assembled is not None
            return assembled

    async def query(self, payload: bytes, timeout_sec: float = 5.0) -> bytes:
        """Send an OpenGoPro query payload on QUERY_REQ and return deframed QUERY_RSP bytes."""
        return await self._await_ble_response(
            QUERY_REQ,
            QUERY_RSP,
            payload,
            timeout_sec=timeout_sec,
        )

    async def _query_tlv(
        self,
        query_op: int,
        ids: Optional[list[int]] = None,
        timeout_sec: float = 5.0,
    ) -> dict[int, list[int]]:
        """Execute a TLV query opcode and verify the response opcode and status code."""
        raw = await self.query(bytes([query_op, *(ids or [])]), timeout_sec=timeout_sec)
        query_id, status_code, parsed = parse_ble_tlv_response(raw)
        if query_id != query_op:
            raise CommandError(
                f"BLE query response mismatch: expected opcode 0x{query_op:02x}, got 0x{query_id:02x}"
            )
        if status_code != 0:
            raise CommandError(
                f"BLE query 0x{query_op:02x} failed with status code {status_code}"
            )
        return parsed

    async def get_status_values(
        self,
        status_ids: Optional[list[int]] = None,
        timeout_sec: float = 5.0,
    ) -> dict[int, int]:
        """Query camera status values over BLE (opcode 0x13)."""
        parsed = await self._query_tlv(
            QUERY_GET_STATUS_VALUES,
            status_ids,
            timeout_sec=timeout_sec,
        )
        return {k: vals[-1] for k, vals in parsed.items() if vals}

    async def get_camera_status(self, timeout_sec: float = 5.0) -> CameraStatus:
        """Query core camera status IDs over BLE and parse into CameraStatus."""
        values = await self.get_status_values(DEFAULT_STATUS_QUERY_IDS, timeout_sec=timeout_sec)
        return parse_camera_status(values)

    async def get_settings(
        self,
        setting_ids: Optional[list[int]] = None,
        timeout_sec: float = 5.0,
    ) -> dict[int, int]:
        """Query camera setting values over BLE (opcode 0x12)."""
        parsed = await self._query_tlv(
            QUERY_GET_SETTING_VALUES,
            setting_ids,
            timeout_sec=timeout_sec,
        )
        return {k: vals[-1] for k, vals in parsed.items() if vals}

    async def get_available_settings(
        self,
        setting_ids: Optional[list[int]] = None,
        timeout_sec: float = 5.0,
    ) -> dict[int, list[int]]:
        """Query available setting capabilities over BLE (opcode 0x32)."""
        return await self._query_tlv(
            QUERY_GET_AVAILABLE_SETTINGS,
            setting_ids,
            timeout_sec=timeout_sec,
        )

    async def set_setting(
        self,
        setting_id: int,
        value: int,
        timeout_sec: float = 5.0,
    ) -> None:
        """Mutate a 1-byte camera setting over BLE SETTINGS_REQ/SETTINGS_RSP."""
        if isinstance(setting_id, bool) or not isinstance(setting_id, int):
            raise CommandError(f"BLE setting ID must be an int, got {setting_id!r}")
        if not (0 <= setting_id <= 255):
            raise CommandError(
                f"BLE setting ID {setting_id!r} is out of 1-byte range (0-255)"
            )
        if isinstance(value, bool) or not isinstance(value, int):
            raise CommandError(f"BLE setting value must be an int, got {value!r}")
        if not (0 <= value <= 255):
            raise CommandError(
                f"BLE setting value {value!r} is out of 1-byte range (0-255)"
            )
        resp = await self._await_ble_response(
            SETTINGS_REQ,
            SETTINGS_RSP,
            bytes([setting_id, 1, value]),
            timeout_sec=timeout_sec,
        )
        if len(resp) < 2:
            raise CommandError(
                f"Invalid BLE settings response: expected at least 2 bytes, got {len(resp)}"
            )
        if resp[0] != setting_id:
            raise CommandError(
                f"BLE settings response mismatch: expected setting ID {setting_id}, got {resp[0]}"
            )
        if resp[1] != 0:
            raise CommandError(
                f"BLE set_setting({setting_id}={value}) failed with status code {resp[1]}"
            )

    async def __aenter__(self) -> GoProBleClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
