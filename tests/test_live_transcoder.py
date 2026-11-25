from __future__ import annotations

import io
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import pytest

from uel_gopro.core.exceptions import CommandError
from uel_gopro.stream.preview import DEFAULT_STREAM_URL
from uel_gopro.stream.transcoder import (
    JPEG_EOI,
    JPEG_SOI,
    MAX_BUFFER_BYTES,
    MjpegStreamTranscoder,
    build_mjpeg_ffmpeg_command,
    extract_jpeg_frames,
)


def _make_jpeg(payload: bytes) -> bytes:
    return JPEG_SOI + payload + JPEG_EOI


class _PipeFakeProcess:
    """Fake subprocess backed by an OS pipe for realistic blocking read/EOF/stop tests."""

    def __init__(
        self,
        stderr_data: bytes = b"",
        returncode: Optional[int] = 1,
    ) -> None:
        r_fd, w_fd = os.pipe()
        self.stdout = os.fdopen(r_fd, "rb")
        self._write_fd: Optional[int] = w_fd
        self._write_lock = threading.Lock()
        self.stderr = io.BytesIO(stderr_data)
        self.stdin = None
        self.returncode: Optional[int] = None
        self._exit_code = returncode
        self.terminated = False

    def write_chunk(self, data: bytes) -> None:
        with self._write_lock:
            if self._write_fd is not None:
                os.write(self._write_fd, data)

    def close_stdout(self, returncode: Optional[int] = None) -> None:
        with self._write_lock:
            if self._write_fd is not None:
                os.close(self._write_fd)
                self._write_fd = None
            if returncode is not None:
                self.returncode = returncode
            elif self.returncode is None:
                self.returncode = self._exit_code

    def poll(self) -> Optional[int]:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.close_stdout(self._exit_code)

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        if self.returncode is None:
            self.returncode = self._exit_code
        return self.returncode


def test_build_mjpeg_ffmpeg_command_defaults_and_udp_params() -> None:
    cmd = build_mjpeg_ffmpeg_command()
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-fflags") + 1] == "+nobuffer+discardcorrupt"
    assert cmd[cmd.index("-flags") + 1] == "low_delay"
    assert cmd[cmd.index("-max_delay") + 1] == "0"
    assert cmd[cmd.index("-analyzeduration") + 1] == "100000"
    assert cmd[cmd.index("-probesize") + 1] == "65536"
    i_idx = cmd.index("-i")
    assert cmd[i_idx + 1] == f"{DEFAULT_STREAM_URL}?overrun_nonfatal=1&fifo_size=5570"
    # Single-threaded decode before -i and single-threaded MJPEG encode after -an
    assert cmd[cmd.index("-threads") + 1] == "1"
    an_idx = cmd.index("-an")
    assert cmd[an_idx + 1 : an_idx + 3] == ["-threads", "1"]
    assert cmd[cmd.index("-fps_mode") + 1] == "passthrough"
    assert cmd[cmd.index("-strict") + 1] == "unofficial"
    assert cmd[cmd.index("-q:v") + 1] == "5"
    assert cmd[cmd.index("-flush_packets") + 1] == "1"
    assert "-vf" not in cmd
    assert not any(arg.startswith("fps=") for arg in cmd)
    assert cmd[-3:] == ["-f", "mjpeg", "pipe:1"]


def test_build_mjpeg_ffmpeg_command_preserves_existing_query_and_non_udp() -> None:
    udp_with_query = "udp://@0.0.0.0:8554?fifo_size=1024"
    cmd_udp = build_mjpeg_ffmpeg_command(
        stream_url=udp_with_query,
        ffmpeg_path="/usr/local/bin/ffmpeg",
        fps=30,
        quality=3,
    )
    assert cmd_udp[0] == "/usr/local/bin/ffmpeg"
    assert cmd_udp[cmd_udp.index("-i") + 1] == udp_with_query
    assert cmd_udp[cmd_udp.index("-fps_mode") + 1] == "passthrough"
    assert cmd_udp[cmd_udp.index("-q:v") + 1] == "3"

    non_udp = "/tmp/sample.ts"
    cmd_file = build_mjpeg_ffmpeg_command(stream_url=non_udp)
    assert cmd_file[cmd_file.index("-i") + 1] == non_udp


@pytest.mark.parametrize("bad_fps", [0, -5, 61, True, False, "24"])
def test_build_mjpeg_ffmpeg_command_invalid_fps(bad_fps: Any) -> None:
    with pytest.raises(CommandError):
        build_mjpeg_ffmpeg_command(fps=bad_fps)


