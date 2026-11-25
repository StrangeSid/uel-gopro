from __future__ import annotations

from uel_gopro.api.capabilities import (
    detect_camera_model,
    format_option_label,
    resolve_setting_capabilities,
)


def test_detect_camera_model_variants_and_fallbacks():
    assert detect_camera_model(model_name="HERO10 Black") == "HERO10 Black"
    assert detect_camera_model(model_name="hero 12 black") == "HERO12 Black"
    assert detect_camera_model(model_name="GoPro HERO13") == "HERO13 Black"
    assert detect_camera_model(model_name="hero-9") == "HERO9 Black"

    # Generic CDC-ECM / BLE names fall through to model_id or firmware
    assert (
        detect_camera_model(
            model_name="GoPro (USB CDC-ECM)",
            firmware_version="H21.01.01.62.00",
        )
        == "HERO10 Black"
    )
    assert detect_camera_model(model_name="00000039") == "HERO10 Black"
    assert detect_camera_model(model_id="00000039") == "HERO10 Black"
    assert detect_camera_model(model_id="0000003A") == "HERO11 Black"
    assert detect_camera_model(model_id="0000003c") == "HERO11 Black"
    assert detect_camera_model(model_id="0000003e") == "HERO12 Black"
    assert detect_camera_model(model_id="00000040") == "HERO13 Black"
    assert detect_camera_model(model_id="00000037") == "HERO9 Black"
    assert detect_camera_model(model_id=57) == "HERO10 Black"
    assert detect_camera_model(model_id="57") == "HERO10 Black"
    assert detect_camera_model(model_id=55) == "HERO9 Black"
    assert detect_camera_model(model_id=58) == "HERO11 Black"
    assert detect_camera_model(model_id=60) == "HERO11 Black"
    assert detect_camera_model(model_id=62) == "HERO12 Black"
    assert detect_camera_model(model_id=64) == "HERO13 Black"
    assert detect_camera_model(firmware_version="h22.01.00") == "HERO11 Black"
    assert detect_camera_model(firmware_version="H24.01.00.00") == "HERO13 Black"

    # Boolean model_id must not be coerced to int
    assert detect_camera_model(model_id=True) == "Generic OpenGoPro"
    # Settings heuristic & generic fallback
    assert detect_camera_model(raw_settings={"2": 107}) == "HERO12 Black"
    assert detect_camera_model(raw_settings={"182": 1}) == "HERO11 Black"
    assert detect_camera_model(raw_settings={"2": 1, "3": 5}) == "Generic OpenGoPro"
    assert detect_camera_model() == "Generic OpenGoPro"


def test_format_option_label():
    assert format_option_label(2, 100) == "5.3K (16:9)"
    assert format_option_label(3, 6) == "50 fps"
    assert format_option_label(121, 9) == "HyperView"
    assert format_option_label(134, 3) == "50 Hz (PAL)"
    assert format_option_label(135, 4) == "AutoBoost"
    assert format_option_label(182, 1) == "High"
    assert format_option_label(2, 999) == "Option 999"
    assert format_option_label(999, 42) == "Option 42"


