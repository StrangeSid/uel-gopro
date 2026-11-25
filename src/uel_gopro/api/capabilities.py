from __future__ import annotations

import re
from typing import Any, Dict, Optional

RESOLUTION_LABELS: dict[int, str] = {
    1: "4K (16:9)",
    4: "2.7K (16:9)",
    6: "2.7K (4:3)",
    7: "1440p",
    9: "1080p (16:9)",
    18: "4K (4:3)",
    24: "5K (16:9)",
    25: "5.3K (4:3)",
    26: "5.3K (8:7)",
    27: "5.3K (4:3)",
    28: "4K (8:7)",
    100: "5.3K (16:9)",
    107: "5.3K (8:7)",
    108: "4K (8:7)",
    109: "4K (9:16)",
    110: "1080p (9:16)",
}

FPS_LABELS: dict[int, str] = {
    0: "240 fps",
    1: "120 fps",
    2: "100 fps",
    5: "60 fps",
    6: "50 fps",
    8: "30 fps",
    9: "25 fps",
    10: "24 fps",
    13: "200 fps",
}

LENS_LABELS: dict[int, str] = {
    0: "Wide",
    2: "Narrow",
    3: "SuperView",
    4: "Linear",
    7: "Max SuperView",
    8: "Linear + Horizon Leveling",
    9: "HyperView",
    10: "Linear + Horizon Lock",
    11: "Max HyperView",
}

BITRATE_LABELS: dict[int, str] = {
    0: "Standard",
    1: "High",
}

ANTI_FLICKER_LABELS: dict[int, str] = {
    2: "60 Hz (NTSC)",
    3: "50 Hz (PAL)",
}

HYPERSMOOTH_LABELS: dict[int, str] = {
    0: "Off",
    1: "Low",
    2: "High",
    3: "Boost",
    4: "AutoBoost",
    100: "High / On",
}

_SETTING_LABEL_TABLES: dict[int, dict[int, str]] = {
    2: RESOLUTION_LABELS,
    3: FPS_LABELS,
    121: LENS_LABELS,
    182: BITRATE_LABELS,
    134: ANTI_FLICKER_LABELS,
    135: HYPERSMOOTH_LABELS,
}

# Ordered quick settings definition: (setting_id, alias, display_label)
_ORDERED_SETTINGS: tuple[tuple[int, str, str], ...] = (
    (2, "resolution", "Resolution"),
    (3, "fps", "Frame Rate"),
    (121, "fov", "Digital Lens"),
    (134, "anti_flicker", "Anti-Flicker"),
    (135, "hypersmooth", "HyperSmooth"),
    (182, "bitrate", "Bitrate"),
)

MODEL_ID_MAP: dict[int | str, str] = {
    55: "HERO9 Black",
    "00000037": "HERO9 Black",
    57: "HERO10 Black",
    "00000039": "HERO10 Black",
    58: "HERO11 Black",
    60: "HERO11 Black",
    "0000003a": "HERO11 Black",
    "0000003c": "HERO11 Black",
    62: "HERO12 Black",
    "0000003e": "HERO12 Black",
    64: "HERO13 Black",
    "00000040": "HERO13 Black",
}

FIRMWARE_MODEL_PREFIXES: dict[str, str] = {
    "H20": "HERO9 Black",
    "H21": "HERO10 Black",
    "H22": "HERO11 Black",
    "H23": "HERO12 Black",
    "H24": "HERO13 Black",
}

_HERO_NAME_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhero[\s\-_]*13\b", re.IGNORECASE), "HERO13 Black"),
    (re.compile(r"\bhero[\s\-_]*12\b", re.IGNORECASE), "HERO12 Black"),
    (re.compile(r"\bhero[\s\-_]*11\b", re.IGNORECASE), "HERO11 Black"),
    (re.compile(r"\bhero[\s\-_]*10\b", re.IGNORECASE), "HERO10 Black"),
    (re.compile(r"\bhero[\s\-_]*9\b", re.IGNORECASE), "HERO9 Black"),
)

_PAL_FPS_CODES = frozenset({2, 6, 9, 13})


