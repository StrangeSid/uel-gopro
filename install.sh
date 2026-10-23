#!/usr/bin/env bash
# ==============================================================================
# UEL-GoPro Installer
# Unofficial Extended Life GoPro Toolchain
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/StrangeSid/uel-gopro/main/install.sh | bash
# ==============================================================================

set -euo pipefail

REPO="StrangeSid/uel-gopro"
BIN_NAME="uel-gopro"
INSTALL_DIR="${BINDIR:-$HOME/.local/bin}"
SHARE_DIR="$HOME/.local/share/uel-gopro"

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}"
cat << 'EOF'
  _   _ _____ _        ____        ____
 | | | | ____| |      / ___| ___  |  _ \ _ __ ___
 | | | |  _| | |     | |  _ / _ \ | |_) | '__/ _ \
 | |_| | |___| |___  | |_| | (_) ||  __/| | | (_) |
  \___/|_____|_____|  \____|\___/ |_|   |_|  \___/
EOF
echo -e " Unofficial Extended Life GoPro Toolchain Installer${NC}"
echo -e " https://github.com/${REPO}\n"

mkdir -p "$INSTALL_DIR"

# ------------------------------------------------------------------------------
# 1. Check OS and Architecture
# ------------------------------------------------------------------------------
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin) OS_NAME="macOS" ;;
    Linux)  OS_NAME="Linux" ;;
    *)
        echo -e "${RED}Error: Unsupported operating system: $OS${NC}" >&2
        exit 1
        ;;
esac

echo -e "${BLUE}==>${NC} Detected platform: ${BOLD}${OS_NAME} (${ARCH})${NC}"

# ------------------------------------------------------------------------------
# 2. Check for FFmpeg (Recommended for chapter stitching & telemetry)
# ------------------------------------------------------------------------------
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo -e "${YELLOW}Warning: 'ffmpeg' not found in PATH.${NC}"
    echo -e "         FFmpeg is recommended for lossless chapter stitching and telemetry extraction."
    if [ "$OS" = "Darwin" ]; then
        echo -e "         Install via Homebrew: ${CYAN}brew install ffmpeg${NC}\n"
    else
        echo -e "         Install via package manager: ${CYAN}sudo apt install ffmpeg${NC}\n"
    fi
fi

# ------------------------------------------------------------------------------
# 3. Installation Strategy
# ------------------------------------------------------------------------------
INSTALLED=0

# Method A: Use 'uv' if available (fastest and cleanest tool manager)
if command -v uv >/dev/null 2>&1; then
    echo -e "${BLUE}==>${NC} Found ${BOLD}uv${NC}. Installing via uv tool..."
    uv tool install --force uel-gopro
    if [ -f "$HOME/.local/bin/$BIN_NAME" ] && [ "$INSTALL_DIR" != "$HOME/.local/bin" ]; then
        ln -sf "$HOME/.local/bin/$BIN_NAME" "$INSTALL_DIR/$BIN_NAME"
    fi
    INSTALLED=1
fi

# Method B: Isolated Python Virtual Environment in ~/.local/share/uel-gopro
if [ "$INSTALLED" -eq 0 ]; then
    PYTHON_CMD=""
    for cmd in python3.13 python3.12 python3.11 python3 python; do
        if command -v "$cmd" >/dev/null 2>&1; then
            # Verify version >= 3.11
            PY_VER=$("$cmd" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
            PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
            if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 11 ]; then
                PYTHON_CMD="$cmd"
                break
            fi
        fi
    done

    if [ -n "$PYTHON_CMD" ]; then
        echo -e "${BLUE}==>${NC} Using ${BOLD}${PYTHON_CMD}${NC} to create isolated environment in ${SHARE_DIR}..."
        mkdir -p "$SHARE_DIR"
        "$PYTHON_CMD" -m venv "$SHARE_DIR/venv"
        "$SHARE_DIR/venv/bin/pip" install --quiet --upgrade pip
        "$SHARE_DIR/venv/bin/pip" install --quiet --upgrade uel-gopro
        ln -sf "$SHARE_DIR/venv/bin/$BIN_NAME" "$INSTALL_DIR/$BIN_NAME"
        INSTALLED=1
    fi
fi

if [ "$INSTALLED" -eq 0 ]; then
    echo -e "${RED}Error: Neither 'uv' nor Python >= 3.11 could be found.${NC}" >&2
    echo -e "Please install Python 3.11+ or uv, then rerun this script." >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# 4. PATH Check & Final Verification
# ------------------------------------------------------------------------------
echo -e "\n${GREEN}${BOLD}✓ uel-gopro successfully installed to:${NC} ${INSTALL_DIR}/${BIN_NAME}"

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo -e "\n${YELLOW}Notice:${NC} '${INSTALL_DIR}' is not in your current PATH."
    echo -e "Add it to your shell configuration to run '${BIN_NAME}' from anywhere:"
    SHELL_NAME=$(basename "${SHELL:-/bin/bash}")
    case "$SHELL_NAME" in
        zsh)  echo -e "  ${CYAN}echo 'export PATH=\"${INSTALL_DIR}:\$PATH\"' >> ~/.zshrc && source ~/.zshrc${NC}" ;;
        bash) echo -e "  ${CYAN}echo 'export PATH=\"${INSTALL_DIR}:\$PATH\"' >> ~/.bashrc && source ~/.bashrc${NC}" ;;
        fish) echo -e "  ${CYAN}fish_add_path ${INSTALL_DIR}${NC}" ;;
        *)    echo -e "  ${CYAN}export PATH=\"${INSTALL_DIR}:\$PATH\"${NC}" ;;
    esac
fi

echo -e "\nRun ${CYAN}${BIN_NAME} --help${NC} to get started!"
