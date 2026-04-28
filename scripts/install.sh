#!/usr/bin/env bash
set -euo pipefail

REPO="kowyo/mini-agent"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

if command -v mini &>/dev/null; then
  echo "Checking for updates..."
  LATEST_RELEASE=$(curl -fsSL "${API_URL}")
  LATEST_VERSION=$(echo "${LATEST_RELEASE}" | grep '"tag_name":' | sed 's/.*"tag_name": "v\([^"]*\)".*/\1/')

  INSTALLED_VERSION=$(mini --version 2>/dev/null | awk '{print $2}' || true)
  if [ "${INSTALLED_VERSION}" = "${LATEST_VERSION}" ]; then
    CYAN='\033[36m'
    RESET='\033[0m'
    echo -e "You're already on version ${CYAN}${INSTALLED_VERSION}${RESET} of mini-agent (the latest version)."
    exit 0
  fi
  echo "Updating mini-agent from v${INSTALLED_VERSION} to v${LATEST_VERSION}..."
else
  LATEST_RELEASE=$(curl -fsSL "${API_URL}")
fi

if ! command -v uv &>/dev/null; then
  echo "'uv' is required but not installed."
  read -r -p "Would you like to install uv now? [Y/n] " REPLY </dev/tty
  if [[ "${REPLY:-n}" =~ ^[Yy]$ ]]; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # Add uv to PATH for the current script session
    if [ -f "$HOME/.local/bin/uv" ]; then
      export PATH="$HOME/.local/bin:$PATH"
    fi
    echo "uv installed. Continuing with mini-agent installation..."
  else
    echo "Aborting. Install uv manually and re-run this script."
    exit 1
  fi
fi

OS=$(uname -s)
ARCH=$(uname -m)

case "${OS}" in
  Darwin) OS_TAG="macosx" ;;
  Linux)  OS_TAG="linux" ;;
  *) echo "Unsupported OS: ${OS}"; exit 1 ;;
esac

case "${ARCH}" in
  arm64|aarch64|x86_64) ;;
  *) echo "Unsupported architecture: ${ARCH}"; exit 1 ;;
esac

ASSETS=$(echo "${LATEST_RELEASE}" | grep "browser_download_url" | grep "\.whl" | sed 's/.*"browser_download_url": "\(.*\)".*/\1/' || true)

WHEEL=$(echo "${ASSETS}" | grep "${OS_TAG}" | grep "${ARCH}" | head -1 || true)
if [ -z "${WHEEL}" ]; then
  WHEEL=$(echo "${ASSETS}" | grep "none-any" | head -1 || true)
fi

if [ -z "${WHEEL}" ]; then
  echo "No compatible wheel found for ${OS}/${ARCH}."
  exit 1
fi

echo "Installing mini-agent from ${WHEEL}..."
uv tool install --force "${WHEEL}"
echo "Done. Run 'mini' to get started."