def _safe_int(value: Any) -> Optional[int]:
    """Coerce numeric values to int while rejecting booleans and non-numeric strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            try:
                parsed = float(cleaned)
            except ValueError:
                return None
            return int(parsed) if parsed.is_integer() else None
    return None


def _normalize_settings(raw_settings: Optional[Dict[Any, Any]]) -> dict[int, int]:
    """Normalize a raw settings mapping into integer key -> integer value."""
    normalized: dict[int, int] = {}
    if not isinstance(raw_settings, dict):
        return normalized
    for raw_key, raw_val in raw_settings.items():
        key = _safe_int(raw_key)
        val = _safe_int(raw_val)
        if key is not None and val is not None:
            normalized[key] = val
    return normalized


def _lookup_model_id(candidate: Any) -> Optional[str]:
    """Resolve numeric or hex camera model IDs via MODEL_ID_MAP."""
    if isinstance(candidate, bool) or candidate is None:
        return None
    if isinstance(candidate, int):
        return MODEL_ID_MAP.get(candidate)
    if not isinstance(candidate, str):
        return None

    cleaned = candidate.strip()
    if not cleaned:
        return None

    lowered = cleaned.lower()
    if lowered in MODEL_ID_MAP:
        return MODEL_ID_MAP[lowered]

    if cleaned.isascii() and cleaned.isdigit():
        num = int(cleaned)
        if num in MODEL_ID_MAP:
            return MODEL_ID_MAP[num]

    if lowered.startswith("0x"):
        try:
            num = int(lowered, 16)
        except ValueError:
            return None
        return MODEL_ID_MAP.get(num)

    if len(lowered) <= 8 and all(ch in "0123456789abcdef" for ch in lowered):
        if any(ch in "abcdef" for ch in lowered) or lowered.startswith("0"):
            try:
                num = int(lowered, 16)
            except ValueError:
                return None
            return MODEL_ID_MAP.get(num)

    return None


def _dedupe_ints(values: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def detect_camera_model(
    model_name: Optional[str] = None,
    firmware_version: Optional[str] = None,
    model_id: Any = None,
    raw_settings: Optional[Dict[Any, Any]] = None,
) -> str:
    """Detect canonical GoPro model string from name, model ID, firmware, or settings."""
    if isinstance(model_name, str) and model_name.strip():
        text = model_name.strip()
        for pattern, canonical in _HERO_NAME_PATTERNS:
            if pattern.search(text):
                return canonical

    for candidate in (model_id, model_name):
        matched = _lookup_model_id(candidate)
        if matched:
            return matched

    if isinstance(firmware_version, str) and firmware_version.strip():
        fw_upper = firmware_version.strip().upper()
        for prefix, canonical in FIRMWARE_MODEL_PREFIXES.items():
            if fw_upper.startswith(prefix):
                return canonical

    norm = _normalize_settings(raw_settings)
    if norm:
        res = norm.get(2)
        lens = norm.get(121)
        hs = norm.get(135)
        if res in {107, 108, 109, 110} or lens == 10:
            return "HERO12 Black"
        if res in {26, 28} or 182 in norm or lens == 9 or hs == 4:
            return "HERO11 Black"

    return "Generic OpenGoPro"


def format_option_label(setting_id: int, option_value: int) -> str:
    """Return human-readable label for a setting option value."""
    table = _SETTING_LABEL_TABLES.get(setting_id)
    if table is not None and option_value in table:
        return table[option_value]
    return f"Option {option_value}"


def _hero9_fps_options(active_res: Optional[int], hz: int) -> list[int]:
    if hz == 50:
        mapping = {
            24: [9, 10],
            25: [9, 10],
            1: [6, 9, 10],
            18: [9, 10],
            4: [2, 6],
            6: [6],
            7: [2, 6, 9, 10],
            9: [13, 2, 6, 9, 10],
        }
        return list(mapping.get(active_res, [6, 9, 10]))
    mapping = {
        24: [8, 10],
        25: [8, 10],
        1: [5, 8, 10],
        18: [8, 10],
        4: [1, 5],
        6: [5],
        7: [1, 5, 8, 10],
        9: [0, 1, 5, 8, 10],
    }
    return list(mapping.get(active_res, [5, 8, 10]))


def _hero10_fps_options(active_res: Optional[int], hz: int) -> list[int]:
    if hz == 50:
        mapping = {
            100: [6, 9, 10],
            25: [9, 10],
            1: [2, 6, 9, 10],
            18: [6, 9, 10],
            4: [13, 2, 6],
            6: [2, 6],
            9: [13, 2, 6, 9, 10],
        }
        return list(mapping.get(active_res, [2, 6, 9, 10]))
    mapping = {
        100: [5, 8, 10],
        25: [8, 10],
        1: [1, 5, 8, 10],
        18: [5, 8, 10],
        4: [0, 1, 5],
        6: [1, 5],
        9: [0, 1, 5, 8, 10],
    }
    return list(mapping.get(active_res, [1, 5, 8, 10]))


def _hero11_fps_options(active_res: Optional[int], hz: int) -> list[int]:
    if hz == 50:
        mapping = {
            100: [6, 9, 10],
            26: [9, 10],
            25: [9, 10],
            1: [2, 6, 9, 10],
            28: [6, 9, 10],
            18: [6, 9, 10],
            4: [13, 2, 6],
            6: [2, 6],
            9: [13, 2, 6, 9, 10],
        }
        return list(mapping.get(active_res, [2, 6, 9, 10]))
    mapping = {
        100: [5, 8, 10],
        26: [8, 10],
        25: [8, 10],
        1: [1, 5, 8, 10],
        28: [5, 8, 10],
        18: [5, 8, 10],
        4: [0, 1, 5],
        6: [1, 5],
        9: [0, 1, 5, 8, 10],
    }
    return list(mapping.get(active_res, [1, 5, 8, 10]))


def _hero12_13_fps_options(active_res: Optional[int], hz: int) -> list[int]:
    if hz == 50:
        mapping = {
            100: [6, 9, 10],
            107: [9, 10],
            1: [2, 6, 9, 10],
            108: [6, 9, 10],
            109: [6, 9, 10],
            4: [13, 2, 6],
            9: [13, 2, 6, 9, 10],
            110: [6, 9, 10],
        }
        return list(mapping.get(active_res, [2, 6, 9, 10]))
    mapping = {
        100: [5, 8, 10],
        107: [8, 10],
        1: [1, 5, 8, 10],
        108: [5, 8, 10],
        109: [5, 8, 10],
        4: [0, 1, 5],
        9: [0, 1, 5, 8, 10],
        110: [5, 8, 10],
    }
    return list(mapping.get(active_res, [1, 5, 8, 10]))


def _is_high_speed_16_9(active_res: Optional[int], active_fps: Optional[int]) -> bool:
    return (
        active_fps in {0, 13}
        or (active_res == 1 and active_fps in {1, 2})
        or (active_res == 100 and active_fps in {5, 6})
    )


def _matrix_options_for_model(
    model: str,
    active_res: Optional[int],
    active_fps: Optional[int],
    hz: int,
    norm_settings: dict[int, int],
) -> dict[int, list[int]]:
    if model == "HERO9 Black":
        if active_res in {25, 18, 6}:
            lens_opts = [0, 4]
        elif active_res == 24 or active_fps in {0, 13}:
            lens_opts = [0, 4, 2]
        else:
            lens_opts = [0, 2, 3, 4]
        opts: dict[int, list[int]] = {
            2: [24, 25, 1, 18, 4, 6, 7, 9],
            3: _hero9_fps_options(active_res, hz),
            121: lens_opts,
            134: [2, 3],
            135: [0, 1, 2, 3],
        }
        if 182 in norm_settings:
            opts[182] = [0, 1]
        return opts

    if model == "HERO10 Black":
        if active_res in {25, 18, 6}:
            lens_opts = [0, 4]
        elif _is_high_speed_16_9(active_res, active_fps):
            lens_opts = [0, 4, 2]
        else:
            lens_opts = [0, 2, 3, 4]
        opts = {
            2: [100, 25, 1, 18, 4, 6, 9],
            3: _hero10_fps_options(active_res, hz),
            121: lens_opts,
            134: [2, 3],
            135: [0, 3, 100],
        }
        if 182 in norm_settings:
            opts[182] = [0, 1]
        return opts

    if model == "HERO11 Black":
        if active_res in {26, 28}:
            lens_opts = [0]
        elif active_res in {25, 18, 6}:
            lens_opts = [0, 4]
        elif _is_high_speed_16_9(active_res, active_fps):
            lens_opts = [0, 4, 2]
        else:
            lens_opts = [9, 3, 0, 4, 8]
        return {
            2: [100, 26, 25, 1, 28, 18, 4, 6, 9],
            3: _hero11_fps_options(active_res, hz),
            121: lens_opts,
            134: [2, 3],
            135: [0, 1, 4],
            182: [0, 1],
        }

    if model in {"HERO12 Black", "HERO13 Black"}:
        if active_res in {107, 108}:
            lens_opts = [0]
        elif active_res in {109, 110}:
            lens_opts = [0, 4]
        elif _is_high_speed_16_9(active_res, active_fps):
            lens_opts = [0, 4, 2]
        else:
            lens_opts = [9, 3, 0, 4, 8, 10]
        return {
            2: [100, 107, 1, 108, 109, 4, 9, 110],
            3: _hero12_13_fps_options(active_res, hz),
            121: lens_opts,
            134: [2, 3],
            135: [0, 1, 4],
            182: [0, 1],
        }

    # Generic OpenGoPro fallback
    return {
        2: [100, 24, 1, 18, 4, 6, 9],
        3: [13, 2, 6, 9, 10] if hz == 50 else [0, 1, 5, 8, 10],
        121: [0, 2, 3, 4],
        134: [2, 3],
        135: [0, 1, 2, 3, 4, 100],
        182: [0, 1],
    }


def resolve_setting_capabilities(
    model_name: Optional[str] = None,
    current_settings: Optional[Dict[Any, Any]] = None,
    firmware_version: Optional[str] = None,
    model_id: Any = None,
    live_available: Optional[Dict[int, list[int]]] = None,
) -> dict[str, Any]:
    """Resolve model- and setting-aware camera capabilities and labeled options."""
    norm_settings = _normalize_settings(current_settings)
    model = detect_camera_model(
        model_name=model_name,
        firmware_version=firmware_version,
        model_id=model_id,
        raw_settings=norm_settings,
    )

    anti_flicker = norm_settings.get(134)
    if anti_flicker == 3:
        anti_flicker_hz = 50
    elif anti_flicker == 2:
        anti_flicker_hz = 60
    elif norm_settings.get(3) in _PAL_FPS_CODES:
        anti_flicker_hz = 50
    else:
        anti_flicker_hz = 60

    active_res = norm_settings.get(2)
    active_fps = norm_settings.get(3)
    matrix_options = _matrix_options_for_model(
        model=model,
        active_res=active_res,
        active_fps=active_fps,
        hz=anti_flicker_hz,
        norm_settings=norm_settings,
    )

    norm_live: Optional[dict[int, list[int]]] = None
    if isinstance(live_available, dict):
        parsed_live: dict[int, list[int]] = {}
        for raw_k, raw_vals in live_available.items():
            sid = _safe_int(raw_k)
            if sid is None or not isinstance(raw_vals, (list, tuple)):
                continue
            coerced = [v for v in (_safe_int(item) for item in raw_vals) if v is not None]
            parsed_live[sid] = _dedupe_ints(coerced)
        if parsed_live:
            norm_live = parsed_live

    used_live = False
    resolved_settings: dict[str, Any] = {}
    for setting_id, alias, human_name in _ORDERED_SETTINGS:
        option_ids: Optional[list[int]] = None
        if norm_live is not None:
            if setting_id in norm_live:
                if norm_live[setting_id]:
                    option_ids = list(norm_live[setting_id])
                    used_live = True
                else:
                    # Camera explicitly reported zero supported values for this setting.
                    continue
            elif setting_id in matrix_options:
                option_ids = list(matrix_options[setting_id])
        else:
            if setting_id in matrix_options:
                option_ids = list(matrix_options[setting_id])

        if option_ids is None:
            continue

        current_val = norm_settings.get(setting_id)
        if current_val is not None and current_val not in option_ids:
            option_ids.append(current_val)

        resolved_settings[alias] = {
            "id": setting_id,
            "label": human_name,
            "current": current_val,
            "current_label": (
                format_option_label(setting_id, current_val)
                if current_val is not None
                else None
            ),
            "options": [
                {"value": v, "label": format_option_label(setting_id, v)}
                for v in option_ids
            ],
        }

    source = "camera_live" if used_live else "model_matrix"
    return {
        "model": model,
        "source": source,
        "anti_flicker_hz": anti_flicker_hz,
        "settings": resolved_settings,
    }
