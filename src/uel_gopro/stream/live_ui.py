from __future__ import annotations

_SHARED_CSS = """\
:root {
  --bg-canvas: #0c0d10;
  --bg-panel: #15171c;
  --bg-elevated: #1c1f26;
  --border: #262a33;
  --border-strong: #343a46;
  --text: #f3f4f6;
  --text-muted: #9ca3af;
  --text-dim: #8b95a7;
  --red: #ef4444;
  --red-soft: rgba(239, 68, 68, 0.16);
  --green: #22c55e;
  --green-soft: rgba(34, 197, 94, 0.14);
  --amber: #f59e0b;
  --amber-soft: rgba(245, 158, 11, 0.16);
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

*, *::before, *::after {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  background: var(--bg-canvas);
  color: var(--text);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.4;
  -webkit-font-smoothing: antialiased;
}

.mono {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.hidden {
  display: none !important;
}

button, input, select {
  font: inherit;
  color: inherit;
}

button {
  cursor: pointer;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text);
  border-radius: 6px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background-color 120ms ease, border-color 120ms ease, opacity 120ms ease, transform 80ms ease;
}

button:hover:not(:disabled) {
  background: #232730;
  border-color: var(--border-strong);
}

button:active:not(:disabled) {
  transform: translateY(1px);
}

button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

button:focus-visible, input:focus-visible, select:focus-visible, summary:focus-visible {
  outline: 2px solid #60a5fa;
  outline-offset: 2px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}

.badge-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-dim);
  flex-shrink: 0;
}

.badge--ok {
  border-color: rgba(34, 197, 94, 0.35);
  background: var(--green-soft);
  color: var(--green);
}

.badge--ok .badge-dot {
  background: var(--green);
}

.badge--rec {
  border-color: rgba(239, 68, 68, 0.55);
  background: var(--red-soft);
  color: #fecaca;
}

.badge--rec .badge-dot {
  background: var(--red);
  box-shadow: 0 0 8px var(--red);
  animation: pulse-rec 1s infinite;
}

.badge--warn {
  border-color: rgba(245, 158, 11, 0.45);
  background: var(--amber-soft);
  color: var(--amber);
}

.badge--warn .badge-dot {
  background: var(--amber);
}

.badge--err {
  border-color: rgba(239, 68, 68, 0.45);
  background: rgba(239, 68, 68, 0.14);
  color: #fca5a5;
}

.badge--err .badge-dot {
  background: var(--red);
}

@keyframes pulse-rec {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

.btn-record {
  border-color: rgba(239, 68, 68, 0.5);
  background: rgba(239, 68, 68, 0.14);
  color: #fecaca;
}

.btn-record:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.24);
  border-color: var(--red);
}

.btn-record.is-recording {
  background: var(--red);
  border-color: var(--red);
  color: #ffffff;
}

.btn-record.is-recording:hover:not(:disabled) {
  background: #dc2626;
}

.rec-dot-icon {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--red);
  display: inline-block;
}

.btn-record.is-recording .rec-dot-icon {
  border-radius: 2px;
  background: #ffffff;
}

.viewfinder {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #060709;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

#live-feed {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
  user-select: none;
}

.reticle {
  position: absolute;
  width: 18px;
  height: 18px;
  pointer-events: none;
  border-color: rgba(255, 255, 255, 0.38);
  border-style: solid;
  z-index: 2;
}

.reticle-tl { top: 12px; left: 12px; border-width: 2px 0 0 2px; }
.reticle-tr { top: 12px; right: 12px; border-width: 2px 2px 0 0; }
.reticle-bl { bottom: 12px; left: 12px; border-width: 0 0 2px 2px; }
.reticle-br { bottom: 12px; right: 12px; border-width: 0 2px 2px 0; }

.grid-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 2;
}

.grid-line-v1, .grid-line-v2, .grid-line-h1, .grid-line-h2 {
  position: absolute;
  background: rgba(255, 255, 255, 0.22);
}

.grid-line-v1 { top: 0; bottom: 0; left: 33.3333%; width: 1px; }
.grid-line-v2 { top: 0; bottom: 0; left: 66.6667%; width: 1px; }
.grid-line-h1 { left: 0; right: 0; top: 33.3333%; height: 1px; }
.grid-line-h2 { left: 0; right: 0; top: 66.6667%; height: 1px; }

.stream-overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  background: rgba(12, 13, 16, 0.84);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 20px;
  text-align: center;
}

.stream-overlay-title {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--amber);
}

.stream-overlay-msg {
  font-size: 12px;
  color: var(--text-muted);
  max-width: 420px;
}

.toast {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 50;
  min-width: 240px;
  max-width: min(420px, calc(100vw - 36px));
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--bg-panel);
  color: var(--text);
  font-size: 12px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55);
  opacity: 0;
  transform: translateY(8px);
  pointer-events: none;
  transition: opacity 150ms ease, transform 150ms ease;
}

.toast.is-visible {
  opacity: 1;
  transform: translateY(0);
  pointer-events: auto;
}

.toast--ok {
  border-color: rgba(34, 197, 94, 0.5);
}

.toast--warn {
  border-color: rgba(245, 158, 11, 0.5);
}

.toast--err {
  border-color: rgba(239, 68, 68, 0.6);
}
"""

_FULL_CSS = """\
.app-shell {
  max-width: 1440px;
  margin: 0 auto;
  padding: 14px 16px 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.topbar {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.topbar-left, .topbar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.brand-mark {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
  margin-right: 4px;
}

.telemetry-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 9px;
  border-radius: 5px;
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--text);
  max-width: min(340px, 100%);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.telemetry-key {
  color: var(--text-dim);
  text-transform: uppercase;
  font-size: 10px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.75fr) minmax(320px, 1fr);
  gap: 14px;
  align-items: start;
}

@media (max-width: 1040px) {
  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

.main-col, .side-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.panel-title {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.stage-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
}

.stage-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.shutter-bar {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

@media (max-width: 640px) {
  .shutter-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.shutter-bar button {
  padding: 11px 12px;
  font-size: 13px;
}

.kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  border: 1px solid var(--border-strong);
  background: rgba(0, 0, 0, 0.25);
  color: var(--text-muted);
}

.preset-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.preset-group-label {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-dim);
  margin-bottom: 5px;
}

.preset-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.preset-btn {
  padding: 6px 10px;
  font-size: 12px;
}

.preset-btn.is-active {
  border-color: var(--green);
  background: var(--green-soft);
  color: var(--green);
}

.settings-quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 10px;
}

@media (max-width: 500px) {
  .settings-quick-grid {
    grid-template-columns: 1fr;
  }
}

.setting-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.setting-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  font-size: 11px;
}

.setting-name {
  font-family: var(--font-mono);
  font-weight: 700;
  text-transform: uppercase;
  color: var(--text-muted);
  flex-shrink: 0;
}

.setting-current {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--green);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.setting-select, .text-input {
  width: 100%;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 6px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
}

.custom-setting-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 6px;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.transfers-list, .captures-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.transfer-item, .capture-item {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.item-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.item-name {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.item-path {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-dim);
  word-break: break-all;
}

.progress-track {
  height: 5px;
  border-radius: 999px;
  background: var(--bg-elevated);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--green);
  transition: width 150ms ease;
}

.empty-state {
  font-size: 12px;
  color: var(--text-dim);
  padding: 6px 0;
}

details.integrate-drawer {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
}

details.integrate-drawer summary {
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
  list-style: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.snippet-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

@media (max-width: 780px) {
  .snippet-grid {
    grid-template-columns: 1fr;
  }
}

.snippet-card {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.snippet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.snippet-title {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
}

.snippet-code {
  margin: 0;
  padding: 8px;
  border-radius: 5px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
"""

_EMBED_CSS = """\
html, body.embed {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: var(--bg-canvas);
}

.embed-stage {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #060709;
}

.embed-stage .viewfinder {
  width: 100%;
  height: 100%;
  aspect-ratio: auto;
  border: 0;
  border-radius: 0;
}

.embed-hud {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  background: rgba(12, 13, 16, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(8px);
}

.embed-hud-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.embed-stat {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--text);
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(21, 23, 28, 0.8);
  border: 1px solid var(--border);
}

.embed-dock {
  position: absolute;
  left: 50%;
  bottom: 14px;
  transform: translateX(-50%);
  z-index: 10;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(21, 23, 28, 0.82);
  border: 1px solid var(--border-strong);
  backdrop-filter: blur(8px);
  max-width: calc(100vw - 24px);
}

.embed-select {
  background: var(--bg-canvas);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  max-width: 190px;
}

.toast {
  bottom: 72px;
}
"""

