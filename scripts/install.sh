#!/usr/bin/env bash
set -euo pipefail

REPO="kowyo/mini-agent"
API_URL="https://api.github.com/repos/${REPO}/releases/latest"

if ! command -v uv &>/dev/null; then
  echo "'uv' is required but not installed."
  read -r -p "Would you like to install uv now? [Y/n] " REPLY </dev/tty
  if [[ "${REPLY:-y}" =~ ^[Yy]$ ]]; then
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
  arm64|aarch64) ARCH_TAG="arm64" ;;
  x86_64)        ARCH_TAG="x86_64" ;;
  *) echo "Unsupported architecture: ${ARCH}"; exit 1 ;;
esac

ASSETS=$(curl -fsSL "${API_URL}" | grep "browser_download_url" | grep "\.whl" | sed 's/.*"browser_download_url": "\(.*\)".*/\1/')

WHEEL=$(echo "${ASSETS}" | grep "${OS_TAG}" | grep "${ARCH_TAG}" | head -1)
if [ -z "${WHEEL}" ]; then
  WHEEL=$(echo "${ASSETS}" | grep "none-any" | head -1)
fi

if [ -z "${WHEEL}" ]; then
  echo "No compatible wheel found for ${OS}/${ARCH}."
  exit 1
fi

echo "Installing mini-agent from ${WHEEL}..."
uv tool install "${WHEEL}"
echo "Done. Run 'mini' to get started."
