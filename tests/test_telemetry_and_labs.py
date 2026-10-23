from __future__ import annotations

import csv
import json
import struct
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import pytest
import segno

from uel_gopro.core.models import GpsPoint, TelemetryTrack
from uel_gopro.labs.qr import (
    PRESETS,
    generate_labs_qr,
    render_terminal_qr,
    save_qr_image,
)
from uel_gopro.telemetry.gpmf import (
    extract_gpmf_from_mp4,
    parse_gpmf_stream,
    unpack_klv_stream,
)
from uel_gopro.telemetry.exporters import (
    export_csv,
    export_geojson,
    export_gpx,
    export_kml,
)


def make_klv(fourcc: str, type_char: str, sample_size: int, repeat: int, payload: bytes) -> bytes:
    """Helper to assemble a valid big-endian 8-byte KLV packet with 4-byte padding."""
    fourcc_bytes = fourcc.encode("ascii")[:4].ljust(4, b" ")
    type_byte = ord(type_char) if type_char else 0
    header = struct.pack(">4sBBH", fourcc_bytes, type_byte, sample_size, repeat)
    padded_len = (len(payload) + 3) & ~3
    padding = b"\x00" * (padded_len - len(payload))
    return header + payload + padding


# =============================================================================
# GoPro Labs QR Tests
# =============================================================================

class TestLabsQR:
    def test_generate_labs_qr_standard_qr(self):
        qr = generate_labs_qr("*BITR=180")
        assert isinstance(qr, segno.QRCode)
        assert not qr.is_micro
        assert qr.version >= 1

    def test_generate_labs_qr_preset_lookup(self):
        qr = generate_labs_qr("motion_detect")
        assert isinstance(qr, segno.QRCode)
        assert not qr.is_micro

    def test_render_terminal_qr_ansi_string(self):
        output = render_terminal_qr("speed_trigger_50kmh", invert=False)
        assert isinstance(output, str)
        assert len(output) > 0
        # Check for block characters
        assert any(c in output for c in ("█", "▀", "▄", " "))
        # Check for ANSI escape sequences
        assert "\033[97;40m" in output
        assert "\033[0m" in output

    def test_render_terminal_qr_invert(self):
        output = render_terminal_qr("!M1", invert=True)
        assert isinstance(output, str)
        assert len(output) > 0
        assert "\033[30;47m" in output
        assert "\033[0m" in output

    @pytest.mark.parametrize("preset_name", list(PRESETS.keys()))
    def test_all_presets_renderable(self, preset_name):
        rendered = render_terminal_qr(preset_name)
        assert len(rendered) > 0
        assert "\033[0m" in rendered

    def test_save_qr_image_png_and_svg(self, tmp_path: Path):
        png_path = tmp_path / "qr.png"
        svg_path = tmp_path / "qr.svg"

        res_png = save_qr_image("bitrate_max", png_path, scale=5)
        res_svg = save_qr_image("bitrate_max", svg_path, scale=5)

        assert res_png.is_file()
        assert res_png.stat().st_size > 0
        assert res_svg.is_file()
        assert "<svg" in res_svg.read_text(encoding="utf-8")


# =============================================================================
# GPMF Binary Parsing Tests
# =============================================================================

