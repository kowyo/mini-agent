import base64
import io
import sys
from collections.abc import Iterable
from typing import cast

from anthropic.types import ImageBlockParam
from PIL import Image, ImageGrab


def format_image_indicator(index: int) -> str:
    return f"[Image #{index}]"


def _get_macos_clipboard_file_image() -> Image.Image | None:
    try:
        import AppKit

        pb = AppKit.NSPasteboard.generalPasteboard()  # ty: ignore[unresolved-attribute]
        paths = pb.propertyListForType_(AppKit.NSFilenamesPboardType)  # ty: ignore[unresolved-attribute]
        if not paths:
            return None
        for path in paths:
            try:
                img = Image.open(path)
                img.load()
                return img
            except Exception:
                continue
    except Exception:
        pass
    return None


def get_clipboard_image() -> Image.Image | None:
    if sys.platform == "darwin":
        file_image = _get_macos_clipboard_file_image()
        if file_image is not None:
            return file_image

    try:
        clipboard_content = ImageGrab.grabclipboard()
    except Exception:
        return None

    if clipboard_content is None:
        return None

    if isinstance(clipboard_content, list):
        for item in clipboard_content:
            if isinstance(item, str):
                try:
                    img = Image.open(item)
                    img.load()
                    return img
                except Exception:
                    continue
        return None

    if isinstance(clipboard_content, Image.Image):
        return clipboard_content

    return None


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")


def create_image_content(image: Image.Image) -> ImageBlockParam:
    base64_data = image_to_base64(image, "PNG")

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64_data,
        },
    }


def extract_text_content(content: Iterable[object] | str) -> str:
    if isinstance(content, str):
        return content

    blocks = [cast("dict[str, object]", b) for b in content if isinstance(b, dict)]

    texts = [
        cast(str, b.get("text", "")).strip()
        for b in blocks
        if b.get("type") == "text" and isinstance(b.get("text", ""), str)
    ]

    if texts:
        return "\n".join(text for text in texts if text)

    return ""