@pytest.mark.parametrize("bad_quality", [1, 0, 32, True, False, "5"])
def test_build_mjpeg_ffmpeg_command_invalid_quality(bad_quality: Any) -> None:
    with pytest.raises(CommandError):
        build_mjpeg_ffmpeg_command(quality=bad_quality)


@pytest.mark.parametrize("bad_str", ["", "   "])
def test_build_mjpeg_ffmpeg_command_empty_strings(bad_str: str) -> None:
    with pytest.raises(CommandError):
        build_mjpeg_ffmpeg_command(stream_url=bad_str)
    with pytest.raises(CommandError):
        build_mjpeg_ffmpeg_command(ffmpeg_path=bad_str)


def test_extract_jpeg_frames_single_and_multiple_with_noise() -> None:
    f1 = _make_jpeg(b"frame-one")
    f2 = _make_jpeg(b"frame-two")
    buf = bytearray(b"junk-prefix" + f1 + b"mid-noise" + f2)

    frames = extract_jpeg_frames(buf)
    assert frames == [f1, f2]
    assert len(buf) == 0


def test_extract_jpeg_frames_split_across_chunks_and_markers() -> None:
    f1 = _make_jpeg(b"alpha")
    f2 = _make_jpeg(b"beta")

    # Split SOI across chunk 1 and chunk 2, split EOI across chunk 3 and chunk 4.
    buf = bytearray()
    buf.extend(b"noise\xff")
    assert extract_jpeg_frames(buf) == []
    assert bytes(buf) == b"\xff"

    buf.extend(b"\xd8alpha\xff")
    assert extract_jpeg_frames(buf) == []
    assert bytes(buf) == b"\xff\xd8alpha\xff"

    buf.extend(b"\xd9extra\xff\xd8be")
    assert extract_jpeg_frames(buf) == [f1]
    assert bytes(buf) == b"\xff\xd8be"

    buf.extend(b"ta\xff\xd9")
    assert extract_jpeg_frames(buf) == [f2]
    assert len(buf) == 0


def test_extract_jpeg_frames_discards_noise_and_clears_oversized_buffer() -> None:
    noise_only = bytearray(b"abcd1234")
    assert extract_jpeg_frames(noise_only) == []
    assert len(noise_only) == 0

    oversized_incomplete = bytearray(JPEG_SOI + b"x" * MAX_BUFFER_BYTES)
    assert len(oversized_incomplete) > MAX_BUFFER_BYTES
    assert extract_jpeg_frames(oversized_incomplete) == []
    assert len(oversized_incomplete) == 0


def test_transcoder_validates_params_and_missing_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(CommandError):
        MjpegStreamTranscoder(fps=0)
    with pytest.raises(CommandError):
        MjpegStreamTranscoder(quality=99)

    monkeypatch.setattr("uel_gopro.stream.transcoder.shutil.which", lambda _: None)
    transcoder = MjpegStreamTranscoder(ffmpeg_path="missing-ffmpeg")
    with pytest.raises(CommandError, match="FFmpeg binary not found"):
        transcoder.start()


def test_transcoder_stop_before_start_and_idempotent_start() -> None:
    created: list[_PipeFakeProcess] = []

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        proc = _PipeFakeProcess()
        created.append(proc)
        return proc

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    assert transcoder.fps == 30
    assert transcoder.read_chunk_size == 8192
    initial_status = transcoder.status()
    assert initial_status == {
        "running": False,
        "stream_url": DEFAULT_STREAM_URL,
        "has_frame": False,
        "frame_seq": 0,
        "last_frame_age_sec": None,
        "error": None,
    }
    assert transcoder.get_latest_frame() is None

    # Safe stop before start
    transcoder.stop()
    assert transcoder.status()["running"] is False

    transcoder.start()
    transcoder.start()  # idempotent
    try:
        deadline = time.monotonic() + 2.0
        while not created and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(created) == 1
        assert transcoder.status()["running"] is True
    finally:
        transcoder.stop()

    assert transcoder.status()["running"] is False