class TestGPMFParsing:
    def test_parse_gpmf_stream_synthetic_payload(self):
        # 1. SCAL: 5 values for lat, lon, alt, 2D speed, 3D speed
        scal_bytes = struct.pack(">5i", 10_000_000, 10_000_000, 1_000, 100, 100)
        scal_klv = make_klv("SCAL", "l", 4, 5, scal_bytes)

        # 2. GPS5: 2 samples of 5 longs each
        # Sample 1: 37.774929, -122.419400, 12.5m, 5.4 m/s, 5.5 m/s
        # Sample 2: 37.775000, -122.419000, 13.0m, 6.0 m/s, 6.1 m/s
        gps5_bytes = struct.pack(
            ">10i",
            377749290, -1224194000, 12500, 540, 550,
            377750000, -1224190000, 13000, 600, 610,
        )
        gps5_klv = make_klv("GPS5", "l", 20, 2, gps5_bytes)

        # 3. ACCL: 3 signed shorts
        accl_bytes = struct.pack(">3h", 0, 981, 0)
        accl_klv = make_klv("ACCL", "s", 6, 1, accl_bytes)

        # 4. GYRO: 3 signed shorts
        gyro_bytes = struct.pack(">3h", 12, -45, 67)
        gyro_klv = make_klv("GYRO", "s", 6, 1, gyro_bytes)

        # 5. STRM container wrapping SCAL + GPS5 + ACCL + GYRO
        strm_payload = scal_klv + gps5_klv + accl_klv + gyro_klv
        strm_klv = make_klv("STRM", "", 1, len(strm_payload), strm_payload)

        # 6. DVNM: Device Name
        dvnm_bytes = b"HERO11 Black"
        dvnm_klv = make_klv("DVNM", "c", 1, len(dvnm_bytes), dvnm_bytes)

        # 7. DEVC container wrapping DVNM + STRM
        devc_payload = dvnm_klv + strm_klv
        devc_klv = make_klv("DEVC", "", 1, len(devc_payload), devc_payload)

        # Parse stream
        track = parse_gpmf_stream(devc_klv)

        assert track.device_name == "HERO11 Black"
        assert track.has_accel is True
        assert track.has_gyro is True
        assert len(track.gps_points) == 2

        # Verify point 1
        pt1 = track.gps_points[0]
        assert abs(pt1.lat - 37.774929) < 1e-5
        assert abs(pt1.lon - (-122.419400)) < 1e-4
        assert abs(pt1.alt - 12.5) < 1e-3
        assert abs(pt1.speed_2d - 5.4) < 1e-3
        assert abs(pt1.speed_3d - 5.5) < 1e-3

        # Verify point 2
        pt2 = track.gps_points[1]
        assert abs(pt2.lat - 37.775000) < 1e-5
        assert abs(pt2.lon - (-122.419000)) < 1e-4
        assert abs(pt2.alt - 13.0) < 1e-3
        assert abs(pt2.speed_2d - 6.0) < 1e-3
        assert abs(pt2.speed_3d - 6.1) < 1e-3

    def test_parse_gpmf_stream_with_days_and_secs(self):
        # GPS sample with 7 fields: lat, lon, alt, s2d, s3d, days, secs
        # days = 8415 (2023-01-15), secs = 43200 (12:00:00)
        scal_bytes = struct.pack(">7i", 10_000_000, 10_000_000, 1_000, 100, 100, 1, 1)
        scal_klv = make_klv("SCAL", "l", 4, 7, scal_bytes)

        gps_bytes = struct.pack(
            ">7i",
            377749290, -1224194000, 12500, 540, 550, 8415, 43200
        )
        gps_klv = make_klv("GPS5", "l", 28, 1, gps_bytes)
        strm_payload = scal_klv + gps_klv
        strm_klv = make_klv("STRM", "", 1, len(strm_payload), strm_payload)

        track = parse_gpmf_stream(strm_klv)
        assert len(track.gps_points) == 1
        pt = track.gps_points[0]
        assert pt.timestamp_utc is not None
        assert "2023-01-15" in pt.timestamp_utc
        assert "12:00:00" in pt.timestamp_utc

    def test_parse_gpmf_stream_with_gpsu(self):
        scal_bytes = struct.pack(">5i", 10_000_000, 10_000_000, 1_000, 100, 100)
        scal_klv = make_klv("SCAL", "l", 4, 5, scal_bytes)

        gpsu_bytes = b"230501143000.000"
        gpsu_klv = make_klv("GPSU", "U", 1, len(gpsu_bytes), gpsu_bytes)

        gps5_bytes = struct.pack(">5i", 377749290, -1224194000, 12500, 540, 550)
        gps5_klv = make_klv("GPS5", "l", 20, 1, gps5_bytes)

        strm_payload = gpsu_klv + scal_klv + gps5_klv
        strm_klv = make_klv("STRM", "", 1, len(strm_payload), strm_payload)

        track = parse_gpmf_stream(strm_klv)
        assert len(track.gps_points) == 1
        pt = track.gps_points[0]
        assert pt.timestamp_utc is not None
        assert "2023-05-01" in pt.timestamp_utc

    def test_empty_or_corrupted_stream(self):
        t1 = parse_gpmf_stream(b"")
        assert len(t1.gps_points) == 0

        t2 = parse_gpmf_stream(b"JUNK\x00\x00\x00\x00\x12\x34")
        assert isinstance(t2, TelemetryTrack)

    def test_extract_gpmf_from_mp4_binary_passthrough(self, tmp_path: Path):
        bin_file = tmp_path / "telemetry.bin"
        dummy_data = b"GPMF_TEST_DATA"
        bin_file.write_bytes(dummy_data)

        extracted = extract_gpmf_from_mp4(bin_file)
        assert extracted == dummy_data

    def test_extract_gpmf_from_mp4_not_found(self):
        with pytest.raises(FileNotFoundError):
            extract_gpmf_from_mp4(Path("/nonexistent/video.mp4"))


