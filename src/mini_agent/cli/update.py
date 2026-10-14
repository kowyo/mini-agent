import json
import subprocess
import sys
import urllib.request

from ..config import DISTRIBUTION_NAME, DISTRIBUTION_VERSION

LATEST_RELEASE_URL = "https://api.github.com/repos/kowyo/mini-agent/releases/latest"
WINDOWS_UPDATE_COMMAND = (
    'powershell -c "irm https://raw.githubusercontent.com/kowyo/mini-agent/main/'
    'scripts/install.ps1 | iex"'
)


def run_update() -> int:
    print("Checking for updates...")
    try:
        with urllib.request.urlopen(LATEST_RELEASE_URL, timeout=10) as resp:
            release = json.load(resp)
    except OSError as e:
        print(f"Failed to check for updates: {e}")
        return 1

    latest = release["tag_name"].removeprefix("v")
    if latest == DISTRIBUTION_VERSION:
        print(f"You're already on the latest version ({latest}).")
        return 0

    if sys.platform == "win32":
        print(f"v{latest} is available. Run this to update:\n{WINDOWS_UPDATE_COMMAND}")
        return 0

    print(f"Updating {DISTRIBUTION_NAME} from v{DISTRIBUTION_VERSION} to v{latest}...")

    wheel = next(
        asset["browser_download_url"]
        for asset in release["assets"]
        if asset["name"].endswith("none-any.whl")
    )
    return subprocess.run(["uv", "tool", "install", "--force", wheel]).returncode
