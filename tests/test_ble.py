from unittest.mock import AsyncMock, MagicMock
import pytest

from uel_gopro.core.exceptions import TransportError
from uel_gopro.transport.ble import (
    CMD_KEEP_ALIVE,
    CMD_POWER_ON_WIFI,
    CMD_SHUTTER_START,
    CMD_SHUTTER_STOP,
    COMMAND_REQ,
    GOPRO_SERVICE_UUID,
    GoProBleClient,
    deframe_ble_packets,
    frame_ble_packet,
)


def test_frame_ble_packet_single():
    payload = b"short_cmd"
    packets = frame_ble_packet(payload)
    assert len(packets) == 1
    assert packets[0] == bytes([len(payload)]) + payload

    # Test exact 31 bytes boundary
    payload31 = b"B" * 31
    packets31 = frame_ble_packet(payload31)
    assert len(packets31) == 1
    assert packets31[0] == bytes([31]) + payload31


def test_frame_ble_packet_multi():
    payload = b"X" * 100
    packets = frame_ble_packet(payload, max_packet_len=20)
    assert len(packets) > 1

    # First packet: 2-byte header + 18 bytes payload
    header = packets[0][:2]
    assert header[0] == (0x20 | (100 >> 8))
    assert header[1] == (100 & 0xFF)
    assert len(packets[0]) == 20
    assert packets[0][2:] == payload[:18]

    # Continuation packets
    assert packets[1][0] == 0x80  # seq 0
    assert packets[2][0] == 0x81  # seq 1

    # Deframe roundtrip
    reassembled = deframe_ble_packets(packets)
    assert reassembled == payload


def test_frame_ble_packet_sequence_wrap():
    # Long payload that requires > 16 continuation packets
    payload = bytes(range(256)) * 2  # 512 bytes
    packets = frame_ble_packet(payload, max_packet_len=20)
    for i, pkt in enumerate(packets[1:]):
        expected_seq = i % 16
        assert pkt[0] == (0x80 | expected_seq)

    assert deframe_ble_packets(packets) == payload


def test_deframe_ble_packets_single():
    payload = b"hello gopro"
    packets = [bytes([len(payload)]) + payload]
    assert deframe_ble_packets(packets) == payload


def test_deframe_ble_packets_errors():
    assert deframe_ble_packets([]) == b""

    with pytest.raises(ValueError, match="First packet cannot be empty"):
        deframe_ble_packets([b""])

    with pytest.raises(ValueError, match="First packet cannot be a continuation packet"):
        deframe_ble_packets([b"\x80continuation"])

    # Incomplete sequence
    payload = b"Z" * 80
    packets = frame_ble_packet(payload, max_packet_len=20)
    with pytest.raises(ValueError, match="Incomplete packet frame"):
        deframe_ble_packets(packets[:-1])

    # Subsequent packet missing continuation header
    corrupt_packets = [packets[0], b"\x00corrupt"]
    with pytest.raises(ValueError, match="missing continuation header"):
        deframe_ble_packets(corrupt_packets)


@pytest.mark.asyncio
async def test_ble_mock_discovery(monkeypatch):
    mock_dev1 = MagicMock()
    mock_dev1.name = "GoPro 1234"
    mock_dev1.address = "11:22:33:44:55:66"

    mock_discover = AsyncMock(return_value=[mock_dev1])
    monkeypatch.setattr("uel_gopro.transport.ble.BleakScanner.discover", mock_discover)

    devices = await GoProBleClient.scan(timeout=2.5)
    assert len(devices) == 1
    assert devices[0].name == "GoPro 1234"
    mock_discover.assert_called_once_with(
        timeout=2.5,
        return_adv=True,
    )


@pytest.mark.asyncio
async def test_ble_command_dispatch():
    mock_client = AsyncMock()
    mock_client.is_connected = True

    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()
    mock_client.connect.assert_called_once()

    # Shutter start
    await client.shutter_start()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        frame_ble_packet(CMD_SHUTTER_START)[0],
        response=True,
    )

    # Shutter stop
    await client.shutter_stop()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        frame_ble_packet(CMD_SHUTTER_STOP)[0],
        response=True,
    )

    # Power on wifi
    await client.power_on_wifi()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        frame_ble_packet(CMD_POWER_ON_WIFI)[0],
        response=True,
    )

    # Keep alive
    await client.keep_alive()
    mock_client.write_gatt_char.assert_called_with(
        COMMAND_REQ,
        frame_ble_packet(CMD_KEEP_ALIVE)[0],
        response=True,
    )

    # Disconnect
    await client.disconnect()
    mock_client.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_ble_disconnected_error():
    client = GoProBleClient(address="11:22:33:44:55:66")
    with pytest.raises(TransportError, match="BLE client is not connected"):
        await client.send_command(CMD_SHUTTER_START)
