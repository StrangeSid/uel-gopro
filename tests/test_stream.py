from unittest.mock import MagicMock
import pytest

from uel_gopro.api.rest import GoProRestClient
from uel_gopro.stream.preview import build_player_command, launch_preview_stream
from uel_gopro.stream.webcam import start_webcam, stop_webcam, get_webcam_status


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
    assert client._get.call_count == 2


def test_webcam_start_and_stop():
    client = MagicMock(spec=GoProRestClient)
    client._get.return_value = {"status": 0}

    res_start = start_webcam(client, resolution="1080p", fov="linear")
    assert res_start == {"status": 0}

    res_stop = stop_webcam(client)
    assert res_stop == {"status": 0}

    res_stat = get_webcam_status(client)
    assert res_stat == {"status": 0}
