from __future__ import annotations

from html.parser import HTMLParser
import re
import shutil
import subprocess

import pytest

from uel_gopro.stream.live_ui import render_live_page, render_widget_js


class _TagCollector(HTMLParser):
    """Lightweight HTML5 structure parser for verifying UI DOM attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.ids: set[str] = set()
        self.styles: list[str] = []
        self.scripts: list[str] = []
        self._in_style = False
        self._style_buf: list[str] = []
        self._in_script = False
        self._script_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        lowered = tag.lower()
        self.tags.append((lowered, attr_map))
        if attr_map.get("id"):
            self.ids.add(str(attr_map["id"]))
        if lowered == "style":
            self._in_style = True
            self._style_buf = []
        elif lowered == "script":
            self._in_script = True
            self._script_buf = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "style" and self._in_style:
            self._in_style = False
            self.styles.append("".join(self._style_buf))
            self._style_buf = []
        elif lowered == "script" and self._in_script:
            self._in_script = False
            self.scripts.append("".join(self._script_buf))
            self._script_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._style_buf.append(data)
        if self._in_script:
            self._script_buf.append(data)


def _check_js_syntax(js_code: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in PATH")
    proc = subprocess.run(
        [node, "--check", "-"],
        input=js_code,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, f"node --check failed:\n{proc.stderr}"


@pytest.mark.parametrize("embed", [False, True])
def test_live_page_is_self_contained_html5_with_palette_and_stream(embed: bool) -> None:
    html = render_live_page(embed=embed)

    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<style>" in html and "<script>" in html

    # Zero external CDN or third-party URLs
    assert "https://" not in html
    assert "http://" not in html

    # Hardware monitor palette tokens & error badge styling
    for token in ("#0c0d10", "#15171c", "#262a33", "#ef4444", "#22c55e", "#f59e0b", "tabular-nums"):
        assert token in html

    parser = _TagCollector()
    parser.feed(html)

    assert len(parser.styles) == 1
    css = parser.styles[0]
    assert ".badge--err" in css
    assert ".badge--rec" in css
    assert "#8b95a7" in css
    assert "#fecaca" in css
    assert "calc(100vw - 36px)" in css

    img_tags = [attrs for tag, attrs in parser.tags if tag == "img" and attrs.get("id") == "live-feed"]
    assert len(img_tags) == 1
    assert img_tags[0].get("src") == "/stream.mjpeg"

    body_tags = [attrs for tag, attrs in parser.tags if tag == "body"]
    assert len(body_tags) == 1
    assert body_tags[0].get("data-embed") == ("true" if embed else "false")

    assert len(parser.scripts) == 1
    script = parser.scripts[0]

    # Ensure no unescaped </script> tag inside inline script body
    assert "</script" not in script.lower()

    # Keyboard shortcuts and input focus guard
    for shortcut_key in ('"r"', '"p"', '"s"', '"g"'):
        assert shortcut_key in script
    for editable_tag in ("INPUT", "SELECT", "TEXTAREA", "isContentEditable"):
        assert editable_tag in script

    # Stream error retry must respect stopped preview state & poll epoch guard exists
    assert "state.streamRunning" in script
    assert "stateEpoch" in script

    # No unsafe innerHTML usage and no raw NUL bytes
    assert "innerHTML" not in html
    assert "\x00" not in html

    _check_js_syntax(script)


def test_live_page_full_mode_contains_all_panels_and_endpoints() -> None:
    html = render_live_page(embed=False)
    parser = _TagCollector()
    parser.feed(html)

    expected_ids = {
        "conn-badge",
        "camera-label",
        "tally-badge",
        "rec-timer",
        "battery-label",
        "sd-label",
        "thermal-badge",
        "downloads-badge",
        "live-feed",
        "grid-overlay",
        "stream-overlay",
        "btn-grid",
        "btn-fullscreen",
        "btn-preview-toggle",
        "btn-record",
        "btn-photo",
        "btn-snapshot",
        "btn-pull",
        "presets-container",
        "quick-settings-grid",
        "settings-model-badge",
        "custom-setting-form",
        "setting-id-input",
        "setting-val-input",
        "transfers-list",
        "captures-list",
        "btn-refresh-captures",
        "integrate-drawer",
        "snippet-iframe",
        "snippet-widget",
        "snippet-mjpeg",
        "snippet-api",
        "toast",
    }
    assert expected_ids.issubset(parser.ids)

    css = parser.styles[0]
    assert "min(340px, 100%)" in css
    assert "minmax(0, 1fr)" in css

    expected_endpoints = (
        "/stream.mjpeg",
        "/api/status",
        "/api/presets",
        "/api/settings",
        "/api/capabilities",
        "/api/captures",
        "/api/shutter/start",
        "/api/shutter/stop",
        "/api/photo",
        "/api/snapshot",
        "/api/preset/load",
        "/api/setting",
        "/api/preview/start",
        "/api/preview/stop",
        "/api/media/pull",
    )
    for endpoint in expected_endpoints:
        assert endpoint in html

    script = parser.scripts[0]
    assert "auto_download: true" in script
    assert "auto_switch: true" in script
    assert "execCommand" in script
    assert "setSelectionRange" in script
    assert "<details" in html

    # Quick settings refresh on status poll without clobbering focused dropdown
    apply_match = re.search(r"function applyStatusPayload\(data\)\s*\{(.*?)\n  \}", script, re.DOTALL)
    assert apply_match is not None
    assert "if (!IS_EMBED)" in apply_match.group(1)
    assert "updateCapabilitiesUI(data.capabilities)" in apply_match.group(1)
    assert "updateSettingsDisplay(data.settings)" in apply_match.group(1)

    caps_match = re.search(
        r"function updateCapabilitiesUI\(capabilities\)\s*\{(.*?)\n  \}", script, re.DOTALL
    )
    assert caps_match is not None
    assert "document.activeElement" in caps_match.group(1)
    assert "quickSettingsGrid" in caps_match.group(1)
    assert "settingsModelBadge" in caps_match.group(1)

    settings_match = re.search(
        r"function updateSettingsDisplay\(settingsObj\)\s*\{(.*?)\n  \}", script, re.DOTALL
    )
    assert settings_match is not None
    assert "document.activeElement" in settings_match.group(1)

    apply_setting_match = re.search(
        r"async function applySetting\(setting, value\)\s*\{(.*?)\n  \}", script, re.DOTALL
    )
    assert apply_setting_match is not None
    assert "updateCapabilitiesUI(res.capabilities)" in apply_setting_match.group(1)
    _check_js_syntax(script)


def test_live_page_embed_mode_omits_outer_chrome_and_drawers() -> None:
    html = render_live_page(embed=True)
    parser = _TagCollector()
    parser.feed(html)

    assert 'data-embed="true"' in html
    assert "100vw" in html and "100vh" in html

    # Embed HUD + floating dock present
    assert {"live-feed", "tally-badge", "btn-record", "btn-photo", "btn-snapshot", "embed-preset-select", "toast"}.issubset(
        parser.ids
    )
    assert "embed-hud" in html
    assert "embed-dock" in html

    # Outer chrome / drawers / settings / downloads panels omitted cleanly
    for omitted_id in (
        "conn-badge",
        "downloads-badge",
        "custom-setting-form",
        "captures-list",
        "transfers-list",
        "integrate-drawer",
    ):
        assert omitted_id not in parser.ids
    assert "<details" not in html
    assert "<header" not in html


def test_widget_js_defines_web_component_and_contract() -> None:
    js = render_widget_js()

    assert "\x00" not in js
    assert "https://" not in js
    assert "http://" not in js
    assert "innerHTML" not in js

    assert "class UelGoproLiveElement extends HTMLElement" in js
    assert 'customElements.get("uel-gopro-live")' in js
    assert 'customElements.define("uel-gopro-live", UelGoproLiveElement)' in js
    assert 'attachShadow({ mode: "open" })' in js

    # Styles: error badge, high-contrast REC badge, focus-visible
    assert ".badge--err" in js
    assert ":focus-visible" in js
    assert "#fecaca" in js

    # Attributes & origin detection
    for attr in ('"server"', '"controls"', '"auto-download"'):
        assert attr in js
    assert "observedAttributes" in js
    assert "attributeChangedCallback" in js
    assert "document.currentScript" in js
    assert "window.location.origin" in js
    assert re.search(r"replace\(/\\/\+\$/", js) is not None

    # Lifecycle cleanup & server change state reset
    assert "connectedCallback()" in js
    assert "disconnectedCallback()" in js
    assert "clearInterval" in js
    assert "clearTimeout" in js
    assert "AbortController" in js
    assert "removeAttribute(\"src\")" in js
    assert "_seenCaptureIds.clear()" in js
    assert "_stateEpoch" in js

    # Accessibility on dynamic inputs
    assert "Setting ID or alias" in js
    assert "Setting numeric value" in js

    # Endpoints
    for endpoint in (
        "/stream.mjpeg",
        "/api/status",
        "/api/presets",
        "/api/shutter/start",
        "/api/shutter/stop",
        "/api/photo",
        "/api/snapshot",
        "/api/preset/load",
        "/api/media/pull",
        "/api/preview/start",
        "/api/preview/stop",
        "/api/setting",
    ):
        assert endpoint in js

    # CustomEvents with bubbles + composed
    for event_name in ("uel-status", "uel-capture", "uel-error"):
        assert f'"{event_name}"' in js
    assert "bubbles: true" in js
    assert "composed: true" in js

    _check_js_syntax(js)
