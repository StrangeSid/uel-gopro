from unittest.mock import MagicMock, patch
from pathlib import Path
import pytest

from uel_gopro.transport.mtp import MtpClient, is_mtp_available


def test_is_mtp_available():
    # Verify boolean return
    res = is_mtp_available()
    assert isinstance(res, bool)


def test_mtp_detect_camera_mock(monkeypatch):
    if not is_mtp_available():
        pytest.skip("ImageCaptureCore not available on this platform")

    client = MtpClient()
    mock_cam = MagicMock()
    mock_cam.name.return_value = "HERO10 BLACK"
    monkeypatch.setattr(client, "_get_camera", lambda timeout_sec=2.0: mock_cam)

    info = client.detect_camera()
    assert info is not None
    assert "HERO10" in info.model_name
    assert info.transport.value == "mtp"


def test_mtp_list_media_mock(monkeypatch):
    if not is_mtp_available():
        pytest.skip("ImageCaptureCore not available on this platform")

    client = MtpClient()
    mock_file1 = MagicMock()
    mock_file1.name.return_value = "GX010042.MP4"
    mock_file1.fileSize.return_value = 104857600

    mock_file2 = MagicMock()
    mock_file2.name.return_value = "GOPR0043.JPG"
    mock_file2.fileSize.return_value = 5242880

    mock_cam = MagicMock()
    mock_cam.mediaFiles.return_value = [mock_file1, mock_file2]

    monkeypatch.setattr(client, "_get_camera", lambda timeout_sec=2.0: mock_cam)
    monkeypatch.setattr(client, "_open_session", lambda timeout_sec=4.0: True)

    items = client.list_media()
    assert len(items) == 2
    assert items[0].filename == "GX010042.MP4"
    assert items[0].media_type.value == "video"
    assert items[1].filename == "GOPR0043.JPG"
    assert items[1].media_type.value == "photo"


def test_mtp_download_file_mock(tmp_path: Path, monkeypatch):
    if not is_mtp_available():
        pytest.skip("ImageCaptureCore not available on this platform")

    client = MtpClient()
    mock_file = MagicMock()
    mock_file.name.return_value = "GX010042.MP4"

    mock_cam = MagicMock()
    mock_cam.mediaFiles.return_value = [mock_file]

    def mock_download(target, options, delegate, selector, ctx):
        dest_file = tmp_path / "GX010042.MP4"
        dest_file.write_bytes(b"dummy video data")
        delegate.finished = True
        delegate.error = None

    mock_cam.requestDownloadFile_options_downloadDelegate_didDownloadSelector_contextInfo_ = mock_download
    monkeypatch.setattr(client, "_get_camera", lambda timeout_sec=2.0: mock_cam)
    monkeypatch.setattr(client, "_open_session", lambda timeout_sec=4.0: True)

    out = client.download_file("GX010042.MP4", dest_dir=tmp_path)
    assert out.exists()
    assert out.name == "GX010042.MP4"
    assert out.read_bytes() == b"dummy video data"
