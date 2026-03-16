#!/bin/bash
set -euo pipefail
export USERNAME=$(whoami)
export PROJECT_NAME=$(pwd | xargs basename)
sudo chown -R ${USERNAME}:${USERNAME} /workspaces/${PROJECT_NAME} /home/${USERNAME}
uv sync --all-groups