def test_transcoder_multi_consumer_fanout_and_clean_stop() -> None:
    proc = _PipeFakeProcess()
    spawned = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        spawned.set()
        return proc

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    c1_done = threading.Event()
    c2_done = threading.Event()
    try:
        assert spawned.wait(timeout=2.0)

        c1_frames: list[bytes] = []
        c2_frames: list[bytes] = []

        def run_consumer(out: list[bytes], done: threading.Event) -> None:
            try:
                for frame in transcoder.iter_frames(timeout_sec=10.0):
                    out.append(frame)
            finally:
                done.set()

        t1 = threading.Thread(target=run_consumer, args=(c1_frames, c1_done), daemon=True)
        t2 = threading.Thread(target=run_consumer, args=(c2_frames, c2_done), daemon=True)
        t1.start()
        t2.start()

        f1 = _make_jpeg(b"frame-1")
        f2 = _make_jpeg(b"frame-2")
        proc.write_chunk(f1)

        deadline = time.monotonic() + 2.0
        while (len(c1_frames) < 1 or len(c2_frames) < 1) and time.monotonic() < deadline:
            time.sleep(0.01)

        proc.write_chunk(f2)
        deadline = time.monotonic() + 2.0
        while (len(c1_frames) < 2 or len(c2_frames) < 2) and time.monotonic() < deadline:
            time.sleep(0.01)

        assert transcoder.get_latest_frame() == f2
        status = transcoder.status()
        assert status["running"] is True
        assert status["has_frame"] is True
        assert status["frame_seq"] >= 2
        assert status["last_frame_age_sec"] is not None
        assert status["last_frame_age_sec"] >= 0.0
        assert status["error"] is None

        assert f1 in c1_frames and f2 in c1_frames
        assert f1 in c2_frames and f2 in c2_frames
    finally:
        # stop() must unblock blocked iter_frames() consumers immediately (well below timeout_sec=10.0).
        t0 = time.monotonic()
        transcoder.stop()

    assert c1_done.wait(timeout=1.5)
    assert c2_done.wait(timeout=1.5)
    assert time.monotonic() - t0 < 2.0
    assert transcoder.status()["running"] is False


def test_transcoder_auto_restart_captures_stderr_and_recovers() -> None:
    p1 = _PipeFakeProcess(stderr_data=b"udp bind error: temporary failure\n", returncode=1)
    p2 = _PipeFakeProcess(returncode=0)
    processes = [p1, p2]
    spawn_count = 0
    second_spawned = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        nonlocal spawn_count
        idx = spawn_count
        spawn_count += 1
        if idx == 1:
            second_spawned.set()
        return processes[min(idx, len(processes) - 1)]

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        # Simulate first process failing with EOF
        p1.close_stdout(returncode=1)

        deadline = time.monotonic() + 2.0
        saw_error = False
        while time.monotonic() < deadline:
            err = transcoder.status()["error"]
            if err and "udp bind error" in err:
                saw_error = True
                break
            time.sleep(0.01)
        assert saw_error

        assert second_spawned.wait(timeout=2.0)
        recovered_frame = _make_jpeg(b"recovered")
        p2.write_chunk(recovered_frame)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if transcoder.get_latest_frame() == recovered_frame:
                break
            time.sleep(0.01)

        assert transcoder.get_latest_frame() == recovered_frame
        assert transcoder.status()["error"] is None
    finally:
        transcoder.stop()


def test_transcoder_consumer_stop_event_only_stops_that_consumer() -> None:
    proc = _PipeFakeProcess()
    transcoder = MjpegStreamTranscoder(
        popen_factory=lambda cmd, **kwargs: proc,
        restart_delay_sec=0.05,
    )
    transcoder.start()
    try:
        stop_ev = threading.Event()
        received: list[bytes] = []
        done = threading.Event()

        def consume() -> None:
            try:
                for frame in transcoder.iter_frames(stop_event=stop_ev, timeout_sec=0.05):
                    received.append(frame)
            finally:
                done.set()

        t = threading.Thread(target=consume, daemon=True)
        t.start()

        f1 = _make_jpeg(b"only-one")
        proc.write_chunk(f1)
        deadline = time.monotonic() + 2.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)

        stop_ev.set()
        assert done.wait(timeout=1.0)
        assert received == [f1]
        assert transcoder.status()["running"] is True
    finally:
        transcoder.stop()


