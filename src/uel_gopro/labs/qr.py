from __future__ import annotations

from pathlib import Path
from typing import Dict, Union
import segno

PRESETS: Dict[str, str] = {
    "bitrate_max": "*BITR=180",
    "motion_detect": "!M1",
    "speed_trigger_50kmh": "!S50",
    "schedule_wake_8am": "!08:00N",
    "timestamp_overlay": "oT%m/%d/%y %H:%M:%S",
    "gyro_logging": "*WIDE=1*GPSL=1",
}


def resolve_code(code_or_preset: str) -> str:
    """Resolve preset alias if present, else return input string."""
    return PRESETS.get(code_or_preset, code_or_preset)


def generate_labs_qr(code: str) -> segno.QRCode:
    """Create a standard QR code for GoPro Labs from a string or preset key.
    
    GoPro Labs requires standard QR codes (version >= 1), not Micro QR.
    """
    payload = resolve_code(code)
    return segno.make_qr(payload, error="m")


def render_terminal_qr(code: str, invert: bool = False) -> str:
    """Render QR code as an ANSI/Unicode string suitable for printing directly to the terminal.
    
    Uses half-block characters (▀, ▄, █, ' ') pairing two vertical rows per line
    for a crisp, scan-friendly aspect ratio.
    
    When invert=False (default for dark terminals):
    - Light modules/border are rendered as bright white foreground.
    - Dark modules are rendered as black background.
    
    When invert=True (for light terminals):
    - Color polarity is reversed.
    """
    qr = generate_labs_qr(code)
    # 4-module quiet zone, as required by the QR specification.
    matrix = [list(row) for row in qr.matrix_iter(border=4)]
    
    h = len(matrix)
    w = len(matrix[0]) if h > 0 else 0
    if h == 0 or w == 0:
        return ""

    # Ensure even number of rows
    if h % 2 != 0:
        matrix.append([0] * w)
        h += 1

    lines = []
    # Default: black modules on a white background (standard polarity).
    # --invert: white modules on a black background.
    ansi_prefix = "\033[97;40m" if invert else "\033[30;47m"
    ansi_reset = "\033[0m"

    for r in range(0, h, 2):
        row_chars = []
        for c in range(w):
            top = matrix[r][c]
            bot = matrix[r + 1][c]

            if not invert:
                # Standard polarity: 1 is dark (foreground block), 0 is light (space)
                if top == 1 and bot == 1:
                    row_chars.append("█")
                elif top == 1 and bot == 0:
                    row_chars.append("▀")
                elif top == 0 and bot == 1:
                    row_chars.append("▄")
                else:  # top == 0 and bot == 0
                    row_chars.append(" ")
            else:
                # Inverted: 0 is light (foreground block), 1 is dark (space)
                if top == 0 and bot == 0:
                    row_chars.append("█")
                elif top == 0 and bot == 1:
                    row_chars.append("▀")
                elif top == 1 and bot == 0:
                    row_chars.append("▄")
                else:  # top == 1 and bot == 1
                    row_chars.append(" ")

        lines.append(f"{ansi_prefix}{''.join(row_chars)}{ansi_reset}")

    return "\n".join(lines)


def save_qr_image(code: str, output_path: Union[Path, str], scale: int = 10) -> Path:
    """Save the QR code to an image file (PNG, SVG, etc.)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    qr = generate_labs_qr(code)
    qr.save(str(out), scale=scale)
    return out
