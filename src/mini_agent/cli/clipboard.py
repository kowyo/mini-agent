"""Clipboard image handling for mini-agent."""

import base64
import io
from collections.abc import Iterable, Sequence
from typing import cast

from anthropic.types import ImageBlockParam, TextBlockParam
from PIL import Image, ImageGrab


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


def has_clipboard_image() -> bool:
    """Check if clipboard contains an image.

    Returns:
        True if clipboard contains an image, False otherwise.
    """
    return get_clipboard_image() is not None


def attach_clipboard_image(
    content: str | Sequence[ImageBlockParam | TextBlockParam],
) -> list[ImageBlockParam | TextBlockParam] | str:
    """Attach clipboard image to message content.

    If clipboard contains an image, converts it to Claude API format
    and prepends it to text content. If no image is found, returns
    original content unchanged.

    Args:
        content: Original message content (string or sequence of blocks)

    Returns:
        List of content blocks including image if available
    """
    image = get_clipboard_image()
    if image is None:
        if isinstance(content, str):
            return content
        return list(content)

    # Create image content block
    image_block = create_image_content(image)

    # Build content list with image and text
    result: list[ImageBlockParam | TextBlockParam] = [image_block]

    # Add existing content
    if isinstance(content, str):
        if content.strip():
            text_block: TextBlockParam = {"type": "text", "text": content}
            result.append(text_block)
    else:
        result.extend(content)

    return result


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

    if not has_image:
        return "\n".join(
            cast(str, b.get("text", "")) for b in blocks if b.get("type") == "text"
        )

    parts = ["[Image attached]"]
    for b in blocks:
        if b.get("type") == "text":
            text = cast(str, b.get("text", "")).strip()
            if text:
                parts.append(text)

    return "\n".join(parts)