def test_hero10_50hz_and_60hz_fps_and_lens_constraints():
    # Verified HERO10 50Hz PAL at 4K 50fps
    caps = resolve_setting_capabilities(
        model_name="GoPro 2108",
        firmware_version="H21.01.01.62.00",
        current_settings={"2": 1, "3": 6, "121": 3, "134": 3, "135": 100},
    )
    assert caps["model"] == "HERO10 Black"
    assert caps["source"] == "model_matrix"
    assert caps["anti_flicker_hz"] == 50
    assert list(caps["settings"].keys()) == [
        "resolution",
        "fps",
        "fov",
        "anti_flicker",
        "hypersmooth",
    ]
    assert "bitrate" not in caps["settings"]
    assert [o["value"] for o in caps["settings"]["resolution"]["options"]] == [
        100,
        25,
        1,
        18,
        4,
        6,
        9,
    ]
    assert [o["value"] for o in caps["settings"]["fps"]["options"]] == [2, 6, 9, 10]
    assert [o["value"] for o in caps["settings"]["fov"]["options"]] == [0, 2, 3, 4]
    assert caps["settings"]["resolution"]["current_label"] == "4K (16:9)"
    assert caps["settings"]["fps"]["current_label"] == "50 fps"
    assert caps["settings"]["fov"]["current_label"] == "SuperView"

    # HERO10 4K 100fps (high-speed) -> Lenses [0, 4, 2]
    caps_4k100 = resolve_setting_capabilities(
        model_id="00000039",
        current_settings={2: 1, 3: 2, 134: 3},
    )
    assert [o["value"] for o in caps_4k100["settings"]["fov"]["options"]] == [0, 4, 2]

    # HERO10 5.3K 50Hz vs 60Hz
    caps_5k_50 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 100, 3: 6, 134: 3},
    )
    assert [o["value"] for o in caps_5k_50["settings"]["fps"]["options"]] == [6, 9, 10]
    assert [o["value"] for o in caps_5k_50["settings"]["fov"]["options"]] == [0, 4, 2]

    caps_5k_60 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 100, 3: 8, 134: 2},
    )
    assert caps_5k_60["anti_flicker_hz"] == 60
    assert [o["value"] for o in caps_5k_60["settings"]["fps"]["options"]] == [5, 8, 10]
    assert [o["value"] for o in caps_5k_60["settings"]["fov"]["options"]] == [0, 2, 3, 4]

    # HERO10 2.7K 50Hz vs 60Hz, and 4:3 lens [0, 4]
    caps_27k_50 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 4, 3: 13},  # Infers 50Hz from PAL 200fps code 13
    )
    assert caps_27k_50["anti_flicker_hz"] == 50
    assert [o["value"] for o in caps_27k_50["settings"]["fps"]["options"]] == [13, 2, 6]
    assert [o["value"] for o in caps_27k_50["settings"]["fov"]["options"]] == [0, 4, 2]

    caps_27k_60 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 4, 3: 5, 134: 2},
    )
    assert [o["value"] for o in caps_27k_60["settings"]["fps"]["options"]] == [0, 1, 5]

    caps_4_3 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 18, 3: 9, 134: 3},
    )
    assert [o["value"] for o in caps_4_3["settings"]["fps"]["options"]] == [6, 9, 10]
    assert [o["value"] for o in caps_4_3["settings"]["fov"]["options"]] == [0, 4]

    # HERO10 1080p 60Hz & unknown resolution fallback
    caps_1080 = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 9, 3: 5, 134: 2},
    )
    assert [o["value"] for o in caps_1080["settings"]["fps"]["options"]] == [0, 1, 5, 8, 10]
    caps_unknown_res = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 999, 134: 3},
    )
    assert [o["value"] for o in caps_unknown_res["settings"]["fps"]["options"]] == [2, 6, 9, 10]
    assert 999 in [o["value"] for o in caps_unknown_res["settings"]["resolution"]["options"]]


