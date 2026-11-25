import pytest

from uel_gopro.api.rest import (
    SETTING_ALIASES,
    GoProRestClient,
    parse_camera_status,
    resolve_setting_id,
)
from uel_gopro.core.exceptions import CameraNotFoundError, CommandError
from uel_gopro.core.models import MediaType, TransportType
from uel_gopro.transport.manager import resolve_camera
from uel_gopro.transport.usb import detect_usb_camera, probe_camera_ip


def test_probe_camera_ip_success(monkeypatch):
    class MockResponse:
        status_code = 200

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            assert "172.24.162.51:8080" in url
            return MockResponse()

    monkeypatch.setattr("httpx.Client", MockClient)
    assert probe_camera_ip("172.24.162.51") is True


def test_probe_camera_ip_failure(monkeypatch):
    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            import httpx

            raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr("httpx.Client", MockClient)
    assert probe_camera_ip("172.24.162.51") is False


def test_detect_usb_camera(monkeypatch):
    class MockSnic:
        def __init__(self, address, family):
            self.address = address
            self.family = family

    import socket

    mock_addrs = {
        "en7": [MockSnic("172.20.150.2", socket.AF_INET)],
        "lo0": [MockSnic("127.0.0.1", socket.AF_INET)],
    }
    monkeypatch.setattr("psutil.net_if_addrs", lambda: mock_addrs)
    monkeypatch.setattr(
        "uel_gopro.transport.usb.probe_camera_ip", lambda ip, **kw: ip == "172.20.150.51"
    )

    cam = detect_usb_camera()
    assert cam is not None
    assert cam.ip_address == "172.20.150.51"
    assert cam.interface_name == "en7"


def test_rest_client_get_status_matches_official_ids(monkeypatch):
    """Status IDs and values mirror a captured OpenGoPro camera state."""
    mock_payload = {
        "status": {
            "1": 1,
            "2": 4,  # Internal Battery Bars: 4 = charging
            "6": 0,  # Overheating
            "8": 0,  # Busy
            "10": 0,  # Encoding
            "29": "",  # Connected Wi-Fi SSID (string; must not crash)
            "33": 0,  # Primary storage: OK
            "34": 1814,  # Remaining photos
            "35": 2954,  # Remaining video time (seconds)
            "54": 25_630_304,  # SD card remaining (KB)
            "70": 36,  # Internal battery percentage
            "96": 1000,  # Preset group: Video
            "97": 2,  # Preset ID
        }
    }

    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(client, "get_raw_state", lambda: mock_payload)

    status = client.get_status()
    assert status.connected is True
    assert status.battery_bars == 4
    assert status.battery_percent == 36
    assert status.is_charging is True
    assert status.is_recording is False
    assert status.sd_status == "OK"
    assert status.sd_remaining_mb == 25_029
    assert status.sd_remaining_photos == 1814
    assert status.sd_remaining_video_time_sec == 2954
    assert status.current_mode == "Video"
    assert status.current_preset == "2"


def test_rest_client_get_status_bars_fallback(monkeypatch):
    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(client, "get_raw_state", lambda: {"status": {"2": 2, "33": 2}})

    status = client.get_status()
    assert status.battery_percent == 66
    assert status.battery_bars == 2
    assert status.is_charging is False
    assert status.sd_status == "MISSING"
    assert status.current_mode == "Unknown"


def test_rest_client_set_setting_uses_option_parameter(monkeypatch):
    client = GoProRestClient("172.20.150.51")
    captured = {}

    def fake_get(endpoint, params=None):
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {}

    monkeypatch.setattr(client, "_get", fake_get)
    client.set_setting(3, 5)
    assert captured["endpoint"] == "/gopro/camera/setting"
    assert captured["params"] == {"setting": 3, "option": 5}


def test_rest_client_camera_info(monkeypatch):
    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(
        client,
        "_get",
        lambda endpoint, params=None: {
            "model_name": "HERO12 Black",
            "firmware_version": "H23.01.01.10.00",
            "serial_number": "C3501324645504",
        },
    )
    info = client.get_camera_info()
    assert info["model_name"] == "HERO12 Black"