def test_transcoder_spawn_error_recovery_and_iter_after_stop() -> None:
    p_ok = _PipeFakeProcess()
    attempts = 0
    second_attempt = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("boom on spawn")
        second_attempt.set()
        return p_ok

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        deadline = time.monotonic() + 2.0
        saw_spawn_err = False
        while time.monotonic() < deadline:
            err = transcoder.status()["error"]
            if err and "boom on spawn" in err:
                saw_spawn_err = True
                break
            time.sleep(0.01)
        assert saw_spawn_err

        assert second_attempt.wait(timeout=2.0)
        frame = _make_jpeg(b"after-spawn-error")
        p_ok.write_chunk(frame)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if transcoder.get_latest_frame() == frame:
                break
            time.sleep(0.01)
        assert transcoder.get_latest_frame() == frame
        assert transcoder.status()["error"] is None
    finally:
        transcoder.stop()

    # After stop(), iter_frames() exits immediately without yielding or blocking.
    assert list(transcoder.iter_frames(timeout_sec=5.0)) == []


@pytest.mark.parametrize(
    "bad_delay",
    [-0.1, True, False, "1.0", float("nan"), float("inf"), float("-inf")],
)
def test_transcoder_invalid_restart_delay_sec(bad_delay: Any) -> None:
    with pytest.raises(CommandError):
        MjpegStreamTranscoder(restart_delay_sec=bad_delay)


@pytest.mark.parametrize("bad_chunk", [0, -1024, True, False, "4096", 1.5])
def test_transcoder_invalid_read_chunk_size(bad_chunk: Any) -> None:
    with pytest.raises(CommandError):
        MjpegStreamTranscoder(read_chunk_size=bad_chunk)


def test_transcoder_os_pipe_stderr_draining_prevents_deadlock_and_captures_tail() -> None:
    class _DualPipeFakeProcess(_PipeFakeProcess):
        def __init__(self) -> None:
            super().__init__(returncode=1)
            err_r, err_w = os.pipe()
            self.stderr = os.fdopen(err_r, "rb")
            self._err_write_fd: Optional[int] = err_w
            self._err_lock = threading.Lock()

        def write_stderr(self, data: bytes) -> None:
            with self._err_lock:
                if self._err_write_fd is not None:
                    os.write(self._err_write_fd, data)

        def close_stderr(self) -> None:
            with self._err_lock:
                if self._err_write_fd is not None:
                    os.close(self._err_write_fd)
                    self._err_write_fd = None

        def terminate(self) -> None:
            self.close_stderr()
            super().terminate()

    p1 = _DualPipeFakeProcess()
    p2 = _PipeFakeProcess()
    processes = [p1, p2]
    idx = 0
    second_started = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        nonlocal idx
        proc = processes[min(idx, len(processes) - 1)]
        if idx == 1:
            second_started.set()
        idx += 1
        return proc

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        # Write >96KB to OS stderr pipe in a writer thread (exceeds standard 64KB pipe capacity).
        # Without continuous draining, this write would deadlock before stdout frames arrive.
        writer_done = threading.Event()

        def spam_stderr() -> None:
            try:
                chunk = b"noisy-warning-line\n" * 512  # ~9.7KB per write
                for _ in range(10):
                    p1.write_stderr(chunk)
                p1.write_stderr(b"FINAL_STDERR_TAIL_MARKER\n")
            finally:
                writer_done.set()

        w_thread = threading.Thread(target=spam_stderr, daemon=True)
        w_thread.start()
        assert writer_done.wait(timeout=2.0)

        frame = _make_jpeg(b"still-streaming")
        p1.write_chunk(frame)
        deadline = time.monotonic() + 2.0
        while transcoder.get_latest_frame() != frame and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transcoder.get_latest_frame() == frame

        # Close p1 pipes to simulate crash and confirm stderr tail is surfaced.
        p1.close_stderr()
        p1.close_stdout(returncode=1)

        deadline = time.monotonic() + 2.0
        saw_tail = False
        while time.monotonic() < deadline:
            err = transcoder.status()["error"]
            if err and "FINAL_STDERR_TAIL_MARKER" in err:
                saw_tail = True
                break
            time.sleep(0.01)
        assert saw_tail
        assert second_started.wait(timeout=2.0)
    finally:
        p1.close_stderr()
        transcoder.stop()


def test_transcoder_timeout_expired_escalates_to_kill() -> None:
    class _StubbornProcess(_PipeFakeProcess):
        def __init__(self) -> None:
            super().__init__()
            self.killed = False

        def terminate(self) -> None:
            # Simulate a process ignoring SIGTERM so wait() times out.
            self.terminated = True

        def wait(self, timeout: Optional[float] = None) -> Optional[int]:
            if not self.killed:
                raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout or 1.0)
            self.returncode = -9
            return -9

        def kill(self) -> None:
            self.killed = True
            self.close_stdout(-9)

    stubborn = _StubbornProcess()
    spawned = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> _StubbornProcess:
        spawned.set()
        return stubborn

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        assert spawned.wait(timeout=2.0)
    finally:
        transcoder.stop()

    assert stubborn.terminated is True
    assert stubborn.killed is True
    assert transcoder.status()["running"] is False


