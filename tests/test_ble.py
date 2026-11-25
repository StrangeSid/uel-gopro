from unittest.mock import AsyncMock, MagicMock

import pytest

from uel_gopro.core.exceptions import CommandError, TransportError
from uel_gopro.transport.ble import (
    CMD_POWER_ON_WIFI,
    CMD_SHUTTER_START,
    CMD_SHUTTER_STOP,
    COMMAND_REQ,
    DEFAULT_STATUS_QUERY_IDS,
    GOPRO_SERVICE_UUID,
    QUERY_GET_AVAILABLE_SETTINGS,
    QUERY_GET_SETTING_VALUES,
    QUERY_GET_STATUS_VALUES,
    QUERY_REQ,
    QUERY_RSP,
    SETTINGS_REQ,
    SETTINGS_RSP,
    GoProBleClient,
    deframe_ble_packets,
    frame_ble_packet,
    parse_ble_tlv_response,
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
    with pytest.raises(TransportError, match="BLE client is not connected"):
        await client.query(bytes([QUERY_GET_STATUS_VALUES, 70]))


def test_parse_ble_tlv_response_multibyte_repeated_and_empty():
    # query_id=0x13, status=0x00, ID 54 (4 bytes: 25_630_304), ID 96 (2 bytes: 1000), ID 29 (0 bytes)
    raw = (
        bytes([0x13, 0x00])
        + bytes([54, 4])
        + (25_630_304).to_bytes(4, "big")
        + bytes([96, 2])
        + (1000).to_bytes(2, "big")
        + bytes([29, 0])
    )
    query_id, status_code, parsed = parse_ble_tlv_response(raw)
    assert query_id == 0x13
    assert status_code == 0
    assert parsed == {54: [25_630_304], 96: [1000], 29: []}

    # 0x32 capability response with repeated entries for setting ID 2
    caps_raw = bytes([0x32, 0x00, 2, 1, 1, 2, 1, 4, 2, 1, 9, 3, 1, 5])
    q_id, st, caps = parse_ble_tlv_response(caps_raw)
    assert q_id == 0x32
    assert st == 0
    assert caps == {2: [1, 4, 9], 3: [5]}


def test_parse_ble_tlv_response_errors():
    with pytest.raises(ValueError, match="too short"):
        parse_ble_tlv_response(b"\x13")
    with pytest.raises(ValueError, match="Truncated BLE TLV entry header"):
        parse_ble_tlv_response(bytes([0x13, 0x00, 70]))
    with pytest.raises(ValueError, match="Truncated BLE TLV entry for ID 54"):
        parse_ble_tlv_response(bytes([0x13, 0x00, 54, 4, 0x01, 0x02]))


def _make_notifying_ble_client(rsp_uuid: str, response_payloads: list[bytes]):
    """Build a mock BleakClient that emits framed notification packets upon write."""
    mock_client = AsyncMock()
    mock_client.is_connected = True
    callbacks = {}

    async def fake_start_notify(uuid, cb):
        callbacks[uuid] = cb

    async def fake_stop_notify(uuid):
        callbacks.pop(uuid, None)

    async def fake_write_gatt_char(uuid, data, response=True):
        cb = callbacks.get(rsp_uuid)
        if cb is not None:
            for payload in response_payloads:
                for pkt in frame_ble_packet(payload, max_packet_len=20):
                    cb(uuid, bytearray(pkt))

    mock_client.start_notify.side_effect = fake_start_notify
    mock_client.stop_notify.side_effect = fake_stop_notify
    mock_client.write_gatt_char.side_effect = fake_write_gatt_char
    return mock_client


@pytest.mark.asyncio
async def test_ble_query_multipacket_reassembly_and_cleanup():
    # Construct a >20 byte TLV payload so response spans multiple BLE packets
    tlv_body = b"".join(bytes([i, 1, i + 10]) for i in range(1, 16))
    full_response = bytes([QUERY_GET_STATUS_VALUES, 0x00]) + tlv_body
    assert len(frame_ble_packet(full_response, max_packet_len=20)) > 1

    mock_client = _make_notifying_ble_client(QUERY_RSP, [full_response])
    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()

    raw = await client.query(bytes([QUERY_GET_STATUS_VALUES]))
    assert raw == full_response
    mock_client.start_notify.assert_awaited_once()
    mock_client.stop_notify.assert_awaited_once_with(QUERY_RSP)
    mock_client.write_gatt_char.assert_awaited_once_with(
        QUERY_REQ,
        frame_ble_packet(bytes([QUERY_GET_STATUS_VALUES]))[0],
        response=True,
    )


@pytest.mark.asyncio
async def test_ble_query_timeout_raises_transport_error_and_stops_notify():
    mock_client = AsyncMock()
    mock_client.is_connected = True
    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()

    with pytest.raises(TransportError, match="Timed out waiting for BLE response"):
        await client.query(bytes([QUERY_GET_STATUS_VALUES, 70]), timeout_sec=0.02)

    mock_client.stop_notify.assert_awaited_once_with(QUERY_RSP)


@pytest.mark.asyncio
async def test_ble_status_settings_and_available_settings():
    status_rsp = (
        bytes([QUERY_GET_STATUS_VALUES, 0x00])
        + bytes([2, 1, 4, 6, 1, 0, 10, 1, 1, 33, 1, 0, 34, 2, 0x04, 0xB0, 35, 2, 0x0E, 0x10])
        + bytes([54, 4])
        + (25_630_304).to_bytes(4, "big")
        + bytes([70, 1, 82, 96, 2])
        + (1000).to_bytes(2, "big")
        + bytes([97, 1, 2])
    )
    mock_client = _make_notifying_ble_client(QUERY_RSP, [status_rsp])
    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()

    cam_status = await client.get_camera_status()
    assert cam_status.battery_percent == 82
    assert cam_status.is_charging is True
    assert cam_status.is_recording is True
    assert cam_status.sd_status == "OK"
    assert cam_status.sd_remaining_mb == 25_029
    assert cam_status.sd_remaining_photos == 1200
    assert cam_status.sd_remaining_video_time_sec == 3600
    assert cam_status.current_mode == "Video"
    assert cam_status.current_preset == "2"
    assert cam_status.raw_status["70"] == 82

    # Check exact query payload used by get_camera_status
    written_payload = deframe_ble_packets([mock_client.write_gatt_char.call_args.args[1]])
    assert written_payload == bytes([QUERY_GET_STATUS_VALUES, *DEFAULT_STATUS_QUERY_IDS])

    # get_settings
    settings_rsp = bytes([QUERY_GET_SETTING_VALUES, 0x00, 2, 1, 9, 134, 1, 2])
    mock_client2 = _make_notifying_ble_client(QUERY_RSP, [settings_rsp])
    client2 = GoProBleClient(address="11:22:33:44:55:66", client=mock_client2)
    await client2.connect()
    assert await client2.get_settings([2, 134]) == {2: 9, 134: 2}

    # get_available_settings
    avail_rsp = bytes([QUERY_GET_AVAILABLE_SETTINGS, 0x00, 2, 1, 1, 2, 1, 9, 135, 1, 0, 135, 1, 3])
    mock_client3 = _make_notifying_ble_client(QUERY_RSP, [avail_rsp])
    client3 = GoProBleClient(address="11:22:33:44:55:66", client=mock_client3)
    await client3.connect()
    assert await client3.get_available_settings([2, 135]) == {2: [1, 9], 135: [0, 3]}

    # Non-zero status code raises CommandError
    err_rsp = bytes([QUERY_GET_SETTING_VALUES, 0x01])
    mock_client_err = _make_notifying_ble_client(QUERY_RSP, [err_rsp])
    client_err = GoProBleClient(address="11:22:33:44:55:66", client=mock_client_err)
    await client_err.connect()
    with pytest.raises(CommandError, match="status code 1"):
        await client_err.get_settings()


@pytest.mark.asyncio
async def test_ble_set_setting_ack_error_and_range_validation():
    mock_ok = _make_notifying_ble_client(SETTINGS_RSP, [bytes([135, 0])])
    client_ok = GoProBleClient(address="11:22:33:44:55:66", client=mock_ok)
    await client_ok.connect()

    await client_ok.set_setting(135, 3)
    mock_ok.write_gatt_char.assert_awaited_once_with(
        SETTINGS_REQ,
        frame_ble_packet(bytes([135, 1, 3]))[0],
        response=True,
    )
    mock_ok.stop_notify.assert_awaited_once_with(SETTINGS_RSP)

    mock_fail = _make_notifying_ble_client(SETTINGS_RSP, [bytes([135, 2])])
    client_fail = GoProBleClient(address="11:22:33:44:55:66", client=mock_fail)
    await client_fail.connect()
    with pytest.raises(CommandError, match="status code 2"):
        await client_fail.set_setting(135, 3)

    with pytest.raises(CommandError, match="out of 1-byte range"):
        await client_ok.set_setting(256, 1)
    with pytest.raises(CommandError, match="out of 1-byte range"):
        await client_ok.set_setting(2, -1)
    for bad_id in (True, 1.5, "1"):
        with pytest.raises(CommandError, match="must be an int"):
            await client_ok.set_setting(bad_id, 1)  # type: ignore[arg-type]
    for bad_val in (False, 2.5, "2"):
        with pytest.raises(CommandError, match="must be an int"):
            await client_ok.set_setting(2, bad_val)  # type: ignore[arg-type]

    mock_short = _make_notifying_ble_client(SETTINGS_RSP, [bytes([135])])
    client_short = GoProBleClient(address="11:22:33:44:55:66", client=mock_short)
    await client_short.connect()
    with pytest.raises(CommandError, match="expected at least 2 bytes"):
        await client_short.set_setting(135, 3)

    mock_mismatch = _make_notifying_ble_client(SETTINGS_RSP, [bytes([2, 0])])
    client_mismatch = GoProBleClient(address="11:22:33:44:55:66", client=mock_mismatch)
    await client_mismatch.connect()
    with pytest.raises(CommandError, match="response mismatch"):
        await client_mismatch.set_setting(135, 3)


@pytest.mark.asyncio
async def test_ble_concurrent_queries_are_serialized():
    import asyncio

    mock_client = AsyncMock()
    mock_client.is_connected = True
    callbacks = {}
    active_queries = 0
    max_active = 0

    async def fake_start_notify(uuid, cb):
        nonlocal active_queries, max_active
        active_queries += 1
        max_active = max(max_active, active_queries)
        assert uuid not in callbacks, "Concurrent start_notify race on same characteristic!"
        callbacks[uuid] = cb

    async def fake_stop_notify(uuid):
        nonlocal active_queries
        callbacks.pop(uuid, None)
        active_queries -= 1

    async def fake_write_gatt_char(uuid, data, response=True):
        payload = deframe_ble_packets([bytes(data)])
        op = payload[0]
        await asyncio.sleep(0.02)
        if op == QUERY_GET_STATUS_VALUES:
            rsp = bytes([QUERY_GET_STATUS_VALUES, 0x00, 70, 1, 91])
        else:
            rsp = bytes([QUERY_GET_SETTING_VALUES, 0x00, 2, 1, 12])
        cb = callbacks[QUERY_RSP]
        for pkt in frame_ble_packet(rsp, max_packet_len=20):
            cb(QUERY_RSP, bytearray(pkt))

    mock_client.start_notify.side_effect = fake_start_notify
    mock_client.stop_notify.side_effect = fake_stop_notify
    mock_client.write_gatt_char.side_effect = fake_write_gatt_char

    client = GoProBleClient(address="11:22:33:44:55:66", client=mock_client)
    await client.connect()

    status_res, settings_res = await asyncio.gather(
        client.get_status_values([70]),
        client.get_settings([2]),
    )
    assert max_active == 1
    assert status_res == {70: 91}
    assert settings_res == {2: 12}


@pytest.mark.asyncio
async def test_ble_query_opcode_mismatch_write_error_and_disconnect_cleanup():
    # Opcode mismatch in TLV response
    mock_mismatch = _make_notifying_ble_client(
        QUERY_RSP, [bytes([QUERY_GET_STATUS_VALUES, 0x00, 2, 1, 9])]
    )
    client_mismatch = GoProBleClient(address="11:22:33:44:55:66", client=mock_mismatch)
    await client_mismatch.connect()
    with pytest.raises(CommandError, match="response mismatch"):
        await client_mismatch.get_settings([2])

    # write_gatt_char failure wraps as TransportError and still calls stop_notify
    mock_write_err = AsyncMock()
    mock_write_err.is_connected = True
    mock_write_err.write_gatt_char.side_effect = RuntimeError("BLE write failed")
    mock_write_err.disconnect.side_effect = RuntimeError("disconnect failed")
    client_write_err = GoProBleClient(address="11:22:33:44:55:66", client=mock_write_err)
    await client_write_err.connect()
    with pytest.raises(TransportError, match="BLE write to"):
        await client_write_err.query(bytes([QUERY_GET_STATUS_VALUES, 70]))
    mock_write_err.stop_notify.assert_awaited_once_with(QUERY_RSP)

    # disconnect() clears _is_connected even when underlying disconnect raises
    with pytest.raises(RuntimeError, match="disconnect failed"):
        await client_write_err.disconnect()
    assert client_write_err._is_connected is False