def test_rest_client_camera_info_gpcontrol_fallback(monkeypatch):
    client = GoProRestClient("172.21.108.51")
    calls = []

    def fake_get(endpoint, params=None):
        calls.append(endpoint)
        if endpoint == "/gopro/camera/info":
            raise CommandError("HTTP 404 for /gopro/camera/info")
        if endpoint == "/gp/gpControl/info":
            return {
                "info": {
                    "model_number": 57,
                    "model_name": "HERO10 Black",
                    "firmware_version": "H21.01.01.62.00",
                    "serial_number": "C3461326122108",
                    "ap_ssid": "GP26122108",
                }
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(client, "_get", fake_get)
    info = client.get_camera_info()
    assert calls == ["/gopro/camera/info", "/gp/gpControl/info"]
    assert info["model_number"] == 57
    assert info["model_name"] == "HERO10 Black"
    assert info["firmware_version"] == "H21.01.01.62.00"
    assert info["serial_number"] == "C3461326122108"
    assert info["ap_ssid"] == "GP26122108"


def test_rest_client_camera_info_reraises_original_error_when_fallback_fails(monkeypatch):
    client = GoProRestClient("172.21.108.51")

    def fake_get(endpoint, params=None):
        if endpoint == "/gopro/camera/info":
            raise CommandError("HTTP 404 original")
        raise CommandError("HTTP 500 fallback")

    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(CommandError, match="HTTP 404 original"):
        client.get_camera_info()


def test_rest_client_camera_info_non_dict_and_none_field_fallbacks(monkeypatch):
    client = GoProRestClient("172.21.108.51")

    def fake_non_dict(endpoint, params=None):
        if endpoint == "/gopro/camera/info":
            raise CommandError("HTTP 404")
        return ["unexpected-list"]

    monkeypatch.setattr(client, "_get", fake_non_dict)
    assert client.get_camera_info() == {}

    def fake_none_fields(endpoint, params=None):
        if endpoint == "/gopro/camera/info":
            raise CommandError("HTTP 404")
        return {
            "info": {
                "model_name": None,
                "model": "HERO10 Black",
                "firmware_version": None,
                "firmware": "H21.01.01.62.00",
                "serial_number": None,
                "serial": "C3461326122108",
                "model_number": None,
                "model_id": 57,
            }
        }

    monkeypatch.setattr(client, "_get", fake_none_fields)
    info = client.get_camera_info()
    assert info["model_name"] == "HERO10 Black"
    assert info["firmware_version"] == "H21.01.01.62.00"
    assert info["serial_number"] == "C3461326122108"
    assert info["model_number"] == 57


def test_rest_client_get_case_insensitive_content_type(monkeypatch):
    class MockResponse:
        status_code = 200
        headers = {"content-type": "Application/JSON; charset=utf-8"}

        def json(self):
            return {"ok": True}

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, params=None):
            return MockResponse()

    monkeypatch.setattr("httpx.Client", MockHttpxClient)
    client = GoProRestClient("172.20.150.51")
    assert client._get("/gopro/camera/state") == {"ok": True}


def test_parse_camera_status_int_and_str_keys_and_new_aliases():
    assert SETTING_ALIASES["anti_flicker"] == 134
    assert SETTING_ALIASES["hypersmooth"] == 135
    assert resolve_setting_id("anti_flicker") == 134
    assert resolve_setting_id("hypersmooth") == 135

    status_from_ints = parse_camera_status(
        {
            2: 3,
            6: 1,
            10: 1,
            33: 0,
            34: 500,
            35: 1200,
            54: 10240,
            70: 88,
            96: 1000,
            97: 4,
        }
    )
    assert status_from_ints.battery_percent == 88
    assert status_from_ints.system_hot is True
    assert status_from_ints.is_recording is True
    assert status_from_ints.sd_remaining_mb == 10
    assert status_from_ints.current_mode == "Video"
    assert status_from_ints.current_preset == "4"
    assert status_from_ints.raw_status["70"] == 88

    status_from_strs = parse_camera_status({"70": "42", "33": "0", "96": "1001"})
    assert status_from_strs.battery_percent == 42
    assert status_from_strs.current_mode == "Photo"
    assert status_from_strs.raw_status["96"] == "1001"


def test_rest_client_media_list(monkeypatch):
    mock_payload = {
        "media": [
            {
                "d": "100GOPRO",
                "fs": [
                    {"n": "GX010042.MP4", "s": "4000000000", "mod": "1690000000"},
                    {"n": "GOPR0043.JPG", "s": "5000000", "mod": "1690000050"},
                ],
            }
        ]
    }

    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(client, "_get", lambda endpoint, params=None: mock_payload)

    items = client.get_media_list()
    assert len(items) == 2
    video = items[0]
    assert video.filename == "GX010042.MP4"
    assert video.size_bytes == 4_000_000_000
    assert video.media_type == MediaType.VIDEO
    assert video.base_id == "0042"
    assert video.download_url_path == "/videos/DCIM/100GOPRO/GX010042.MP4"
    photo = items[1]
    assert photo.media_type == MediaType.PHOTO
    assert photo.base_id == ""


def test_resolve_camera_usb(monkeypatch):
    from uel_gopro.core.models import CameraInfo

    mock_cam = CameraInfo(ip_address="172.20.150.51", transport=TransportType.USB)
    monkeypatch.setattr("uel_gopro.transport.manager.detect_usb_camera", lambda **kw: mock_cam)

    info, client = resolve_camera()
    assert info.ip_address == "172.20.150.51"
    assert client.ip == "172.20.150.51"


def test_resolve_camera_manual_ip(monkeypatch):
    monkeypatch.setattr("uel_gopro.transport.manager.probe_camera_ip", lambda *a, **kw: True)
    info, client = resolve_camera(target_ip="192.168.1.50")
    assert info.transport == TransportType.MANUAL
    assert client.ip == "192.168.1.50"


def test_resolve_camera_not_found(monkeypatch):
    monkeypatch.setattr("uel_gopro.transport.manager.detect_usb_camera", lambda **kw: None)
    monkeypatch.setattr("uel_gopro.transport.manager.probe_camera_ip", lambda *a, **kw: False)

    with pytest.raises(CameraNotFoundError):
        resolve_camera()
