from unittest.mock import AsyncMock, MagicMock

import pytest

from uel_gopro.core.exceptions import TransportError
from uel_gopro.transport.ble import (
    CMD_POWER_ON_WIFI,
    CMD_SHUTTER_START,
    CMD_SHUTTER_STOP,
    COMMAND_REQ,
    GOPRO_SERVICE_UUID,
    GoProBleClient,
    deframe_ble_packets,
    frame_ble_packet,
)


def test_frame_ble_packet_official_shutter_vector():
    """Match the official OpenGoPro SDK wire bytes for SET_SHUTTER(start)."""
    packets = frame_ble_packet(CMD_SHUTTER_START)
    assert packets == [bytes.fromhex("2003010101")]
    assert CMD_SHUTTER_START == bytes([0x01, 0x01, 0x01])
    assert CMD_SHUTTER_STOP == bytes([0x01, 0x01, 0x00])
    assert CMD_POWER_ON_WIFI == bytes([0x17, 0x01, 0x01])


def test_frame_ble_packet_multi_and_roundtrip():
    payload = b"X" * 100
    packets = frame_ble_packet(payload, max_packet_len=20)
    assert len(packets) > 1
    assert packets[0][:2] == bytes([0x20, 100])
    assert len(packets[0]) == 20
    assert packets[0][2:] == payload[:18]
    assert packets[1][0] == 0x80
    assert packets[2][0] == 0x81
    assert deframe_ble_packets(packets) == payload


def test_frame_ble_packet_sequence_wrap():
    payload = bytes(range(256)) * 2  # 512 bytes
    packets = frame_ble_packet(payload, max_packet_len=20)
    for index, packet in enumerate(packets[1:]):
        assert packet[0] == (0x80 | (index % 16))
    assert deframe_ble_packets(packets) == payload


def test_frame_ble_packet_extended_16bit():
    payload = b"A" * 8200
    packets = frame_ble_packet(payload)
    assert packets[0][:3] == bytes([0x40, 8200 >> 8, 8200 & 0xFF])
    assert deframe_ble_packets(packets) == payload


def test_frame_ble_packet_empty_and_too_long():
    with pytest.raises(ValueError, match="empty"):
        frame_ble_packet(b"")
    with pytest.raises(ValueError, match="too long"):
        frame_ble_packet(b"A" * 65535)


def test_deframe_ble_packets_general_header():
    payload = b"hello gopro"
    packets = [bytes([len(payload)]) + payload]
    assert deframe_ble_packets(packets) == payload


def test_deframe_ble_packets_errors():
    assert deframe_ble_packets([]) == b""

    with pytest.raises(ValueError, match="First packet cannot be empty"):
        deframe_ble_packets([b""])

    with pytest.raises(ValueError, match="First packet cannot be a continuation packet"):
        deframe_ble_packets([b"\x80continuation"])

    payload = b"Z" * 80
    packets = frame_ble_packet(payload, max_packet_len=20)
    with pytest.raises(ValueError, match="Incomplete packet frame"):
        deframe_ble_packets(packets[:-1])

    corrupt_packets = [packets[0], b"\x00corrupt"]
    with pytest.raises(ValueError, match="missing continuation header"):
        deframe_ble_packets(corrupt_packets)


@pytest.mark.asyncio
async def test_ble_mock_discovery(monkeypatch):
    mock_device = MagicMock()
    mock_device.name = "GoPro 1234"
    mock_device.address = "11:22:33:44:55:66"

    advertisement = MagicMock()
    advertisement.service_uuids = [GOPRO_SERVICE_UUID]
    advertisement.manufacturer_data = {0x02F2: b"\x01"}
    advertisement.local_name = "GoPro 1234"

    mock_discover = AsyncMock(return_value={"11:22:33:44:55:66": (mock_device, advertisement)})
    monkeypatch.setattr("uel_gopro.transport.ble.BleakScanner.discover", mock_discover)

    devices = await GoProBleClient.scan(timeout=2.5)
    assert devices == [mock_device]
    mock_discover.assert_called_once_with(timeout=2.5, return_adv=True)


@pytest.mark.asyncio
async def test_ble_command_dispatch_uses_single_framing():
    mock_client = AsyncMock()
    mock_client.is_connected = True

    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()
    mock_client.connect.assert_called_once()

    await client.shutter_start()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        bytes.fromhex("2003010101"),
        response=True,
    )

    await client.shutter_stop()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        bytes.fromhex("2003010100"),
        response=True,
    )

    await client.power_on_wifi()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        bytes.fromhex("2003170101"),
        response=True,
    )

    await client.disconnect()
    mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_ble_disconnected_error():
    client = GoProBleClient(address="11:22:33:44:55:66")
    with pytest.raises(TransportError, match="BLE client is not connected"):
        await client.send_command(CMD_SHUTTER_START)
