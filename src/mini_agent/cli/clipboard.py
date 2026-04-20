"""Clipboard image handling for mini-agent."""

from __future__ import annotations

import base64
import io
import subprocess
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image


def get_clipboard_image() -> Image | None:
    """Get image from clipboard if available.

    Supports macOS, Linux (with xclip), and Windows.
    Returns None if no image is available in clipboard.
    """
    try:
        from PIL import ImageGrab

        # Try PIL's grabclipboard first (works on Windows and macOS)
        img = ImageGrab.grabclipboard()
        if img is not None:
            return img

        # Fallback for Linux using xclip
        if sys.platform == "linux":
            return _get_linux_clipboard_image()

        return None
    except ImportError:
        return None
    except Exception:
        return None


def _get_linux_clipboard_image() -> Image | None:
    """Get image from clipboard on Linux using xclip."""
    try:
        from PIL import Image

        # Try to get image data from clipboard
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            return Image.open(io.BytesIO(result.stdout))

        # Try other common formats
        for img_format in ["image/jpeg", "image/bmp", "image/gif"]:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", img_format, "-o"],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return Image.open(io.BytesIO(result.stdout))

        return None
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


def image_to_base64(img: Image) -> tuple[str, str]:
    """Convert PIL Image to base64 encoded string.

    Returns:
        Tuple of (base64_data, media_type)
    """
    # Convert to RGB if necessary (for JPEG compatibility)
    if img.mode in ("RGBA", "P"):
        img_rgb = img.convert("RGB")
        buffer = io.BytesIO()
        img_rgb.save(buffer, format="JPEG")
        media_type = "image/jpeg"
    else:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        media_type = "image/png"

    buffer.seek(0)
    img_bytes = buffer.getvalue()
    base64_data = base64.b64encode(img_bytes).decode("utf-8")

    return base64_data, media_type


def create_image_content_block(img: Image) -> dict:
    """Create an Anthropic image content block from a PIL Image."""
    base64_data, media_type = image_to_base64(img)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64_data,
        },
    }
