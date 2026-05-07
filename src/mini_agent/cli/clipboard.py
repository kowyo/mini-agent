import base64
import io
import subprocess
import sys
from collections.abc import Iterable
from typing import cast

from anthropic.types import ImageBlockParam, MessageParam
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


def _is_text_block(block: object) -> str | None:
    """Extract text from a content block. Returns text or None if not a text block."""
    if isinstance(block, dict):
        d = cast("dict[str, object]", block)
        block_type = d.get("type")
        text = d.get("text", "")
    else:
        block_type = getattr(block, "type", None)
        text = getattr(block, "text", None)

    if block_type == "text" and isinstance(text, str) and text.strip():
        return text.strip()
    return None


def extract_text_content(content: Iterable[object] | str) -> str:
    if isinstance(content, str):
        return content

    texts = [text for block in content if (text := _is_text_block(block)) is not None]

    return "\n".join(texts) if texts else ""


def copy_to_clipboard(text: str) -> bool:
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
        elif sys.platform == "win32":
            subprocess.run(["clip"], input=text, text=True, check=True)
        else:
            for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"]):
                try:
                    subprocess.run(cmd, input=text, text=True, check=True)
                    return True
                except FileNotFoundError, subprocess.CalledProcessError:
                    continue
            return False
        return True
    except FileNotFoundError, subprocess.CalledProcessError:
        return False


def copy_last_assistant_text(history: Iterable[MessageParam]) -> None:
    for message in reversed(list(history)):
        if message["role"] == "assistant":
            text = extract_text_content(message["content"])
            if text:
                if copy_to_clipboard(text):
                    print("Copied to clipboard.")
                else:
                    print("Failed to copy — no clipboard tool available.")
                return
    print("No assistant message to copy.")
