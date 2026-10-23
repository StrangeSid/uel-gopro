from unittest.mock import MagicMock, patch
import pytest

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError, TransportError
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
    monkeypatch.setattr("uel_gopro.transport.usb.probe_camera_ip", lambda ip, **kw: ip == "172.20.150.51")

    cam = detect_usb_camera()
    assert cam is not None
    assert cam.ip_address == "172.20.150.51"
    assert cam.interface_name == "en7"


def test_rest_client_get_status(monkeypatch):
    mock_payload = {
        "status": {
            "2": 85,    # 85% battery
            "6": 0,     # not hot
            "8": 0,     # not encoding
            "10": 0,    # shutter not active
            "33": 0,    # SD OK
            "38": 52428800,  # 50GB remaining
            "43": 0,    # Video mode
            "49": 1,    # Charging
        }
    }

    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(client, "get_raw_state", lambda: mock_payload)

    status = client.get_status()
    assert status.connected is True
    assert status.battery_percent == 85
    assert status.is_charging is True
    assert status.is_recording is False
    assert status.sd_status == "OK"
    assert status.sd_remaining_mb == 51200
    assert status.current_mode == "Video"


def test_rest_client_media_list(monkeypatch):
    mock_payload = {
        "media": [
            {
                "d": "100GOPRO",
                "fs": [
                    {"n": "GX010042.MP4", "s": 4000000000, "mod": 1690000000},
                    {"n": "GOPR0043.JPG", "s": 5000000, "mod": 1690000050},
                ],
            }
        ]
    }

    client = GoProRestClient("172.20.150.51")
    monkeypatch.setattr(client, "_get", lambda endpoint, **kwargs: mock_payload)

def test_resolve_camera_usb(monkeypatch):
    from uel_gopro.transport.manager import resolve_camera
    from uel_gopro.core.models import CameraInfo, TransportType

    mock_cam = CameraInfo(ip_address="172.20.150.51", transport=TransportType.USB)
    monkeypatch.setattr("uel_gopro.transport.manager.detect_usb_camera", lambda **kw: mock_cam)

    info, client = resolve_camera()
    assert info.ip_address == "172.20.150.51"
    assert client.ip == "172.20.150.51"


def test_resolve_camera_not_found(monkeypatch):
    from uel_gopro.transport.manager import resolve_camera
    from uel_gopro.core.exceptions import CameraNotFoundError

    monkeypatch.setattr("uel_gopro.transport.manager.detect_usb_camera", lambda **kw: None)
    monkeypatch.setattr("uel_gopro.transport.manager.probe_camera_ip", lambda *a, **kw: False)

    with pytest.raises(CameraNotFoundError):
        resolve_camera()