def test_transcoder_handles_stdout_none_and_recovers() -> None:
    class _NoStdoutProcess:
        stdout = None
        stderr = io.BytesIO(b"")
        stdin = None
        returncode = 1

        def poll(self) -> int:
            return 1

        def terminate(self) -> None:
            pass

        def wait(self, timeout: Optional[float] = None) -> int:
            return 1

    p2 = _PipeFakeProcess()
    attempts = 0
    second_spawned = threading.Event()

    def factory(cmd: list[str], **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _NoStdoutProcess()
        second_spawned.set()
        return p2

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        deadline = time.monotonic() + 2.0
        saw_no_stdout = False
        while time.monotonic() < deadline:
            err = transcoder.status()["error"]
            if err and "no stdout pipe" in err:
                saw_no_stdout = True
                break
            time.sleep(0.01)
        assert saw_no_stdout

        assert second_spawned.wait(timeout=2.0)
        f = _make_jpeg(b"recovered-after-none")
        p2.write_chunk(f)
        deadline = time.monotonic() + 2.0
        while transcoder.get_latest_frame() != f and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transcoder.get_latest_frame() == f
    finally:
        transcoder.stop()


def test_transcoder_restart_clears_stale_frame_and_concurrent_stop_start() -> None:
    terminating = threading.Event()
    allow_terminate = threading.Event()

    class _SlowStopProcess(_PipeFakeProcess):
        def terminate(self) -> None:
            terminating.set()
            allow_terminate.wait(timeout=2.0)
            super().terminate()

    procs: list[_PipeFakeProcess] = []
    spawned_events = [threading.Event(), threading.Event()]

    def factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        idx = len(procs)
        proc: _PipeFakeProcess = _SlowStopProcess() if idx == 0 else _PipeFakeProcess()
        procs.append(proc)
        if idx < len(spawned_events):
            spawned_events[idx].set()
        return proc

    transcoder = MjpegStreamTranscoder(popen_factory=factory, restart_delay_sec=0.05)
    transcoder.start()
    try:
        assert spawned_events[0].wait(timeout=2.0)
        f1 = _make_jpeg(b"session-1")
        procs[0].write_chunk(f1)

        deadline = time.monotonic() + 2.0
        while transcoder.get_latest_frame() != f1 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transcoder.get_latest_frame() == f1
        assert transcoder.status()["has_frame"] is True

        # Start stop() first and wait until it is mid-shutdown inside _lifecycle_lock,
        # then invoke start() concurrently. Lifecycle lock ensures start() waits for
        # shutdown to finish and launches session 2 instead of returning early.
        stop_thread = threading.Thread(target=transcoder.stop, daemon=True)
        stop_thread.start()
        assert terminating.wait(timeout=2.0)

        start_thread = threading.Thread(target=transcoder.start, daemon=True)
        start_thread.start()
        time.sleep(0.02)
        allow_terminate.set()

        stop_thread.join(timeout=2.0)
        start_thread.join(timeout=2.0)

        assert spawned_events[1].wait(timeout=2.0)
        # Before session 2 emits a frame, stale session-1 frame/timestamp must be cleared.
        st = transcoder.status()
        assert st["running"] is True
        assert st["has_frame"] is False
        assert st["last_frame_age_sec"] is None
        assert transcoder.get_latest_frame() is None

        f2 = _make_jpeg(b"session-2")
        procs[1].write_chunk(f2)
        deadline = time.monotonic() + 2.0
        while transcoder.get_latest_frame() != f2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transcoder.get_latest_frame() == f2
    finally:
        allow_terminate.set()
        transcoder.stop()


def test_transcoder_iter_frames_clamps_non_positive_timeout() -> None:
    proc = _PipeFakeProcess()
    transcoder = MjpegStreamTranscoder(
        popen_factory=lambda cmd, **kwargs: proc,
        restart_delay_sec=0.05,
    )
    transcoder.start()
    try:
        stop_ev = threading.Event()
        received: list[bytes] = []
        done = threading.Event()

        def consume() -> None:
            try:
                for frame in transcoder.iter_frames(stop_event=stop_ev, timeout_sec=0):
                    received.append(frame)
            finally:
                done.set()

        t = threading.Thread(target=consume, daemon=True)
        t.start()
        time.sleep(0.08)
        stop_ev.set()
        assert done.wait(timeout=1.0)
        assert received == []
    finally:
        transcoder.stop()


def test_transcoder_fps_pacing_low_fps_drops_excess_and_high_fps_passes_through() -> None:
    # When fps < 30 (e.g. fps=2 -> 0.5s min_frame_interval), rapid intermediate frames
    # are dropped without blocking while the first and post-interval frames publish.
    proc_slow = _PipeFakeProcess()
    spawned_slow = threading.Event()

    def slow_factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        spawned_slow.set()
        return proc_slow

    slow_transcoder = MjpegStreamTranscoder(
        fps=2,
        popen_factory=slow_factory,
        restart_delay_sec=0.05,
    )
    slow_transcoder.start()
    try:
        assert spawned_slow.wait(timeout=2.0)
        f1 = _make_jpeg(b"slow-1")
        f2 = _make_jpeg(b"slow-2-dropped")
        f3 = _make_jpeg(b"slow-3")

        proc_slow.write_chunk(f1)
        deadline = time.monotonic() + 2.0
        while slow_transcoder.get_latest_frame() != f1 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert slow_transcoder.get_latest_frame() == f1
        assert slow_transcoder.status()["frame_seq"] == 1

        # Push f2 immediately (well under 0.5s interval) -> must be dropped.
        proc_slow.write_chunk(f2)
        time.sleep(0.05)
        assert slow_transcoder.get_latest_frame() == f1
        assert slow_transcoder.status()["frame_seq"] == 1

        # Wait past the 0.5s interval, then push f3 -> must publish.
        time.sleep(0.5)
        proc_slow.write_chunk(f3)
        deadline = time.monotonic() + 2.0
        while slow_transcoder.get_latest_frame() != f3 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert slow_transcoder.get_latest_frame() == f3
        assert slow_transcoder.status()["frame_seq"] == 2
    finally:
        slow_transcoder.stop()

    # When fps >= 30 (e.g. fps=30 -> passthrough), back-to-back frames publish immediately.
    proc_fast = _PipeFakeProcess()
    spawned_fast = threading.Event()

    def fast_factory(cmd: list[str], **kwargs: Any) -> _PipeFakeProcess:
        spawned_fast.set()
        return proc_fast

    fast_transcoder = MjpegStreamTranscoder(
        fps=30,
        popen_factory=fast_factory,
        restart_delay_sec=0.05,
    )
    fast_transcoder.start()
    try:
        assert spawned_fast.wait(timeout=2.0)
        g1 = _make_jpeg(b"fast-1")
        g2 = _make_jpeg(b"fast-2")
        proc_fast.write_chunk(g1)
        deadline = time.monotonic() + 2.0
        while fast_transcoder.get_latest_frame() != g1 and time.monotonic() < deadline:
            time.sleep(0.005)
        proc_fast.write_chunk(g2)
        deadline = time.monotonic() + 2.0
        while fast_transcoder.get_latest_frame() != g2 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert fast_transcoder.get_latest_frame() == g2
        assert fast_transcoder.status()["frame_seq"] == 2
    finally:
        fast_transcoder.stop()


def test_ffmpeg_low_latency_mjpeg_command_decodes_synthetic_h264_mpegts(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg binary not found in PATH")

    ts_path = tmp_path / "synthetic.ts"
    gen = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x120:rate=30",
            "-t",
            "0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mpegts",
            str(ts_path),
        ],
        capture_output=True,
        check=False,
        timeout=15,
    )
    if gen.returncode != 0:
        pytest.skip(f"ffmpeg could not generate synthetic H.264 MPEG-TS clip: {gen.stderr!r}")

    cmd = build_mjpeg_ffmpeg_command(stream_url=str(ts_path), ffmpeg_path=ffmpeg, fps=30, quality=5)
    proc = subprocess.run(cmd, capture_output=True, check=False, timeout=15)
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    assert proc.stderr == b""

    buf = bytearray(proc.stdout)
    frames = extract_jpeg_frames(buf)
    assert len(frames) >= 3
    for frame in frames:
        assert frame.startswith(JPEG_SOI)
        assert frame.endswith(JPEG_EOI)
        assert len(frame) > 100