_FULL_BODY = """\
<div class="app-shell">
  <header class="topbar" aria-label="Camera status bar">
    <div class="topbar-left">
      <span class="brand-mark">UEL // GOPRO</span>
      <span id="conn-badge" class="badge"><span class="badge-dot"></span><span id="conn-text">CONNECTING</span></span>
      <span id="camera-label" class="telemetry-chip">Camera: --</span>
      <span id="tally-badge" class="badge"><span class="badge-dot"></span><span id="tally-text">STANDBY</span> <span id="rec-timer" class="mono">00:00</span></span>
    </div>
    <div class="topbar-right">
      <span class="telemetry-chip"><span class="telemetry-key">MODE</span> <span id="mode-label">--</span></span>
      <span class="telemetry-chip"><span class="telemetry-key">BAT</span> <span id="battery-label">--</span></span>
      <span class="telemetry-chip"><span class="telemetry-key">SD</span> <span id="sd-label">--</span></span>
      <span id="thermal-badge" class="badge badge--warn hidden"><span class="badge-dot"></span><span>THERMAL HIGH</span></span>
      <span class="telemetry-chip" title="Downloads directory"><span class="telemetry-key">DIR</span> <span id="downloads-badge">--</span></span>
    </div>
  </header>

  <main class="workspace-grid">
    <div class="main-col">
      <section class="panel" aria-label="Live viewfinder">
        <div class="stage-toolbar">
          <span id="stream-badge" class="badge"><span class="badge-dot"></span><span id="stream-badge-text">STREAM INIT</span></span>
          <div class="stage-actions">
            <button id="btn-grid" type="button" aria-label="Toggle rule of thirds grid" aria-pressed="false">Grid <span class="kbd">G</span></button>
            <button id="btn-fullscreen" type="button" aria-label="Toggle fullscreen">Fullscreen</button>
            <button id="btn-preview-toggle" type="button" aria-label="Start or stop preview stream">Start Preview</button>
          </div>
        </div>
        <div id="viewfinder-frame" class="viewfinder">
          <img id="live-feed" src="/stream.mjpeg" alt="GoPro Live Stream">
          <span class="reticle reticle-tl" aria-hidden="true"></span>
          <span class="reticle reticle-tr" aria-hidden="true"></span>
          <span class="reticle reticle-bl" aria-hidden="true"></span>
          <span class="reticle reticle-br" aria-hidden="true"></span>
          <div id="grid-overlay" class="grid-overlay hidden" aria-hidden="true">
            <div class="grid-line-v1"></div>
            <div class="grid-line-v2"></div>
            <div class="grid-line-h1"></div>
            <div class="grid-line-h2"></div>
          </div>
          <div id="stream-overlay" class="stream-overlay">
            <div id="stream-overlay-title" class="stream-overlay-title">Connecting Viewfinder</div>
            <div id="stream-overlay-msg" class="stream-overlay-msg">Waiting for live MJPEG frames from camera preview stream...</div>
            <button id="btn-retry-stream" type="button" aria-label="Reconnect live stream">Reconnect Feed</button>
          </div>
        </div>
      </section>

      <section class="panel" aria-label="Primary shutter and capture controls">
        <div class="shutter-bar">
          <button id="btn-record" class="btn-record" type="button" aria-label="Start or stop video recording">
            <span class="rec-dot-icon" aria-hidden="true"></span>
            <span id="btn-record-label">Record</span>
            <span class="kbd">R</span>
          </button>
          <button id="btn-photo" type="button" aria-label="Take photo and save to Downloads">
            <span>Take Photo</span>
            <span class="kbd">P</span>
          </button>
          <button id="btn-snapshot" type="button" aria-label="Grab live frame JPEG to Downloads">
            <span>Grab Frame</span>
            <span class="kbd">S</span>
          </button>
          <button id="btn-pull" type="button" aria-label="Pull latest media file from camera SD card">
            <span>Pull Latest</span>
          </button>
        </div>
      </section>
    </div>

    <aside class="side-col" aria-label="Camera controls and saved captures">
      <section class="panel" aria-label="Presets">
        <div class="panel-head">
          <h2 class="panel-title">Presets</h2>
          <span id="active-preset-chip" class="mono" style="font-size:11px;color:var(--text-dim);">Preset: --</span>
        </div>
        <div id="presets-container" class="preset-groups">
          <div class="empty-state">Loading camera presets...</div>
        </div>
      </section>

      <section class="panel" aria-label="Settings">
        <div class="panel-head">
          <h2 class="panel-title">Quick Settings</h2>
          <span id="settings-model-badge" class="mono" style="font-size:10px;color:var(--text-dim);">OPEN GOPRO</span>
        </div>
        <div id="quick-settings-grid" class="settings-quick-grid">
          <div class="empty-state">Loading camera settings...</div>
        </div>
        <form id="custom-setting-form" class="custom-setting-form">
          <input id="setting-id-input" class="text-input" type="text" placeholder="Setting ID or alias" aria-label="Setting ID or alias">
          <input id="setting-val-input" class="text-input" type="number" placeholder="Value" aria-label="Setting numeric value">
          <button id="btn-apply-setting" type="submit" aria-label="Apply custom camera setting">Apply</button>
        </form>
      </section>

      <section class="panel" aria-label="Saved to Downloads">
        <div class="panel-head">
          <h2 class="panel-title">Saved to Downloads</h2>
          <div style="display:flex;align-items:center;gap:8px;">
            <span id="captures-count" class="mono" style="font-size:11px;color:var(--text-dim);">0 files</span>
            <button id="btn-refresh-captures" type="button" style="padding:3px 8px;font-size:11px;" aria-label="Refresh saved captures list">Refresh</button>
          </div>
        </div>
        <div id="transfers-list" class="transfers-list"></div>
        <div id="captures-list" class="captures-list">
          <div class="empty-state">No captures saved in this session yet.</div>
        </div>
      </section>
    </aside>
  </main>

  <details id="integrate-drawer" class="integrate-drawer">
    <summary>
      <span>Integrate / Embed</span>
      <span class="mono" style="font-size:11px;color:var(--text-dim);">IFRAME · WEB COMPONENT · MJPEG</span>
    </summary>
    <div class="snippet-grid">
      <div class="snippet-card">
        <div class="snippet-head">
          <span class="snippet-title">Iframe / OBS Browser Source</span>
          <button type="button" class="copy-btn" data-copy-target="snippet-iframe" aria-label="Copy iframe embed code">Copy</button>
        </div>
        <pre id="snippet-iframe" class="snippet-code"></pre>
      </div>
      <div class="snippet-card">
        <div class="snippet-head">
          <span class="snippet-title">Web Component (&lt;uel-gopro-live&gt;)</span>
          <button type="button" class="copy-btn" data-copy-target="snippet-widget" aria-label="Copy Web Component embed code">Copy</button>
        </div>
        <pre id="snippet-widget" class="snippet-code"></pre>
      </div>
      <div class="snippet-card">
        <div class="snippet-head">
          <span class="snippet-title">MJPEG Stream URL</span>
          <button type="button" class="copy-btn" data-copy-target="snippet-mjpeg" aria-label="Copy MJPEG stream URL">Copy</button>
        </div>
        <pre id="snippet-mjpeg" class="snippet-code"></pre>
      </div>
      <div class="snippet-card">
        <div class="snippet-head">
          <span class="snippet-title">JSON Status API</span>
          <button type="button" class="copy-btn" data-copy-target="snippet-api" aria-label="Copy JSON status API URL">Copy</button>
        </div>
        <pre id="snippet-api" class="snippet-code"></pre>
      </div>
    </div>
  </details>
</div>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
"""

_EMBED_BODY = """\
<div class="embed-stage">
  <div id="viewfinder-frame" class="viewfinder">
    <img id="live-feed" src="/stream.mjpeg" alt="GoPro Live Stream">
    <span class="reticle reticle-tl" aria-hidden="true"></span>
    <span class="reticle reticle-tr" aria-hidden="true"></span>
    <span class="reticle reticle-bl" aria-hidden="true"></span>
    <span class="reticle reticle-br" aria-hidden="true"></span>
    <div id="grid-overlay" class="grid-overlay hidden" aria-hidden="true">
      <div class="grid-line-v1"></div>
      <div class="grid-line-v2"></div>
      <div class="grid-line-h1"></div>
      <div class="grid-line-h2"></div>
    </div>
    <div id="stream-overlay" class="stream-overlay">
      <div id="stream-overlay-title" class="stream-overlay-title">Connecting Viewfinder</div>
      <div id="stream-overlay-msg" class="stream-overlay-msg">Waiting for live MJPEG frames...</div>
      <button id="btn-retry-stream" type="button" aria-label="Reconnect live stream">Reconnect</button>
    </div>
  </div>

  <div class="embed-hud" aria-label="Camera HUD">
    <div class="embed-hud-group">
      <span id="tally-badge" class="badge"><span class="badge-dot"></span><span id="tally-text">STANDBY</span> <span id="rec-timer" class="mono">00:00</span></span>
      <span id="mode-label" class="embed-stat">--</span>
    </div>
    <div class="embed-hud-group">
      <span id="battery-label" class="embed-stat">BAT --</span>
      <span id="sd-label" class="embed-stat">SD --</span>
      <span id="thermal-badge" class="badge badge--warn hidden"><span class="badge-dot"></span><span>HOT</span></span>
    </div>
  </div>

  <div class="embed-dock" aria-label="Camera quick controls">
    <button id="btn-record" class="btn-record" type="button" aria-label="Start or stop video recording">
      <span class="rec-dot-icon" aria-hidden="true"></span>
      <span id="btn-record-label">Record</span>
    </button>
    <button id="btn-photo" type="button" aria-label="Take photo and save to Downloads">Photo</button>
    <button id="btn-snapshot" type="button" aria-label="Grab live frame snapshot">Snapshot</button>
    <select id="embed-preset-select" class="embed-select" aria-label="Select camera preset">
      <option value="">Presets...</option>
    </select>
    <button id="btn-grid" type="button" aria-label="Toggle rule of thirds grid" aria-pressed="false">Grid</button>
  </div>
</div>
<div id="toast" class="toast" role="status" aria-live="polite"></div>
"""