def test_hero9_hero11_hero12_hero13_matrices():
    h9 = resolve_setting_capabilities(
        model_name="HERO9 Black",
        current_settings={2: 24, 3: 8, 134: 2},
    )
    assert h9["model"] == "HERO9 Black"
    assert [o["value"] for o in h9["settings"]["resolution"]["options"]] == [
        24,
        25,
        1,
        18,
        4,
        6,
        7,
        9,
    ]
    assert [o["value"] for o in h9["settings"]["fps"]["options"]] == [8, 10]
    assert [o["value"] for o in h9["settings"]["fov"]["options"]] == [0, 4, 2]
    assert [o["value"] for o in h9["settings"]["hypersmooth"]["options"]] == [0, 1, 2, 3]
    assert "bitrate" not in h9["settings"]

    h11 = resolve_setting_capabilities(
        model_name="HERO11 Black",
        current_settings={2: 1, 3: 8, 134: 2},
    )
    assert 26 in [o["value"] for o in h11["settings"]["resolution"]["options"]]
    assert [o["value"] for o in h11["settings"]["fov"]["options"]] == [9, 3, 0, 4, 8]
    assert [o["value"] for o in h11["settings"]["hypersmooth"]["options"]] == [0, 1, 4]
    assert [o["value"] for o in h11["settings"]["bitrate"]["options"]] == [0, 1]

    h11_87 = resolve_setting_capabilities(
        model_name="HERO11 Black",
        current_settings={2: 26, 3: 9, 134: 3},
    )
    assert [o["value"] for o in h11_87["settings"]["fov"]["options"]] == [0]

    h12 = resolve_setting_capabilities(
        model_name="HERO12 Black",
        current_settings={2: 109, 3: 5, 134: 2},
    )
    assert [o["value"] for o in h12["settings"]["resolution"]["options"]] == [
        100,
        107,
        1,
        108,
        109,
        4,
        9,
        110,
    ]
    assert [o["value"] for o in h12["settings"]["fov"]["options"]] == [0, 4]
    assert "bitrate" in h12["settings"]

    h13 = resolve_setting_capabilities(
        model_name="HERO13 Black",
        current_settings={2: 1, 3: 8, 134: 2},
    )
    assert [o["value"] for o in h13["settings"]["fov"]["options"]] == [9, 3, 0, 4, 8, 10]


def test_live_available_overrides_matrix_and_preserves_unknown_current():
    caps = resolve_setting_capabilities(
        model_name="HERO10 Black",
        firmware_version="H21.01.01.62.00",
        current_settings={"2": 1, "3": 6, "121": 77, "134": "bad", "135": True},
        live_available={
            2: [1, 4, 100],
            3: [6, 9],
            121: [0, 2, 3, 4],
            134: [2, 3],
            135: [0, 3, 100],
            182: [],
        },
    )
    assert caps["source"] == "camera_live"
    assert [o["value"] for o in caps["settings"]["resolution"]["options"]] == [1, 4, 100]
    assert [o["value"] for o in caps["settings"]["fps"]["options"]] == [6, 9]
    # Unknown active value 77 appended so select never renders blank
    assert [o["value"] for o in caps["settings"]["fov"]["options"]] == [0, 2, 3, 4, 77]
    assert caps["settings"]["fov"]["current"] == 77
    assert caps["settings"]["fov"]["current_label"] == "Option 77"
    # Non-numeric / bool settings ignored safely
    assert caps["settings"]["anti_flicker"]["current"] is None
    assert caps["settings"]["hypersmooth"]["current"] is None
    # Empty list reported by camera omits bitrate
    assert "bitrate" not in caps["settings"]


def test_capabilities_edge_cases_empty_live_partial_live_hex_and_floats():
    # Empty live_available falls back cleanly to model_matrix
    empty_live = resolve_setting_capabilities(
        model_id="0x39",
        current_settings={2: 1.0, 3: 6, 134: 2, 121: 1.5},
        live_available={},
    )
    assert empty_live["model"] == "HERO10 Black"
    assert empty_live["source"] == "model_matrix"
    # Explicit 134=2 (60 Hz) overrides stale PAL FPS code 3=6
    assert empty_live["anti_flicker_hz"] == 60
    assert empty_live["settings"]["resolution"]["current"] == 1
    assert empty_live["settings"]["fov"]["current"] is None  # 1.5 skipped safely
    assert [o["value"] for o in empty_live["settings"]["fps"]["options"]] == [1, 5, 8, 10, 6]

    # 0x-prefixed hex model_id
    assert detect_camera_model(model_id="0x3a") == "HERO11 Black"

    # Partial live_available uses camera_live for returned settings and matrix for others
    partial_live = resolve_setting_capabilities(
        model_name="HERO10 Black",
        current_settings={2: 1, 3: 6, 134: 3},
        live_available={2: [1, 4], 3: [6]},
    )
    assert partial_live["source"] == "camera_live"
    assert [o["value"] for o in partial_live["settings"]["resolution"]["options"]] == [1, 4]
    assert [o["value"] for o in partial_live["settings"]["fps"]["options"]] == [6]
    assert [o["value"] for o in partial_live["settings"]["anti_flicker"]["options"]] == [2, 3]

