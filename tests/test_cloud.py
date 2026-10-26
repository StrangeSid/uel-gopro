import json
import stat
from unittest.mock import MagicMock
import pytest

from uel_gopro.cloud.client import (
    GoProCloudClient,
    load_cloud_auth,
    save_cloud_auth,
)
from uel_gopro.core.exceptions import CommandError, MediaError, TransportError


def test_save_and_load_cloud_auth(tmp_path):
    config_file = tmp_path / "sub" / "cloud.json"
    saved = save_cloud_auth("test-token-123", "user-456", config_path=config_file)
    assert saved == config_file
    assert config_file.is_file()

    with open(config_file) as f:
        data = json.load(f)
    assert data == {"auth_token": "test-token-123", "user_id": "user-456"}
    if hasattr(stat, "S_IMODE"):
        assert stat.S_IMODE(config_file.stat().st_mode) == 0o600

    loaded = load_cloud_auth(config_path=config_file)
    assert loaded == {"auth_token": "test-token-123", "user_id": "user-456"}


def test_load_cloud_auth_missing(tmp_path):
    missing_file = tmp_path / "does_not_exist.json"
    assert load_cloud_auth(config_path=missing_file) == {}


def test_client_init_from_config(tmp_path):
    config_file = tmp_path / "cloud.json"
    save_cloud_auth("token-abc", "user-xyz", config_path=config_file)

    client = GoProCloudClient(config_path=config_file)
    assert client.auth_token == "token-abc"
    assert client.user_id == "user-xyz"

    # Explicit parameters override config file
    client2 = GoProCloudClient(
        auth_token="override-token",
        user_id="override-user",
        config_path=config_file,
    )
    assert client2.auth_token == "override-token"
    assert client2.user_id == "override-user"


def test_list_media_missing_token():
    client = GoProCloudClient(auth_token="")
    with pytest.raises(TransportError, match="auth token is not configured"):
        client.list_media()


def test_list_media_paginated(monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")

    captured_requests = []

    class MockResponse:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code
            self.text = json.dumps(data)

        def json(self):
            return self._data

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers=None, params=None):
            captured_requests.append((url, headers, params))
            page = params.get("page", 1)
            if page == 1:
                return MockResponse(
                    {
                        "_embedded": {
                            "media": [
                                {"id": "med1", "filename": "GH010001.MP4", "file_size": 1024},
                                {"id": "med2", "filename": "GH010002.MP4", "file_size": 2048},
                            ]
                        }
                    }
                )
            return MockResponse({"_embedded": {"media": []}})

    monkeypatch.setattr("httpx.Client", MockHttpxClient)

    items = client.list_media(page=1, per_page=100)
    assert len(items) == 2
    assert items[0]["filename"] == "GH010001.MP4"
    assert items[1]["filename"] == "GH010002.MP4"

    assert len(captured_requests) == 1
    req_url, req_headers, req_params = captured_requests[0]
    assert req_url == "https://api.gopro.com/media/search"
    assert req_headers["Authorization"] == "Bearer test-token-999"
    assert req_params == {"page": 1, "per_page": 100}


def test_list_media_http_error(monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers=None, params=None):
            resp = MagicMock()
            resp.status_code = 401
            resp.text = "Unauthorized"
            return resp

    monkeypatch.setattr("httpx.Client", MockHttpxClient)
    with pytest.raises(CommandError, match="HTTP 401"):
        client.list_media(page=1)


def test_get_download_url(monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, headers=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "_embedded": {
                    "variations": [
                        {"label": "high_res_proxy_mp4", "url": "https://cdn.gopro.com/proxy.mp4"},
                        {"label": "source", "url": "https://cdn.gopro.com/source.mp4"},
                    ]
                }
            }
            return resp

    monkeypatch.setattr("httpx.Client", MockHttpxClient)
    url = client.get_download_url("test_media_id")
    assert url == "https://cdn.gopro.com/source.mp4"


def test_sync_all_downloads_and_skips_existing(tmp_path, monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")

    media_pages = {
        1: [
            {"id": "id1", "filename": "FILE1.MP4", "file_size": 10, "download_url": "https://cdn.example.com/1.mp4"},
            {"id": "id2", "filename": "FILE2.MP4", "file_size": 20, "download_url": "https://cdn.example.com/2.mp4"},
        ],
        2: [],
    }

    def mock_list_media(page=1, per_page=100):
        return media_pages.get(page, [])

    stream_call_count = 0

    class MockStreamResponse:
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code
            self.headers = {"content-length": str(len(content))}

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=65536):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, headers=None, follow_redirects=True):
            nonlocal stream_call_count
            stream_call_count += 1
            if "1.mp4" in url:
                return MockStreamResponse(b"1" * 10)
            elif "2.mp4" in url:
                return MockStreamResponse(b"2" * 20)
            return MockStreamResponse(b"")

    monkeypatch.setattr(client, "list_media", mock_list_media)
    monkeypatch.setattr("httpx.Client", MockHttpxClient)

    # First sync: downloads both files
    progress_calls = []

    def progress_cb(downloaded, total):
        progress_calls.append((downloaded, total))

    paths = client.sync_all(dest_dir=tmp_path, progress_callback=progress_cb)
    assert len(paths) == 2
    assert stream_call_count == 2
    assert (tmp_path / "FILE1.MP4").is_file()
    assert (tmp_path / "FILE2.MP4").is_file()
    assert (tmp_path / "FILE1.MP4").stat().st_size == 10
    assert (tmp_path / "FILE2.MP4").stat().st_size == 20
    assert not (tmp_path / "FILE1.MP4.partial").exists()
    assert not (tmp_path / "FILE2.MP4.partial").exists()
    assert len(progress_calls) >= 2

    # Second sync: files already exist with matching size, should skip
    stream_call_count = 0
    paths2 = client.sync_all(dest_dir=tmp_path)
    assert len(paths2) == 2
    assert stream_call_count == 0  # No network streams opened!


def test_download_media_file_resumes_partial(tmp_path, monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")
    target = tmp_path / "RESUME.MP4"
    partial = target.with_name("RESUME.MP4.partial")
    partial.write_bytes(b"12345")
    seen_range = {}

    class MockStreamResponse:
        status_code = 206
        headers = {"content-length": "5"}

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=65536):
            yield b"67890"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, headers=None, follow_redirects=True):
            seen_range["range"] = (headers or {}).get("Range")
            return MockStreamResponse()

    monkeypatch.setattr("httpx.Client", MockHttpxClient)
    out = client.download_media_file("https://cdn.example.com/resume.mp4", target, expected_size=10)
    assert out == target
    assert target.read_bytes() == b"1234567890"
    assert seen_range["range"] == "bytes=5-"
    assert not partial.exists()


def test_download_media_file_size_mismatch(tmp_path, monkeypatch):
    client = GoProCloudClient(auth_token="test-token-999")

    class MockStreamResponse:
        status_code = 200
        headers = {"content-length": "5"}

        def raise_for_status(self):
            pass

        def iter_bytes(self, chunk_size=65536):
            yield b"12345"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class MockHttpxClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def stream(self, method, url, headers=None, follow_redirects=True):
            return MockStreamResponse()

    monkeypatch.setattr("httpx.Client", MockHttpxClient)

    target = tmp_path / "mismatch.mp4"
    with pytest.raises(MediaError, match="does not match expected size"):
        client.download_media_file("https://mock.url", target, expected_size=100)

    assert not target.exists()
    assert not (tmp_path / "mismatch.mp4.partial").exists()