# =============================================================================
# Exporters Tests
# =============================================================================

@pytest.fixture
def sample_track() -> TelemetryTrack:
    p1 = GpsPoint(
        timestamp_utc="2023-01-01T10:00:00Z",
        lat=37.774900,
        lon=-122.419400,
        alt=10.5,
        speed_2d=5.0,
        speed_3d=5.1,
    )
    p2 = GpsPoint(
        timestamp_utc="2023-01-01T10:00:01Z",
        lat=37.775000,
        lon=-122.419000,
        alt=11.0,
        speed_2d=6.0,
        speed_3d=6.2,
    )
    return TelemetryTrack(
        device_name="GoPro HERO11",
        gps_points=[p1, p2],
        has_gyro=True,
        has_accel=True,
    )


class TestExporters:
    def test_export_gpx(self, sample_track: TelemetryTrack, tmp_path: Path):
        gpx_file = tmp_path / "track.gpx"
        export_gpx(sample_track, gpx_file)

        assert gpx_file.is_file()
        tree = ET.parse(gpx_file)
        root = tree.getroot()
        assert "gpx" in root.tag

        # Find trkpt elements (handling potential XML namespaces)
        trkpts = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        if not trkpts:
            trkpts = root.findall(".//trkpt")

        assert len(trkpts) == 2
        pt0 = trkpts[0]
        assert float(pt0.attrib["lat"]) == pytest.approx(37.774900, abs=1e-5)
        assert float(pt0.attrib["lon"]) == pytest.approx(-122.419400, abs=1e-5)

        ele = pt0.find("{http://www.topografix.com/GPX/1/1}ele")
        if ele is None:
            ele = pt0.find("ele")

        time_el = pt0.find("{http://www.topografix.com/GPX/1/1}time")
        if time_el is None:
            time_el = pt0.find("time")

        speed_el = pt0.find("{http://www.topografix.com/GPX/1/1}speed")
        if speed_el is None:
            speed_el = pt0.find("speed")

        assert ele is not None and float(ele.text) == pytest.approx(10.5, abs=1e-3)
        assert time_el is not None and time_el.text == "2023-01-01T10:00:00Z"
        assert speed_el is not None and float(speed_el.text) == pytest.approx(5.0, abs=1e-3)

    def test_export_kml(self, sample_track: TelemetryTrack, tmp_path: Path):
        kml_file = tmp_path / "track.kml"
        export_kml(sample_track, kml_file)

        assert kml_file.is_file()
        tree = ET.parse(kml_file)
        root = tree.getroot()
        assert "kml" in root.tag

        coords_el = root.find(".//{http://www.opengis.net/kml/2.2}coordinates")
        if coords_el is None:
            coords_el = root.find(".//coordinates")

        assert coords_el is not None
        coord_text = coords_el.text.strip()
        lines = [line.strip() for line in coord_text.splitlines() if line.strip()]
        assert len(lines) == 2
        assert "-122.4194000,37.7749000,10.500" in lines[0]

    def test_export_geojson(self, sample_track: TelemetryTrack, tmp_path: Path):
        geojson_file = tmp_path / "track.geojson"
        export_geojson(sample_track, geojson_file)

        assert geojson_file.is_file()
        data = json.loads(geojson_file.read_text(encoding="utf-8"))

        assert data["type"] == "FeatureCollection"
        features = data["features"]
        assert len(features) == 1
        feat = features[0]
        assert feat["properties"]["device_name"] == "GoPro HERO11"
        assert feat["geometry"]["type"] == "LineString"
        coords = feat["geometry"]["coordinates"]
        assert len(coords) == 2
        assert coords[0] == [-122.4194, 37.7749, 10.5]
        assert coords[1] == [-122.419, 37.775, 11.0]

    def test_export_csv(self, sample_track: TelemetryTrack, tmp_path: Path):
        csv_file = tmp_path / "track.csv"
        export_csv(sample_track, csv_file)

        assert csv_file.is_file()
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = list(csv.reader(f))

        assert len(reader) == 3
        assert reader[0] == ["timestamp", "lat", "lon", "alt", "speed_2d", "speed_3d"]
        assert reader[1] == ["2023-01-01T10:00:00Z", "37.7749", "-122.4194", "10.5", "5.0", "5.1"]
        assert reader[2] == ["2023-01-01T10:00:01Z", "37.775", "-122.419", "11.0", "6.0", "6.2"]