_PAGE_SCRIPT = """\
(() => {
  "use strict";

  const IS_EMBED = document.body.getAttribute("data-embed") === "true";
  const STREAM_PATH = "/stream.mjpeg";

  const el = (id) => document.getElementById(id);
  const liveFeed = el("live-feed");
  const streamOverlay = el("stream-overlay");
  const streamOverlayTitle = el("stream-overlay-title");
  const streamOverlayMsg = el("stream-overlay-msg");
  const gridOverlay = el("grid-overlay");
  const viewfinderFrame = el("viewfinder-frame");
  const tallyBadge = el("tally-badge");
  const tallyText = el("tally-text");
  const recTimerEl = el("rec-timer");
  const modeLabel = el("mode-label");
  const batteryLabel = el("battery-label");
  const sdLabel = el("sd-label");
  const thermalBadge = el("thermal-badge");
  const btnRecord = el("btn-record");
  const btnRecordLabel = el("btn-record-label");
  const btnPhoto = el("btn-photo");
  const btnSnapshot = el("btn-snapshot");
  const btnGrid = el("btn-grid");
  const btnRetryStream = el("btn-retry-stream");
  const toastEl = el("toast");

  // Full-mode optional DOM elements
  const connBadge = el("conn-badge");
  const connText = el("conn-text");
  const cameraLabel = el("camera-label");
  const downloadsBadge = el("downloads-badge");
  const streamBadge = el("stream-badge");
  const streamBadgeText = el("stream-badge-text");
  const btnFullscreen = el("btn-fullscreen");
  const btnPreviewToggle = el("btn-preview-toggle");
  const btnPull = el("btn-pull");
  const presetsContainer = el("presets-container");
  const activePresetChip = el("active-preset-chip");
  const embedPresetSelect = el("embed-preset-select");
  const quickSettingsGrid = el("quick-settings-grid");
  const settingsModelBadge = el("settings-model-badge");
  const customSettingForm = el("custom-setting-form");
  const settingIdInput = el("setting-id-input");
  const settingValInput = el("setting-val-input");
  const transfersList = el("transfers-list");
  const capturesList = el("captures-list");
  const capturesCount = el("captures-count");
  const btnRefreshCaptures = el("btn-refresh-captures");

  const state = {
    isRecording: false,
    streamRunning: true,
    hasFrame: false,
    streamLoadedOnce: false,
    recordingElapsedSec: 0,
    lastStatusAt: 0,
    currentPreset: null,
    presetsLoaded: false,
    pollInFlight: false,
    pollSeq: 0,
    stateEpoch: 0,
    retryTimer: null,
    toastTimer: null,
    seenCaptureIds: new Set(),
    initializedCaptures: false
  };

  function formatDuration(totalSec) {
    const sec = Math.max(0, Math.floor(Number(totalSec) || 0));
    const hrs = Math.floor(sec / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    const rem = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    if (hrs > 0) {
      return `${pad(hrs)}:${pad(mins)}:${pad(rem)}`;
    }
    return `${pad(mins)}:${pad(rem)}`;
  }

  function formatBytes(bytes) {
    const val = Number(bytes);
    if (!Number.isFinite(val) || val < 0) return "--";
    if (val < 1024) return `${val} B`;
    if (val < 1024 * 1024) return `${(val / 1024).toFixed(1)} KB`;
    if (val < 1024 * 1024 * 1024) return `${(val / (1024 * 1024)).toFixed(1)} MB`;
    return `${(val / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  function formatSdSpace(mb) {
    const val = Number(mb);
    if (!Number.isFinite(val) || val < 0) return "--";
    if (val >= 1024) return `${(val / 1024).toFixed(1)} GB`;
    return `${Math.round(val)} MB`;
  }

  function formatTimestamp(iso) {
    if (!iso) return "--";
    const dt = new Date(iso);
    if (Number.isNaN(dt.getTime())) return String(iso);
    return dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function showToast(message, tone = "ok") {
    if (!toastEl) return;
    toastEl.textContent = String(message || "");
    toastEl.className = `toast is-visible toast--${tone}`;
    if (state.toastTimer) {
      clearTimeout(state.toastTimer);
    }
    state.toastTimer = setTimeout(() => {
      toastEl.classList.remove("is-visible");
    }, 3500);
  }

  async function apiJson(path, method = "GET", body = undefined) {
    const opts = {
      method,
      headers: { Accept: "application/json" }
    };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    let data = {};
    try {
      data = await resp.json();
    } catch (_) {
      data = {};
    }
    if (!resp.ok || data.ok === false) {
      const msg = data.error || data.detail || `Request failed (${resp.status})`;
      throw new Error(msg);
    }
    return data;
  }

  async function withButtonBusy(button, fn) {
    if (!button || button.disabled) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      await fn();
    } finally {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  function scheduleStreamRetry(delayMs = 1500) {
    if (state.retryTimer) return;
    state.retryTimer = setTimeout(() => {
      state.retryTimer = null;
      reloadStream();
    }, delayMs);
  }

  function reloadStream() {
    if (!liveFeed) return;
    if (state.retryTimer) {
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
    }
    liveFeed.src = `${STREAM_PATH}?t=${Date.now()}`;
  }

  function updateStreamOverlay(stream) {
    const running = Boolean(stream && stream.running);
    const hasFrame = Boolean(stream && stream.has_frame);
    const streamErr = stream && stream.error ? String(stream.error) : "";
    const showOverlay = !running || (!hasFrame && !state.streamLoadedOnce);

    if (!running && state.retryTimer) {
      clearTimeout(state.retryTimer);
      state.retryTimer = null;
    }

    if (streamOverlay) {
      streamOverlay.classList.toggle("hidden", !showOverlay);
    }
    if (showOverlay && streamOverlayTitle && streamOverlayMsg) {
      if (!running) {
        streamOverlayTitle.textContent = "Preview Stopped";
        streamOverlayMsg.textContent = streamErr || "Live preview stream is currently stopped.";
      } else if (streamErr) {
        streamOverlayTitle.textContent = "Stream Reconnecting";
        streamOverlayMsg.textContent = streamErr;
      } else {
        streamOverlayTitle.textContent = "Connecting Viewfinder";
        streamOverlayMsg.textContent = "Waiting for live MJPEG frames from camera preview stream...";
      }
    }

    if (streamBadge && streamBadgeText) {
      streamBadge.className = "badge";
      if (running && (hasFrame || state.streamLoadedOnce)) {
        streamBadge.classList.add("badge--ok");
        streamBadgeText.textContent = "STREAM LIVE";
      } else if (running) {
        streamBadge.classList.add("badge--warn");
        streamBadgeText.textContent = "CONNECTING";
      } else {
        streamBadgeText.textContent = "STREAM OFF";
      }
    }

    if (btnPreviewToggle) {
      btnPreviewToggle.textContent = running ? "Stop Preview" : "Start Preview";
    }
  }

  function _buildQuickSettingCard(alias, spec) {
    const card = document.createElement("div");
    card.className = "setting-card";
    card.id = `card-${alias}`;
    card.setAttribute("data-setting-alias", alias);

    const head = document.createElement("div");
    head.className = "setting-card-head";

    const nameEl = document.createElement("span");
    nameEl.className = "setting-name";
    nameEl.textContent = spec.label || alias;

    const valEl = document.createElement("span");
    valEl.className = "setting-current";
    valEl.id = `val-${alias}`;
    valEl.textContent = "--";

    head.appendChild(nameEl);
    head.appendChild(valEl);

    const selEl = document.createElement("select");
    selEl.className = "setting-select";
    selEl.id = `select-${alias}`;
    selEl.setAttribute("data-setting", alias);
    selEl.setAttribute("aria-label", `${spec.label || alias} setting`);
    selEl.addEventListener("change", () => {
      if (selEl.value === "") return;
      applySetting(alias, selEl.value).catch((err) => {
        showToast(err.message, "err");
        refreshStatus({ force: true });
      });
    });

    card.appendChild(head);
    card.appendChild(selEl);
    return card;
  }

  function updateCapabilitiesUI(capabilities) {
    if (!capabilities || typeof capabilities !== "object") return;
    if (settingsModelBadge) {
      const modelLabel = capabilities.model || "OPEN GOPRO";
      const hzLabel = capabilities.anti_flicker_hz ? `${capabilities.anti_flicker_hz} Hz` : "";
      settingsModelBadge.textContent = hzLabel ? `${modelLabel} · ${hzLabel}` : modelLabel;
    }
    if (!quickSettingsGrid) return;

    const settingsMap = capabilities.settings;
    if (!settingsMap || typeof settingsMap !== "object") return;
    const entries = Object.entries(settingsMap);
    if (entries.length === 0) {
      quickSettingsGrid.textContent = "";
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No camera quick settings available.";
      quickSettingsGrid.appendChild(empty);
      return;
    }

    // Clear loading/empty placeholders once settings arrive
    quickSettingsGrid.querySelectorAll(".empty-state").forEach((node) => node.remove());

    const activeAliases = new Set(entries.map(([alias]) => alias));
    quickSettingsGrid.querySelectorAll("[data-setting-alias]").forEach((cardNode) => {
      const alias = cardNode.getAttribute("data-setting-alias");
      if (alias && !activeAliases.has(alias)) {
        const selNode = el(`select-${alias}`);
        if (!selNode || document.activeElement !== selNode) {
          cardNode.remove();
        }
      }
    });

    entries.forEach(([alias, spec], index) => {
      if (!spec || typeof spec !== "object") return;
      let card = el(`card-${alias}`);
      if (!card) {
        card = _buildQuickSettingCard(alias, spec);
      }

      const currentChild = quickSettingsGrid.children[index];
      if (currentChild !== card) {
        const selElCheck = el(`select-${alias}`);
        if (!selElCheck || document.activeElement !== selElCheck) {
          quickSettingsGrid.insertBefore(card, currentChild || null);
        }
      }

      const nameEl = card.querySelector(".setting-name");
      if (nameEl) {
        nameEl.textContent = spec.label || alias;
      }

      const badgeEl = el(`val-${alias}`);
      if (badgeEl) {
        if (spec.current_label) {
          badgeEl.textContent = String(spec.current_label);
        } else if (spec.current !== null && spec.current !== undefined) {
          badgeEl.textContent = String(spec.current);
        } else {
          badgeEl.textContent = "--";
        }
      }

      const selEl = el(`select-${alias}`);
      if (selEl) {
        selEl.setAttribute("aria-label", `${spec.label || alias} setting`);
      }
      if (selEl && document.activeElement !== selEl) {
        const options = Array.isArray(spec.options) ? spec.options : [];
        const hasCurrent = spec.current !== null && spec.current !== undefined;
        const desired = [];
        if (!hasCurrent) {
          desired.push({ value: "", label: `Select ${spec.label || alias}...` });
        }
        for (const opt of options) {
          if (!opt || opt.value === undefined || opt.value === null) continue;
          desired.push({
            value: String(opt.value),
            label: opt.label ? String(opt.label) : String(opt.value),
          });
        }

        const existing = [...selEl.options].map((o) => `${o.value}\\u0000${o.textContent}`);
        const target = desired.map((o) => `${o.value}\\u0000${o.label}`);
        const optionsChanged =
          existing.length !== target.length ||
          existing.some((item, idx) => item !== target[idx]);

        if (optionsChanged) {
          selEl.textContent = "";
          for (const item of desired) {
            const optEl = document.createElement("option");
            optEl.value = item.value;
            optEl.textContent = item.label;
            selEl.appendChild(optEl);
          }
        }
        selEl.value = hasCurrent ? String(spec.current) : "";
      }
    });
  }

  function updateSettingsDisplay(settingsObj) {
    if (!settingsObj || typeof settingsObj !== "object") return;
    const mapping = [
      ["resolution", ["2", 2, "resolution"]],
      ["fps", ["3", 3, "fps"]],
      ["fov", ["121", 121, "fov"]],
      ["anti_flicker", ["134", 134, "anti_flicker"]],
      ["hypersmooth", ["135", 135, "hypersmooth"]],
      ["bitrate", ["182", 182, "bitrate"]]
    ];
    for (const [alias, keys] of mapping) {
      let val = undefined;
      for (const k of keys) {
        if (settingsObj[k] !== undefined && settingsObj[k] !== null) {
          val = settingsObj[k];
          break;
        }
      }
      const badgeEl = el(`val-${alias}`);
      if (badgeEl) {
        badgeEl.textContent = val !== undefined ? String(val) : "--";
      }
      const selEl = el(`select-${alias}`);
      if (selEl && val !== undefined && document.activeElement !== selEl) {
        const strVal = String(val);
        if ([...selEl.options].some((opt) => opt.value === strVal)) {
          selEl.value = strVal;
        }
      }
    }
  }

  function renderPresets(groups) {
    const groupList = Array.isArray(groups) ? groups : [];
    const activeId = state.currentPreset !== null && state.currentPreset !== undefined
      ? String(state.currentPreset)
      : null;

    if (presetsContainer) {
      presetsContainer.textContent = "";
      if (groupList.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "No camera presets available.";
        presetsContainer.appendChild(empty);
      } else {
        for (const group of groupList) {
          const wrapper = document.createElement("div");
          const label = document.createElement("div");
          label.className = "preset-group-label";
          label.textContent = group.name || `Group ${group.id ?? ""}`;
          wrapper.appendChild(label);

          const row = document.createElement("div");
          row.className = "preset-list";
          const presets = Array.isArray(group.presets) ? group.presets : [];
          for (const preset of presets) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "preset-btn";
            btn.setAttribute("data-preset-id", String(preset.id));
            btn.setAttribute("aria-label", `Load preset ${preset.name || preset.id}`);
            if (activeId !== null && String(preset.id) === activeId) {
              btn.classList.add("is-active");
            }
            btn.textContent = preset.name || `Preset ${preset.id}`;
            btn.addEventListener("click", () => {
              withButtonBusy(btn, () => loadPreset(preset.id, preset.name)).catch((err) => showToast(err.message, "err"));
            });
            row.appendChild(btn);
          }
          wrapper.appendChild(row);
          presetsContainer.appendChild(wrapper);
        }
      }
    }

    if (embedPresetSelect) {
      embedPresetSelect.textContent = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Select Preset...";
      embedPresetSelect.appendChild(placeholder);
      for (const group of groupList) {
        const optGroup = document.createElement("optgroup");
        optGroup.label = group.name || `Group ${group.id ?? ""}`;
        const presets = Array.isArray(group.presets) ? group.presets : [];
        for (const preset of presets) {
          const opt = document.createElement("option");
          opt.value = String(preset.id);
          opt.textContent = preset.name || `Preset ${preset.id}`;
          if (activeId !== null && String(preset.id) === activeId) {
            opt.selected = true;
          }
          optGroup.appendChild(opt);
        }
        embedPresetSelect.appendChild(optGroup);
      }
    }
  }

  function highlightActivePreset(currentPreset) {
    state.currentPreset = currentPreset;
    const activeId = currentPreset !== null && currentPreset !== undefined && currentPreset !== ""
      ? String(currentPreset)
      : null;
    if (activePresetChip) {
      activePresetChip.textContent = activeId !== null ? `Preset: ${activeId}` : "Preset: --";
    }
    if (presetsContainer) {
      const btns = presetsContainer.querySelectorAll("[data-preset-id]");
      for (const btn of btns) {
        btn.classList.toggle("is-active", activeId !== null && btn.getAttribute("data-preset-id") === activeId);
      }
    }
    if (embedPresetSelect) {
      if (activeId !== null && [...embedPresetSelect.options].some((o) => o.value === activeId)) {
        embedPresetSelect.value = activeId;
      } else {
        embedPresetSelect.value = "";
      }
    }
  }

  function renderTransfers(transfers) {
    if (!transfersList) return;
    transfersList.textContent = "";
    const list = Array.isArray(transfers) ? transfers : [];
    const active = list.filter((t) => t && t.status !== "completed");
    for (const tr of active) {
      const card = document.createElement("div");
      card.className = "transfer-item";

      const top = document.createElement("div");
      top.className = "item-top";
      const name = document.createElement("span");
      name.className = "item-name";
      name.textContent = tr.filename || "Downloading...";
      const statusBadge = document.createElement("span");
      statusBadge.className = tr.status === "failed" ? "badge badge--err" : "badge badge--warn";
      statusBadge.textContent = String(tr.status || "pending").toUpperCase();
      top.appendChild(name);
      top.appendChild(statusBadge);
      card.appendChild(top);

      if (tr.status !== "failed") {
        const track = document.createElement("div");
        track.className = "progress-track";
        const fill = document.createElement("div");
        fill.className = "progress-fill";
        const pct = Number.isFinite(Number(tr.percent)) ? Math.min(100, Math.max(0, Number(tr.percent))) : 0;
        fill.style.width = `${pct}%`;
        track.appendChild(fill);
        card.appendChild(track);
      }

      const meta = document.createElement("div");
      meta.className = "item-meta";
      if (tr.error) {
        meta.textContent = String(tr.error);
      } else {
        const pctText = Number.isFinite(Number(tr.percent)) ? `${Number(tr.percent).toFixed(0)}%` : "";
        meta.textContent = `${formatBytes(tr.bytes_downloaded)} / ${formatBytes(tr.total_bytes)} ${pctText}`.trim();
      }
      card.appendChild(meta);
      transfersList.appendChild(card);
    }
  }

  function renderCaptures(captures) {
    if (!capturesList) return;
    const list = Array.isArray(captures) ? captures : [];
    if (capturesCount) {
      capturesCount.textContent = `${list.length} file${list.length === 1 ? "" : "s"}`;
    }

    if (!state.initializedCaptures) {
      for (const item of list) {
        if (item && item.id) state.seenCaptureIds.add(item.id);
      }
      state.initializedCaptures = true;
    } else {
      for (const item of list) {
        if (item && item.id && !state.seenCaptureIds.has(item.id)) {
          state.seenCaptureIds.add(item.id);
          showToast(`Saved ${item.filename} to Downloads`, "ok");
        }
      }
    }

    capturesList.textContent = "";
    if (list.length === 0) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent = "No captures saved in this session yet.";
      capturesList.appendChild(empty);
      return;
    }

    for (const cap of list) {
      const card = document.createElement("div");
      card.className = "capture-item";

      const top = document.createElement("div");
      top.className = "item-top";
      const fname = document.createElement("span");
      fname.className = "item-name";
      fname.textContent = cap.filename || "capture";

      const sourceBadge = document.createElement("span");
      const srcLabel = String(cap.source || "camera").toUpperCase();
      sourceBadge.className = srcLabel === "SNAPSHOT" ? "badge" : "badge badge--ok";
      sourceBadge.textContent = srcLabel;

      top.appendChild(fname);
      top.appendChild(sourceBadge);
      card.appendChild(top);

      const meta = document.createElement("div");
      meta.className = "item-meta";
      const sizeSpan = document.createElement("span");
      sizeSpan.textContent = formatBytes(cap.size_bytes);
      const timeSpan = document.createElement("span");
      timeSpan.textContent = formatTimestamp(cap.captured_at);
      meta.appendChild(sizeSpan);
      meta.appendChild(timeSpan);
      card.appendChild(meta);

      if (cap.local_path) {
        const pathDiv = document.createElement("div");
        pathDiv.className = "item-path";
        pathDiv.textContent = String(cap.local_path);
        card.appendChild(pathDiv);
      }

      capturesList.appendChild(card);
    }
  }

  function applyStatusPayload(data) {
    const cam = data.camera || {};
    const camStatus = data.status || {};
    const stream = data.stream || {};
    const connected = Boolean(camStatus.connected);
    const recording = Boolean(camStatus.is_recording || camStatus.encoding_active);

    state.isRecording = recording;
    state.streamRunning = Boolean(stream.running);
    state.hasFrame = Boolean(stream.has_frame);
    state.recordingElapsedSec = Number(data.recording_elapsed_sec) || 0;
    state.lastStatusAt = Date.now();

    if (connBadge && connText) {
      connBadge.className = "badge";
      if (connected) {
        connBadge.classList.add("badge--ok");
        connText.textContent = "CONNECTED";
      } else if (data.status_error) {
        connBadge.classList.add("badge--warn");
        connText.textContent = "OFFLINE";
      } else {
        connText.textContent = "DISCONNECTED";
      }
    }

    if (cameraLabel) {
      const model = cam.model_name || "GoPro";
      const link = cam.transport ? String(cam.transport).toUpperCase() : "LINK";
      const ip = cam.ip_address || "--";
      cameraLabel.textContent = `${model} · ${link} · ${ip}`;
    }

    if (downloadsBadge && data.downloads_dir) {
      downloadsBadge.textContent = String(data.downloads_dir);
    }

    if (tallyBadge && tallyText) {
      tallyBadge.className = "badge";
      if (recording) {
        tallyBadge.classList.add("badge--rec");
        tallyText.textContent = "REC";
      } else if (state.streamRunning && (state.hasFrame || state.streamLoadedOnce)) {
        tallyBadge.classList.add("badge--ok");
        tallyText.textContent = "LIVE";
      } else {
        tallyText.textContent = "STANDBY";
      }
    }

    if (recTimerEl) {
      recTimerEl.textContent = recording ? formatDuration(state.recordingElapsedSec) : "00:00";
    }

    if (btnRecord && btnRecordLabel) {
      btnRecord.classList.toggle("is-recording", recording);
      btnRecordLabel.textContent = recording ? "Stop" : "Record";
    }

    if (modeLabel) {
      modeLabel.textContent = camStatus.current_mode || "--";
    }

    if (batteryLabel) {
      const pct = camStatus.battery_percent;
      const pctStr = pct !== null && pct !== undefined ? `${pct}%` : "--";
      const chg = camStatus.is_charging ? " CHG" : "";
      batteryLabel.textContent = IS_EMBED ? `BAT ${pctStr}${chg}` : `${pctStr}${chg}`;
    }

    if (sdLabel) {
      const freeStr = formatSdSpace(camStatus.sd_remaining_mb);
      if (IS_EMBED) {
        sdLabel.textContent = `SD ${freeStr}`;
      } else {
        const remVid = camStatus.sd_remaining_video_time_sec !== null && camStatus.sd_remaining_video_time_sec !== undefined
          ? formatDuration(camStatus.sd_remaining_video_time_sec)
          : "--";
        const remImg = camStatus.sd_remaining_photos !== null && camStatus.sd_remaining_photos !== undefined
          ? `${camStatus.sd_remaining_photos} IMG`
          : "--";
        const sdState = camStatus.sd_status || "UNKNOWN";
        sdLabel.textContent = `${freeStr} · ${remVid} · ${remImg} (${sdState})`;
      }
    }

    if (thermalBadge) {
      thermalBadge.classList.toggle("hidden", !camStatus.system_hot);
    }

    highlightActivePreset(camStatus.current_preset);
    if (!IS_EMBED) {
      if (data.capabilities) {
        updateCapabilitiesUI(data.capabilities);
      } else if (data.settings) {
        updateSettingsDisplay(data.settings);
      }
    }
    updateStreamOverlay(stream);
    renderTransfers(data.transfers);
    renderCaptures(data.captures);

    if (connected && !state.presetsLoaded) {
      refreshPresets();
    }
  }

  async function refreshStatus(options = {}) {
    const force = Boolean(options && options.force);
    if (state.pollInFlight && !force) return;
    state.pollInFlight = true;
    const mySeq = ++state.pollSeq;
    const requestEpoch = state.stateEpoch;
    try {
      const data = await apiJson("/api/status");
      if (requestEpoch !== state.stateEpoch) return;
      applyStatusPayload(data);
    } catch (err) {
      if (requestEpoch !== state.stateEpoch) return;
      if (connBadge && connText) {
        connBadge.className = "badge badge--warn";
        connText.textContent = "SERVER ERR";
      }
    } finally {
      if (state.pollSeq === mySeq) {
        state.pollInFlight = false;
      }
    }
  }

  async function refreshPresets() {
    try {
      const data = await apiJson("/api/presets");
      renderPresets(data.groups);
      state.presetsLoaded = true;
    } catch (_) {
      // Keep existing presets UI if camera is momentarily unreachable
    }
  }

  async function toggleRecord() {
    if (state.isRecording) {
      const res = await apiJson("/api/shutter/stop", "POST", { auto_download: true });
      if (res.capture && res.capture.id) {
        state.seenCaptureIds.add(res.capture.id);
      }
      const fname = res.capture && res.capture.filename ? res.capture.filename : "";
      showToast(fname ? `Saved ${fname} to Downloads` : "Recording stopped — saving to Downloads", "ok");
    } else {
      await apiJson("/api/shutter/start", "POST", {});
      showToast("Recording started", "ok");
    }
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function takePhoto() {
    const res = await apiJson("/api/photo", "POST", { auto_switch: true, auto_download: true });
    if (res.capture && res.capture.id) {
      state.seenCaptureIds.add(res.capture.id);
    }
    const fname = res.capture && res.capture.filename ? res.capture.filename : "";
    showToast(fname ? `Saved ${fname} to Downloads` : "Photo captured — saving to Downloads", "ok");
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function grabSnapshot() {
    const res = await apiJson("/api/snapshot", "POST", {});
    if (res.capture && res.capture.id) {
      state.seenCaptureIds.add(res.capture.id);
    }
    const fname = res.capture && res.capture.filename ? res.capture.filename : "snapshot.jpg";
    showToast(`Saved ${fname} to Downloads`, "ok");
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function pullLatest() {
    const res = await apiJson("/api/media/pull", "POST", {});
    if (res.capture && res.capture.id) {
      state.seenCaptureIds.add(res.capture.id);
    }
    const fname = res.capture && res.capture.filename ? res.capture.filename : "media";
    showToast(`Pulled ${fname} to Downloads`, "ok");
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function refreshCaptures() {
    const res = await apiJson("/api/captures");
    if (downloadsBadge && res.downloads_dir) {
      downloadsBadge.textContent = String(res.downloads_dir);
    }
    renderTransfers(res.transfers);
    renderCaptures(res.captures);
  }

  async function loadPreset(presetId, presetName) {
    const numericId = Number(presetId);
    if (!Number.isFinite(numericId)) return;
    await apiJson("/api/preset/load", "POST", { preset_id: numericId });
    highlightActivePreset(numericId);
    showToast(`Preset loaded: ${presetName || numericId}`, "ok");
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function applySetting(setting, value) {
    const numericVal = Number(value);
    if (!Number.isInteger(numericVal)) {
      throw new Error("Setting value must be an integer");
    }
    const res = await apiJson("/api/setting", "POST", { setting, value: numericVal });
    if (!IS_EMBED && res && res.capabilities) {
      updateCapabilitiesUI(res.capabilities);
    }
    showToast(`Setting ${setting} updated to ${numericVal}`, "ok");
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  async function togglePreview() {
    if (state.streamRunning) {
      await apiJson("/api/preview/stop", "POST", {});
      state.streamRunning = false;
      state.streamLoadedOnce = false;
      if (state.retryTimer) {
        clearTimeout(state.retryTimer);
        state.retryTimer = null;
      }
      if (liveFeed) {
        liveFeed.removeAttribute("src");
      }
      showToast("Preview stream stopped", "warn");
    } else {
      await apiJson("/api/preview/start", "POST", {});
      state.streamRunning = true;
      reloadStream();
      showToast("Preview stream starting", "ok");
    }
    state.stateEpoch += 1;
    await refreshStatus({ force: true });
  }

  function toggleGrid() {
    if (!gridOverlay || !btnGrid) return;
    const isHidden = gridOverlay.classList.toggle("hidden");
    btnGrid.setAttribute("aria-pressed", String(!isHidden));
  }

  function toggleFullscreen() {
    if (!viewfinderFrame) return;
    if (!document.fullscreenElement) {
      if (viewfinderFrame.requestFullscreen) {
        viewfinderFrame.requestFullscreen().catch(() => {});
      }
    } else if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    }
  }

  function populateIntegrateSnippets() {
    const origin = window.location.origin;
    const iframeEl = el("snippet-iframe");
    const widgetEl = el("snippet-widget");
    const mjpegEl = el("snippet-mjpeg");
    const apiEl = el("snippet-api");
    if (iframeEl) {
      iframeEl.textContent = `<iframe src="${origin}/embed" width="960" height="540" style="border:0;border-radius:8px;" allow="fullscreen"></iframe>`;
    }
    if (widgetEl) {
      widgetEl.textContent = `<script src="${origin}/widget.js"><\\/script>\\n<uel-gopro-live server="${origin}" controls="compact" auto-download="true"></uel-gopro-live>`;
    }
    if (mjpegEl) {
      mjpegEl.textContent = `${origin}/stream.mjpeg`;
    }
    if (apiEl) {
      apiEl.textContent = `${origin}/api/status`;
    }
  }

  async function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return;
      } catch (_) {
        // Fall through to textarea fallback when clipboard API is blocked
      }
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.readOnly = true;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    try {
      ta.select();
      ta.setSelectionRange(0, text.length);
      const ok = document.execCommand("copy");
      if (!ok) {
        throw new Error("Copy command rejected");
      }
    } finally {
      document.body.removeChild(ta);
    }
  }

  function isEditableTarget(target) {
    const nodes = [target, document.activeElement];
    for (const node of nodes) {
      if (!node) continue;
      const tag = node.tagName ? node.tagName.toUpperCase() : "";
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return true;
      if (node.isContentEditable) return true;
    }
    return false;
  }

  if (liveFeed) {
    liveFeed.addEventListener("load", () => {
      state.streamLoadedOnce = true;
      if (state.retryTimer) {
        clearTimeout(state.retryTimer);
        state.retryTimer = null;
      }
      if (streamOverlay) {
        streamOverlay.classList.add("hidden");
      }
    });
    liveFeed.addEventListener("error", () => {
      state.streamLoadedOnce = false;
      if (!state.streamRunning) {
        if (state.retryTimer) {
          clearTimeout(state.retryTimer);
          state.retryTimer = null;
        }
        updateStreamOverlay({ running: false, has_frame: false, error: "" });
        return;
      }
      updateStreamOverlay({
        running: true,
        has_frame: false,
        error: "Stream connection interrupted — retrying..."
      });
      scheduleStreamRetry(1500);
    });
  }

  if (btnRetryStream) {
    btnRetryStream.addEventListener("click", () => reloadStream());
  }
  if (btnGrid) {
    btnGrid.addEventListener("click", toggleGrid);
  }
  if (btnFullscreen) {
    btnFullscreen.addEventListener("click", toggleFullscreen);
  }
  if (btnPreviewToggle) {
    btnPreviewToggle.addEventListener("click", () => {
      withButtonBusy(btnPreviewToggle, togglePreview).catch((err) => showToast(err.message, "err"));
    });
  }
  if (btnRecord) {
    btnRecord.addEventListener("click", () => {
      withButtonBusy(btnRecord, toggleRecord).catch((err) => showToast(err.message, "err"));
    });
  }
  if (btnPhoto) {
    btnPhoto.addEventListener("click", () => {
      withButtonBusy(btnPhoto, takePhoto).catch((err) => showToast(err.message, "err"));
    });
  }
  if (btnSnapshot) {
    btnSnapshot.addEventListener("click", () => {
      withButtonBusy(btnSnapshot, grabSnapshot).catch((err) => showToast(err.message, "err"));
    });
  }
  if (btnPull) {
    btnPull.addEventListener("click", () => {
      withButtonBusy(btnPull, pullLatest).catch((err) => showToast(err.message, "err"));
    });
  }
  if (btnRefreshCaptures) {
    btnRefreshCaptures.addEventListener("click", () => {
      withButtonBusy(btnRefreshCaptures, refreshCaptures).catch((err) => showToast(err.message, "err"));
    });
  }
  if (embedPresetSelect) {
    embedPresetSelect.addEventListener("change", () => {
      const val = embedPresetSelect.value;
      if (!val) return;
      const label = embedPresetSelect.options[embedPresetSelect.selectedIndex]?.textContent || val;
      loadPreset(val, label).catch((err) => showToast(err.message, "err"));
    });
  }

  if (customSettingForm) {
    customSettingForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const rawSetting = settingIdInput ? settingIdInput.value.trim() : "";
      const rawValue = settingValInput ? settingValInput.value.trim() : "";
      if (!rawSetting || rawValue === "") {
        showToast("Enter both a setting ID/alias and an integer value", "warn");
        return;
      }
      const btn = el("btn-apply-setting");
      withButtonBusy(btn, () => applySetting(rawSetting, rawValue)).catch((err) => showToast(err.message, "err"));
    });
  }

  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetId = btn.getAttribute("data-copy-target");
      const target = targetId ? el(targetId) : null;
      if (!target) return;
      copyText(target.textContent || "")
        .then(() => showToast("Copied to clipboard", "ok"))
        .catch(() => showToast("Copy failed — select text manually", "warn"));
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    if (isEditableTarget(event.target)) return;
    const key = (event.key || "").toLowerCase();
    if (key === "r" && btnRecord) {
      event.preventDefault();
      withButtonBusy(btnRecord, toggleRecord).catch((err) => showToast(err.message, "err"));
    } else if (key === "p" && btnPhoto) {
      event.preventDefault();
      withButtonBusy(btnPhoto, takePhoto).catch((err) => showToast(err.message, "err"));
    } else if (key === "s" && btnSnapshot) {
      event.preventDefault();
      withButtonBusy(btnSnapshot, grabSnapshot).catch((err) => showToast(err.message, "err"));
    } else if (key === "g" && btnGrid) {
      event.preventDefault();
      toggleGrid();
    }
  });

  setInterval(() => {
    if (state.isRecording && recTimerEl && state.lastStatusAt > 0) {
      const extra = (Date.now() - state.lastStatusAt) / 1000;
      recTimerEl.textContent = formatDuration(state.recordingElapsedSec + extra);
    }
  }, 1000);

  if (!IS_EMBED) {
    populateIntegrateSnippets();
    const initEpoch = state.stateEpoch;
    apiJson("/api/capabilities").then((res) => {
      if (initEpoch !== state.stateEpoch) return;
      if (res && res.settings) updateCapabilitiesUI(res);
    }).catch(() => {
      apiJson("/api/settings").then((res) => {
        if (initEpoch !== state.stateEpoch) return;
        if (res && res.capabilities) {
          updateCapabilitiesUI(res.capabilities);
        } else if (res && res.settings) {
          updateSettingsDisplay(res.settings);
        }
      }).catch(() => {});
    });
  }

  refreshStatus();
  refreshPresets();
  setInterval(refreshStatus, 1200);
})();
"""

