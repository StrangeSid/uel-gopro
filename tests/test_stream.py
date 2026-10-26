from unittest.mock import MagicMock

import pytest

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.core.exceptions import CommandError
from uel_gopro.stream.preview import build_player_command, launch_preview_stream
from uel_gopro.stream.webcam import get_webcam_status, start_webcam, stop_webcam


def test_build_player_command():
    mpv_cmd = build_player_command("mpv", "udp://@0.0.0.0:8554")
    assert mpv_cmd[0] == "mpv"
    assert "--no-cache" in mpv_cmd
    assert "udp://@0.0.0.0:8554" in mpv_cmd

    ffplay_cmd = build_player_command("ffplay", "udp://@0.0.0.0:8554")
    assert ffplay_cmd[0] == "ffplay"
    assert "nobuffer" in ffplay_cmd


def test_launch_preview_stream_no_player():
    client = MagicMock(spec=GoProRestClient)
    proc = launch_preview_stream(client, spawn_player=False)
    assert proc is None
    client.enable_wired_usb.assert_called_once_with(True)
    client.start_preview_stream.assert_called_once()


@pytest.mark.parametrize(
    "resolution,expected_code",
    [("1080p", 12), ("720p", 7), ("480p", 4)],
)
def test_webcam_resolution_codes(resolution, expected_code):
    client = MagicMock(spec=GoProRestClient)
    client.start_webcam.return_value = {"status": 0}
    start_webcam(client, resolution=resolution, fov="linear")
    client.start_webcam.assert_called_once_with(expected_code, 4)


@pytest.mark.parametrize(
    "fov,expected_code",
    [("wide", 0), ("narrow", 2), ("superview", 3), ("linear", 4)],
)
def test_webcam_fov_codes(fov, expected_code):
    client = MagicMock(spec=GoProRestClient)
    client.start_webcam.return_value = {"status": 0}
    start_webcam(client, resolution="1080p", fov=fov)
    client.start_webcam.assert_called_once_with(12, expected_code)


def test_webcam_rejects_invalid_options():
    client = MagicMock(spec=GoProRestClient)
    with pytest.raises(CommandError, match="Unsupported webcam resolution"):
        start_webcam(client, resolution="4k")
    with pytest.raises(CommandError, match="Unsupported webcam field of view"):
        start_webcam(client, fov="fisheye")


def test_webcam_stop_and_status():
    client = MagicMock(spec=GoProRestClient)
    client.stop_webcam.return_value = {"status": 0}
    client.get_webcam_status.return_value = {"status": 1}

    assert stop_webcam(client) == {"status": 0}
    assert get_webcam_status(client) == {"status": 1}
