"""Clipboard image handling for mini-agent."""

import base64
import io
from collections.abc import Iterable
from typing import cast

from anthropic.types import ImageBlockParam
from PIL import Image, ImageGrab


def format_image_indicator(index: int) -> str:
    return f"[Image #{index}]"


def get_clipboard_image() -> Image.Image | None:
    """Get image from clipboard using PIL.ImageGrab.grabclipboard().

    Returns:
        PIL.Image.Image if an image is available, None otherwise.
    """
    try:
        clipboard_content = ImageGrab.grabclipboard()
    except Exception:
        return None

    if clipboard_content is None:
        return None

    # On Windows, grabclipboard() can return a list of filenames
    if isinstance(clipboard_content, list):
        return None

    # On macOS and Linux, it returns an Image or None
    if isinstance(clipboard_content, Image.Image):
        return clipboard_content

    return None


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to base64-encoded string.

    Args:
        image: PIL Image object
        format: Image format for encoding (default: PNG)

    Returns:
        Base64-encoded image string
    """
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def create_image_content(image: Image.Image) -> ImageBlockParam:
    """Create Claude API image content block from PIL Image.

    Args:
        image: PIL Image object

    Returns:
        Claude API image content block dictionary
    """
    # Convert to RGB if necessary (for images with alpha channel)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")

    base64_data = image_to_base64(image, "PNG")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64_data,
        },
    }


def format_content_with_image_indicator(content: Iterable[object] | str) -> str:
    """Format content for display with image indicator.

    Args:
        content: Message content (string or iterable of blocks)

    Returns:
        Formatted string with image indicator if present
    """
    if isinstance(content, str):
        return content

    blocks = [cast("dict[str, object]", b) for b in content if isinstance(b, dict)]

    has_image = any(b.get("type") == "image" for b in blocks)
    texts = [
        cast(str, b.get("text", "")).strip()
        for b in blocks
        if b.get("type") == "text" and isinstance(b.get("text", ""), str)
    ]

    if texts:
        return "\n".join(text for text in texts if text)

    if not has_image:
        return ""

    image_count = sum(1 for b in blocks if b.get("type") == "image")
    return "\n".join(
        format_image_indicator(index) for index in range(1, image_count + 1)
    )