_WIDGET_JS = """\
(() => {
  "use strict";

  const SCRIPT_ORIGIN = (() => {
    try {
      const src = document.currentScript && document.currentScript.src;
      if (src) {
        return new URL(src, window.location.href).origin;
      }
    } catch (_) {
      // Fallback handled below
    }
    return window.location.origin;
  })();

  const WIDGET_CSS = `
    :host {
      display: block;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
      color: #f3f4f6;
      background: #0c0d10;
      border: 1px solid #262a33;
      border-radius: 10px;
      overflow: hidden;
      box-sizing: border-box;
    }
    *, *::before, *::after { box-sizing: border-box; }
    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-variant-numeric: tabular-nums;
    }
    .shell {
      display: flex;
      flex-direction: column;
      background: #0c0d10;
      position: relative;
    }
    .hud {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      padding: 8px 10px;
      background: #15171c;
      border-bottom: 1px solid #262a33;
    }
    .hud-group {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 7px;
      border-radius: 4px;
      border: 1px solid #262a33;
      background: #1c1f26;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-variant-numeric: tabular-nums;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
    }
    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #6b7280;
    }
    .badge--ok {
      border-color: rgba(34, 197, 94, 0.35);
      background: rgba(34, 197, 94, 0.14);
      color: #22c55e;
    }
    .badge--ok .dot { background: #22c55e; }
    .badge--rec {
      border-color: rgba(239, 68, 68, 0.55);
      background: rgba(239, 68, 68, 0.16);
      color: #fecaca;
    }
    .badge--rec .dot { background: #ef4444; }
    .badge--warn {
      border-color: rgba(245, 158, 11, 0.45);
      background: rgba(245, 158, 11, 0.16);
      color: #f59e0b;
    }
    .badge--warn .dot { background: #f59e0b; }
    .badge--err {
      border-color: rgba(239, 68, 68, 0.45);
      background: rgba(239, 68, 68, 0.14);
      color: #fca5a5;
    }
    .badge--err .dot { background: #ef4444; }
    .stage {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #060709;
      display: flex;
      align-items: center;
      justify-content: center;
      overflow: hidden;
    }
    .live-feed {
      width: 100%;
      height: 100%;
      object-fit: contain;
      display: block;
    }
    .overlay {
      position: absolute;
      inset: 0;
      background: rgba(12, 13, 16, 0.82);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 6px;
      padding: 16px;
      text-align: center;
      font-size: 12px;
      color: #9ca3af;
    }
    .overlay-title {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-weight: 700;
      color: #f59e0b;
      text-transform: uppercase;
    }
    .hidden { display: none !important; }
    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      padding: 9px 10px;
      background: #15171c;
      border-top: 1px solid #262a33;
    }
    button, select, input {
      font: inherit;
      color: #f3f4f6;
      background: #1c1f26;
      border: 1px solid #262a33;
      border-radius: 6px;
      padding: 6px 10px;
      font-size: 12px;
    }
    button {
      cursor: pointer;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    button:hover:not(:disabled) {
      background: #232730;
      border-color: #343a46;
    }
    button:disabled { opacity: 0.55; cursor: not-allowed; }
    button:focus-visible, select:focus-visible, input:focus-visible {
      outline: 2px solid #60a5fa;
      outline-offset: 2px;
    }
    .btn-rec {
      border-color: rgba(239, 68, 68, 0.5);
      background: rgba(239, 68, 68, 0.14);
      color: #fecaca;
    }
    .btn-rec.is-recording {
      background: #ef4444;
      border-color: #ef4444;
      color: #ffffff;
    }
    .rec-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ef4444;
    }
    .btn-rec.is-recording .rec-dot {
      border-radius: 2px;
      background: #ffffff;
    }
    .preset-select {
      min-width: 130px;
      flex: 1 1 130px;
      max-width: 220px;
    }
    .full-panel {
      padding: 10px;
      background: #111318;
      border-top: 1px solid #262a33;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .full-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }
    .captures {
      display: flex;
      flex-direction: column;
      gap: 4px;
      max-height: 140px;
      overflow-y: auto;
    }
    .capture-row {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 5px 8px;
      border-radius: 5px;
      background: #15171c;
      border: 1px solid #262a33;
      font-size: 11px;
    }
    .toast {
      position: absolute;
      right: 10px;
      bottom: 54px;
      z-index: 20;
      max-width: calc(100% - 20px);
      padding: 7px 10px;
      border-radius: 6px;
      border: 1px solid #343a46;
      background: #15171c;
      color: #f3f4f6;
      font-size: 11px;
      opacity: 0;
      pointer-events: none;
      transition: opacity 140ms ease;
    }
    .toast.is-visible { opacity: 1; }
    .toast--ok { border-color: rgba(34, 197, 94, 0.55); }
    .toast--err { border-color: rgba(239, 68, 68, 0.65); }
  `;

  function trimTrailingSlashes(url) {
    return String(url || "").trim().replace(/\\/+$/, "");
  }

  function formatDuration(sec) {
    const val = Math.max(0, Math.floor(Number(sec) || 0));
    const m = String(Math.floor(val / 60)).padStart(2, "0");
    const s = String(val % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  function formatBytes(bytes) {
    const val = Number(bytes);
    if (!Number.isFinite(val) || val < 0) return "--";
    if (val < 1024) return `${val} B`;
    if (val < 1024 * 1024) return `${(val / 1024).toFixed(1)} KB`;
    return `${(val / (1024 * 1024)).toFixed(1)} MB`;
  }

  class UelGoproLiveElement extends HTMLElement {
    static get observedAttributes() {
      return ["server", "controls", "auto-download"];
    }

    constructor() {
      super();
      this._shadow = this.attachShadow({ mode: "open" });
      this._rendered = false;
      this._pollTimer = null;
      this._retryTimer = null;
      this._toastTimer = null;
      this._abortController = null;
      this._lifecycleAbort = null;
      this._pollInFlight = false;
      this._pollSeq = 0;
      this._stateEpoch = 0;
      this._isRecording = false;
      this._streamRunning = true;
      this._streamLoadedOnce = false;
      this._presetsLoaded = false;
      this._lastStatus = null;
      this._lastPresetSignature = "";
      this._seenCaptureIds = new Set();
      this._initializedCaptures = false;
      this._els = {};
    }

    get serverUrl() {
      const attr = this.getAttribute("server");
      const base = attr && attr.trim() ? attr : SCRIPT_ORIGIN || window.location.origin;
      return trimTrailingSlashes(base);
    }

    get controlsMode() {
      return this.getAttribute("controls") === "full" ? "full" : "compact";
    }

    get autoDownload() {
      return this.getAttribute("auto-download") !== "false";
    }

    connectedCallback() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
      if (this._lifecycleAbort) {
        this._lifecycleAbort.abort();
      }
      this._lifecycleAbort = new AbortController();
      if (!this._rendered) {
        this._renderSkeleton();
        this._rendered = true;
      }
      this._syncControlsMode();
      this._setStreamSource();
      this._refreshStatus({ force: true });
      this._refreshPresets();
      this._pollTimer = setInterval(() => this._refreshStatus(), 1200);
    }

    disconnectedCallback() {
      if (this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
      if (this._retryTimer) {
        clearTimeout(this._retryTimer);
        this._retryTimer = null;
      }
      if (this._toastTimer) {
        clearTimeout(this._toastTimer);
        this._toastTimer = null;
      }
      if (this._abortController) {
        this._abortController.abort();
        this._abortController = null;
      }
      if (this._lifecycleAbort) {
        this._lifecycleAbort.abort();
        this._lifecycleAbort = null;
      }
      if (this._els.feed) {
        this._els.feed.removeAttribute("src");
      }
    }

    attributeChangedCallback(name, oldValue, newValue) {
      if (oldValue === newValue || !this._rendered) return;
      if (name === "controls") {
        this._syncControlsMode();
      } else if (name === "server" && this.isConnected) {
        if (this._abortController) {
          this._abortController.abort();
          this._abortController = null;
        }
        if (this._lifecycleAbort) {
          this._lifecycleAbort.abort();
        }
        this._lifecycleAbort = new AbortController();
        if (this._retryTimer) {
          clearTimeout(this._retryTimer);
          this._retryTimer = null;
        }
        this._stateEpoch += 1;
        this._pollInFlight = false;
        this._streamLoadedOnce = false;
        this._presetsLoaded = false;
        this._lastStatus = null;
        this._lastPresetSignature = "";
        this._seenCaptureIds.clear();
        this._initializedCaptures = false;
        this._setStreamSource(true);
        this._refreshPresets();
        this._refreshStatus({ force: true });
      }
    }

    _emit(eventName, detail) {
      this.dispatchEvent(
        new CustomEvent(eventName, {
          detail,
          bubbles: true,
          composed: true
        })
      );
    }

    _showToast(message, tone = "ok") {
      const toast = this._els.toast;
      if (!toast) return;
      toast.textContent = String(message || "");
      toast.className = `toast is-visible toast--${tone}`;
      if (this._toastTimer) clearTimeout(this._toastTimer);
      this._toastTimer = setTimeout(() => {
        toast.classList.remove("is-visible");
      }, 3200);
    }

    _renderSkeleton() {
      const style = document.createElement("style");
      style.textContent = WIDGET_CSS;

      const shell = document.createElement("div");
      shell.className = "shell";

      // HUD
      const hud = document.createElement("div");
      hud.className = "hud";
      const hudLeft = document.createElement("div");
      hudLeft.className = "hud-group";

      const tallyBadge = document.createElement("span");
      tallyBadge.className = "badge";
      const tallyDot = document.createElement("span");
      tallyDot.className = "dot";
      const tallyText = document.createElement("span");
      tallyText.textContent = "STANDBY";
      const recTimer = document.createElement("span");
      recTimer.className = "mono";
      recTimer.textContent = "00:00";
      tallyBadge.append(tallyDot, tallyText, recTimer);

      const modeBadge = document.createElement("span");
      modeBadge.className = "badge";
      modeBadge.textContent = "--";
      hudLeft.append(tallyBadge, modeBadge);

      const hudRight = document.createElement("div");
      hudRight.className = "hud-group";
      const batBadge = document.createElement("span");
      batBadge.className = "badge";
      batBadge.textContent = "BAT --";
      const sdBadge = document.createElement("span");
      sdBadge.className = "badge";
      sdBadge.textContent = "SD --";
      hudRight.append(batBadge, sdBadge);
      hud.append(hudLeft, hudRight);

      // Stage
      const stage = document.createElement("div");
      stage.className = "stage";
      const feed = document.createElement("img");
      feed.className = "live-feed";
      feed.alt = "GoPro Live Stream";

      const overlay = document.createElement("div");
      overlay.className = "overlay";
      const overlayTitle = document.createElement("div");
      overlayTitle.className = "overlay-title";
      overlayTitle.textContent = "Connecting Viewfinder";
      const overlayMsg = document.createElement("div");
      overlayMsg.textContent = "Waiting for live MJPEG stream...";
      overlay.append(overlayTitle, overlayMsg);
      stage.append(feed, overlay);

      // Controls bar
      const controls = document.createElement("div");
      controls.className = "controls";

      const btnRec = document.createElement("button");
      btnRec.type = "button";
      btnRec.className = "btn-rec";
      btnRec.setAttribute("aria-label", "Start or stop recording");
      const recDot = document.createElement("span");
      recDot.className = "rec-dot";
      const recLabel = document.createElement("span");
      recLabel.textContent = "Record";
      btnRec.append(recDot, recLabel);

      const btnPhoto = document.createElement("button");
      btnPhoto.type = "button";
      btnPhoto.textContent = "Photo";
      btnPhoto.setAttribute("aria-label", "Take photo");

      const btnSnap = document.createElement("button");
      btnSnap.type = "button";
      btnSnap.textContent = "Snapshot";
      btnSnap.setAttribute("aria-label", "Grab frame snapshot");

      const presetSelect = document.createElement("select");
      presetSelect.className = "preset-select";
      presetSelect.setAttribute("aria-label", "Select camera preset");
      const defOpt = document.createElement("option");
      defOpt.value = "";
      defOpt.textContent = "Presets...";
      presetSelect.appendChild(defOpt);

      controls.append(btnRec, btnPhoto, btnSnap, presetSelect);

      // Full controls panel
      const fullPanel = document.createElement("div");
      fullPanel.className = "full-panel hidden";

      const fullRow = document.createElement("div");
      fullRow.className = "full-row";
      const btnPull = document.createElement("button");
      btnPull.type = "button";
      btnPull.textContent = "Pull Latest";
      const btnPreview = document.createElement("button");
      btnPreview.type = "button";
      btnPreview.textContent = "Stop Preview";

      const settingInput = document.createElement("input");
      settingInput.type = "text";
      settingInput.placeholder = "Setting ID";
      settingInput.setAttribute("aria-label", "Setting ID or alias");
      settingInput.style.width = "95px";
      const valueInput = document.createElement("input");
      valueInput.type = "number";
      valueInput.placeholder = "Value";
      valueInput.setAttribute("aria-label", "Setting numeric value");
      valueInput.style.width = "80px";
      const btnApplySetting = document.createElement("button");
      btnApplySetting.type = "button";
      btnApplySetting.textContent = "Set";
      fullRow.append(btnPull, btnPreview, settingInput, valueInput, btnApplySetting);

      const capturesBox = document.createElement("div");
      capturesBox.className = "captures";
      fullPanel.append(fullRow, capturesBox);

      const toast = document.createElement("div");
      toast.className = "toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");

      shell.append(hud, stage, controls, fullPanel, toast);
      this._shadow.append(style, shell);

      this._els = {
        tallyBadge,
        tallyText,
        recTimer,
        modeBadge,
        batBadge,
        sdBadge,
        feed,
        overlay,
        overlayTitle,
        overlayMsg,
        btnRec,
        recLabel,
        btnPhoto,
        btnSnap,
        presetSelect,
        fullPanel,
        btnPull,
        btnPreview,
        settingInput,
        valueInput,
        btnApplySetting,
        capturesBox,
        toast
      };

      feed.addEventListener("load", () => {
        this._streamLoadedOnce = true;
        if (this._retryTimer) {
          clearTimeout(this._retryTimer);
          this._retryTimer = null;
        }
        overlay.classList.add("hidden");
      });

      feed.addEventListener("error", () => {
        this._streamLoadedOnce = false;
        if (!this._streamRunning) {
          if (this._retryTimer) {
            clearTimeout(this._retryTimer);
            this._retryTimer = null;
          }
          overlayTitle.textContent = "Preview Stopped";
          overlayMsg.textContent = "Live preview stream is currently stopped.";
          overlay.classList.remove("hidden");
          return;
        }
        overlayTitle.textContent = "Stream Reconnecting";
        overlayMsg.textContent = "Connection interrupted — retrying...";
        overlay.classList.remove("hidden");
        if (!this._retryTimer && this.isConnected) {
          this._retryTimer = setTimeout(() => {
            this._retryTimer = null;
            this._setStreamSource(true);
          }, 1500);
        }
      });

      btnRec.addEventListener("click", () => this._runAction(btnRec, () => this._toggleRecord()));
      btnPhoto.addEventListener("click", () => this._runAction(btnPhoto, () => this._takePhoto()));
      btnSnap.addEventListener("click", () => this._runAction(btnSnap, () => this._grabSnapshot()));
      btnPull.addEventListener("click", () => this._runAction(btnPull, () => this._pullLatest()));
      btnPreview.addEventListener("click", () => this._runAction(btnPreview, () => this._togglePreview()));
      btnApplySetting.addEventListener("click", () =>
        this._runAction(btnApplySetting, () => this._applyCustomSetting())
      );

      presetSelect.addEventListener("change", () => {
        const val = presetSelect.value;
        if (!val) return;
        this._loadPreset(val).catch((err) => this._handleError(err, "preset"));
      });
    }

    _syncControlsMode() {
      if (this._els.fullPanel) {
        this._els.fullPanel.classList.toggle("hidden", this.controlsMode !== "full");
      }
    }

    _setStreamSource(bustCache = false) {
      if (!this._els.feed) return;
      const url = `${this.serverUrl}/stream.mjpeg`;
      this._els.feed.src = bustCache ? `${url}?t=${Date.now()}` : url;
    }

    async _apiJson(path, method = "GET", body = undefined) {
      if (this._abortController) {
        this._abortController.abort();
      }
      this._abortController = new AbortController();
      const opts = {
        method,
        headers: { Accept: "application/json" },
        signal: this._abortController.signal
      };
      if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const resp = await fetch(`${this.serverUrl}${path}`, opts);
      let data = {};
      try {
        data = await resp.json();
      } catch (_) {
        data = {};
      }
      if (!resp.ok || data.ok === false) {
        throw new Error(data.error || data.detail || `Request failed (${resp.status})`);
      }
      return data;
    }

    async _fetchWithLifecycle(path, method = "GET", body = undefined) {
      if (!this._lifecycleAbort) {
        this._lifecycleAbort = new AbortController();
      }
      const opts = {
        method,
        headers: { Accept: "application/json" },
        signal: this._lifecycleAbort.signal
      };
      if (body !== undefined) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
      const resp = await fetch(`${this.serverUrl}${path}`, opts);
      let data = {};
      try {
        data = await resp.json();
      } catch (_) {
        data = {};
      }
      if (!resp.ok || data.ok === false) {
        throw new Error(data.error || data.detail || `Request failed (${resp.status})`);
      }
      return data;
    }

    async _runAction(button, fn) {
      if (button.disabled) return;
      button.disabled = true;
      try {
        await fn();
      } catch (err) {
        if (!err || err.name !== "AbortError") {
          this._handleError(err, "command");
        }
      } finally {
        button.disabled = false;
      }
    }

    _handleError(err, source) {
      const message = err && err.message ? String(err.message) : String(err || "Unknown error");
      this._showToast(message, "err");
      this._emit("uel-error", { message, source });
    }

    async _refreshStatus(options = {}) {
      const force = Boolean(options && options.force);
      if ((this._pollInFlight && !force) || !this.isConnected) return;
      this._pollInFlight = true;
      const mySeq = ++this._pollSeq;
      const requestEpoch = this._stateEpoch;
      try {
        const data = await this._apiJson("/api/status");
        if (requestEpoch !== this._stateEpoch || !this.isConnected) return;
        this._applyStatus(data);
        this._emit("uel-status", data);
      } catch (err) {
        if (requestEpoch !== this._stateEpoch || !this.isConnected) return;
        if (!err || err.name !== "AbortError") {
          this._emit("uel-error", {
            message: err && err.message ? err.message : "Status poll failed",
            source: "status"
          });
        }
      } finally {
        if (this._pollSeq === mySeq) {
          this._pollInFlight = false;
        }
      }
    }

    async _refreshPresets() {
      const requestEpoch = this._stateEpoch;
      try {
        const data = await this._fetchWithLifecycle("/api/presets");
        if (requestEpoch !== this._stateEpoch || !this.isConnected) return;
        this._renderPresets(data.groups);
        this._presetsLoaded = true;
      } catch (_) {
        // Ignore transient preset fetch error while disconnected
      }
    }

    _applyStatus(data) {
      this._lastStatus = data;
      const st = data.status || {};
      const stream = data.stream || {};
      const recording = Boolean(st.is_recording || st.encoding_active);
      this._isRecording = recording;
      this._streamRunning = Boolean(stream.running);

      if (!this._streamRunning && this._retryTimer) {
        clearTimeout(this._retryTimer);
        this._retryTimer = null;
      }

      this._els.tallyBadge.className = "badge";
      if (recording) {
        this._els.tallyBadge.classList.add("badge--rec");
        this._els.tallyText.textContent = "REC";
      } else if (this._streamRunning && (stream.has_frame || this._streamLoadedOnce)) {
        this._els.tallyBadge.classList.add("badge--ok");
        this._els.tallyText.textContent = "LIVE";
      } else {
        this._els.tallyText.textContent = "STANDBY";
      }

      this._els.recTimer.textContent = recording ? formatDuration(data.recording_elapsed_sec) : "00:00";
      this._els.btnRec.classList.toggle("is-recording", recording);
      this._els.recLabel.textContent = recording ? "Stop" : "Record";
      this._els.modeBadge.textContent = st.current_mode || "--";
      this._els.batBadge.textContent = st.battery_percent != null ? `BAT ${st.battery_percent}%` : "BAT --";
      this._els.sdBadge.textContent = st.sd_remaining_mb != null
        ? `SD ${(Number(st.sd_remaining_mb) / 1024).toFixed(1)}G`
        : "SD --";
      this._els.btnPreview.textContent = this._streamRunning ? "Stop Preview" : "Start Preview";

      const showOverlay = !this._streamRunning || (!stream.has_frame && !this._streamLoadedOnce);
      this._els.overlay.classList.toggle("hidden", !showOverlay);
      if (showOverlay) {
        this._els.overlayTitle.textContent = this._streamRunning ? "Connecting Viewfinder" : "Preview Stopped";
        this._els.overlayMsg.textContent = stream.error || (this._streamRunning ? "Waiting for frames..." : "Live preview stream is currently stopped.");
      }

      this._syncSelectedPreset(st.current_preset);

      const captures = Array.isArray(data.captures) ? data.captures : [];
      if (!this._initializedCaptures) {
        for (const c of captures) {
          if (c && c.id) this._seenCaptureIds.add(c.id);
        }
        this._initializedCaptures = true;
      } else {
        for (const c of captures) {
          if (c && c.id && !this._seenCaptureIds.has(c.id)) {
            this._seenCaptureIds.add(c.id);
            this._showToast(c.filename ? `Saved ${c.filename}` : "Capture saved", "ok");
            this._emit("uel-capture", c);
          }
        }
      }
      this._renderCaptures(captures);

      if (st.connected && !this._presetsLoaded) {
        this._refreshPresets();
      }
    }

    _syncSelectedPreset(currentPreset) {
      const select = this._els.presetSelect;
      if (!select) return;
      if (currentPreset == null || currentPreset === "") {
        select.value = "";
        return;
      }
      const pid = String(currentPreset);
      if ([...select.options].some((opt) => opt.value === pid)) {
        select.value = pid;
      }
    }

    _renderPresets(groups) {
      const groupList = Array.isArray(groups) ? groups : [];
      const sig = JSON.stringify(groupList);
      if (sig === this._lastPresetSignature) {
        this._syncSelectedPreset(this._lastStatus && this._lastStatus.status ? this._lastStatus.status.current_preset : null);
        return;
      }
      this._lastPresetSignature = sig;

      const select = this._els.presetSelect;
      select.textContent = "";
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Presets...";
      select.appendChild(placeholder);

      for (const group of groupList) {
        const og = document.createElement("optgroup");
        og.label = group.name || `Group ${group.id ?? ""}`;
        for (const p of Array.isArray(group.presets) ? group.presets : []) {
          const opt = document.createElement("option");
          opt.value = String(p.id);
          opt.textContent = p.name || `Preset ${p.id}`;
          og.appendChild(opt);
        }
        select.appendChild(og);
      }

      this._syncSelectedPreset(this._lastStatus && this._lastStatus.status ? this._lastStatus.status.current_preset : null);
    }

    _renderCaptures(captures) {
      const box = this._els.capturesBox;
      box.textContent = "";
      for (const cap of captures.slice(0, 6)) {
        const row = document.createElement("div");
        row.className = "capture-row mono";
        const name = document.createElement("span");
        name.textContent = cap.filename || "capture";
        const meta = document.createElement("span");
        meta.textContent = `${String(cap.source || "").toUpperCase()} · ${formatBytes(cap.size_bytes)}`;
        row.append(name, meta);
        box.appendChild(row);
      }
    }

    async _toggleRecord() {
      if (this._isRecording) {
        const res = await this._fetchWithLifecycle("/api/shutter/stop", "POST", {
          auto_download: this.autoDownload
        });
        if (res.capture) {
          if (res.capture.id) this._seenCaptureIds.add(res.capture.id);
          this._emit("uel-capture", res.capture);
        }
        const fname = res.capture && res.capture.filename ? res.capture.filename : "";
        this._showToast(fname ? `Saved ${fname}` : "Recording stopped", "ok");
      } else {
        await this._fetchWithLifecycle("/api/shutter/start", "POST", {});
        this._showToast("Recording started", "ok");
      }
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _takePhoto() {
      const res = await this._fetchWithLifecycle("/api/photo", "POST", {
        auto_switch: true,
        auto_download: this.autoDownload
      });
      if (res.capture) {
        if (res.capture.id) this._seenCaptureIds.add(res.capture.id);
        this._emit("uel-capture", res.capture);
      }
      const fname = res.capture && res.capture.filename ? res.capture.filename : "";
      this._showToast(fname ? `Saved ${fname}` : "Photo captured", "ok");
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _grabSnapshot() {
      const res = await this._fetchWithLifecycle("/api/snapshot", "POST", {});
      if (res.capture) {
        if (res.capture.id) this._seenCaptureIds.add(res.capture.id);
        this._emit("uel-capture", res.capture);
      }
      const fname = res.capture && res.capture.filename ? res.capture.filename : "";
      this._showToast(fname ? `Saved ${fname}` : "Snapshot saved", "ok");
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _pullLatest() {
      const res = await this._fetchWithLifecycle("/api/media/pull", "POST", {});
      if (res.capture) {
        if (res.capture.id) this._seenCaptureIds.add(res.capture.id);
        this._emit("uel-capture", res.capture);
      }
      const fname = res.capture && res.capture.filename ? res.capture.filename : "";
      this._showToast(fname ? `Pulled ${fname}` : "Pulled latest capture", "ok");
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _togglePreview() {
      if (this._streamRunning) {
        await this._fetchWithLifecycle("/api/preview/stop", "POST", {});
        this._streamRunning = false;
        this._streamLoadedOnce = false;
        if (this._retryTimer) {
          clearTimeout(this._retryTimer);
          this._retryTimer = null;
        }
        if (this._els.feed) {
          this._els.feed.removeAttribute("src");
        }
      } else {
        await this._fetchWithLifecycle("/api/preview/start", "POST", {});
        this._streamRunning = true;
        this._setStreamSource(true);
      }
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _loadPreset(presetId) {
      const numId = Number(presetId);
      if (!Number.isFinite(numId)) return;
      await this._fetchWithLifecycle("/api/preset/load", "POST", { preset_id: numId });
      this._showToast(`Preset ${numId} loaded`, "ok");
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }

    async _applyCustomSetting() {
      const setting = this._els.settingInput.value.trim();
      const val = Number(this._els.valueInput.value.trim());
      if (!setting || !Number.isInteger(val)) {
        throw new Error("Provide a setting ID/alias and integer value");
      }
      await this._fetchWithLifecycle("/api/setting", "POST", { setting, value: val });
      this._showToast(`Setting ${setting} = ${val}`, "ok");
      this._stateEpoch += 1;
      await this._refreshStatus({ force: true });
    }
  }

  if (!customElements.get("uel-gopro-live")) {
    customElements.define("uel-gopro-live", UelGoproLiveElement);
  }
})();
"""


def render_live_page(embed: bool = False) -> str:
    """Render the self-contained HTML5 live viewfinder page.

    When ``embed`` is True, returns a full-bleed 100vw x 100vh monitor with
    translucent HUD and floating control dock, omitting outer chrome and drawers.
    """
    body_class = "embed" if embed else "full"
    embed_attr = "true" if embed else "false"
    mode_css = _EMBED_CSS if embed else _FULL_CSS
    body_html = _EMBED_BODY if embed else _FULL_BODY

    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>UEL GoPro Live Monitor</title>\n"
        "<style>\n"
        f"{_SHARED_CSS}\n"
        f"{mode_css}"
        "</style>\n"
        "</head>\n"
        f'<body class="{body_class}" data-embed="{embed_attr}">\n'
        f"{body_html}"
        "<script>\n"
        f"{_PAGE_SCRIPT}"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


def render_widget_js() -> str:
    """Render the self-contained ``<uel-gopro-live>`` Web Component script."""
    return _WIDGET_JS
