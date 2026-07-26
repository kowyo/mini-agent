from pathlib import Path

import pytest

from mini_agent.agent.tools.file import (
    MAX_BYTES,
    MAX_LINES,
    _detect_image_media_type,
    run_read,
)


@pytest.fixture
def sample_file(tmp_path: Path) -> Path:
    f = tmp_path / "sample.txt"
    f.write_text("\n".join(f"line {i}" for i in range(1, 101)))
    return f


def test_read_whole_file(sample_file: Path) -> None:
    result = run_read(str(sample_file))
    assert "line 1" in result
    assert "line 100" in result
    assert "more lines" not in result


def test_read_with_limit(sample_file: Path) -> None:
    result = run_read(str(sample_file), limit=5)
    assert "line 1" in result
    assert "line 5" in result
    assert "line 6" not in result.split("[")[0]
    assert "95 more lines" in result
    assert "offset=6" in result


def test_read_with_offset(sample_file: Path) -> None:
    result = run_read(str(sample_file), offset=50)
    assert "line 49" not in result.split("\n")[0]
    assert "line 50" in result
    assert "line 100" in result


def test_read_with_offset_and_limit(sample_file: Path) -> None:
    result = run_read(str(sample_file), offset=10, limit=5)
    assert "line 10" in result
    assert "line 14" in result
    assert "line 15" not in result.split("[")[0]
    assert "86 more lines" in result
    assert "offset=15" in result


def test_offset_beyond_eof(sample_file: Path) -> None:
    result = run_read(str(sample_file), offset=200)
    assert "Error" in result
    assert "beyond end of file" in result


def test_offset_one_is_default(sample_file: Path) -> None:
    result_no_offset = run_read(str(sample_file), limit=5)
    result_offset_one = run_read(str(sample_file), offset=1, limit=5)
    assert result_no_offset == result_offset_one


def test_line_limit_truncation(tmp_path: Path) -> None:
    f = tmp_path / "big.txt"
    total = MAX_LINES + 500
    f.write_text("\n".join(f"line {i}" for i in range(1, total + 1)))
    result = run_read(str(f))
    assert f"Showing lines 1-{MAX_LINES} of {total}" in result
    assert f"offset={MAX_LINES + 1}" in result


def test_byte_limit_truncation(tmp_path: Path) -> None:
    f = tmp_path / "heavy.txt"
    long_line = "x" * 200
    line_count = (MAX_BYTES // 200) + 100
    f.write_text("\n".join(long_line for _ in range(line_count)))
    result = run_read(str(f))
    assert "limit" in result
    assert "offset=" in result


def test_missing_file() -> None:
    result = run_read("/nonexistent/path/file.txt")
    assert "Error" in result


def test_continuation_hint_at_user_limit_boundary(sample_file: Path) -> None:
    result = run_read(str(sample_file), offset=1, limit=10)
    assert "offset=11" in result
    assert "90 more lines" in result


PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
JPEG_HEADER = b"\xff\xd8\xff\xe0" + b"\x00" * 12
GIF_HEADER = b"GIF89a" + b"\x00" * 10
WEBP_HEADER = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 4


HEADERS_BY_EXT: dict[str, bytes] = {
    ".png": PNG_HEADER,
    ".jpg": JPEG_HEADER,
    ".jpeg": JPEG_HEADER,
    ".gif": GIF_HEADER,
    ".webp": WEBP_HEADER,
}


class TestImageDetection:
    def test_detect_by_extension_with_valid_header(self, tmp_path: Path) -> None:
        for ext, expected in [
            (".png", "image/png"),
            (".jpg", "image/jpeg"),
            (".jpeg", "image/jpeg"),
            (".gif", "image/gif"),
            (".webp", "image/webp"),
        ]:
            f = tmp_path / f"image{ext}"
            f.write_bytes(HEADERS_BY_EXT[ext])
            assert _detect_image_media_type(f) == expected

    def test_extension_without_valid_header_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.png"
        f.write_text("this is plain text, not a PNG")
        assert _detect_image_media_type(f) is None

    def test_detect_by_magic_bytes(self, tmp_path: Path) -> None:
        for header, expected in [
            (PNG_HEADER, "image/png"),
            (JPEG_HEADER, "image/jpeg"),
            (GIF_HEADER, "image/gif"),
            (WEBP_HEADER, "image/webp"),
        ]:
            f = tmp_path / "unknown_file"
            f.write_bytes(header)
            assert _detect_image_media_type(f) == expected

    def test_non_image_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "data.txt"
        f.write_text("hello world")
        assert _detect_image_media_type(f) is None

    def test_unsupported_image_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "image.bmp"
        f.write_bytes(b"BM" + b"\x00" * 14)
        assert _detect_image_media_type(f) is None


class TestReadImage:
    def test_returns_image_content_blocks(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.png"
        f.write_bytes(PNG_HEADER)
        result = run_read(str(f))
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert "image/png" in result[0]["text"]
        assert result[1]["type"] == "image"
        assert result[1]["source"]["media_type"] == "image/png"
        assert result[1]["source"]["type"] == "base64"

    def test_image_ignores_offset_and_limit(self, tmp_path: Path) -> None:
        f = tmp_path / "photo.jpg"
        f.write_bytes(JPEG_HEADER)
        result = run_read(str(f), offset=10, limit=5)
        assert isinstance(result, list)
        assert result[1]["source"]["media_type"] == "image/jpeg"

    def test_non_image_returns_string(self, sample_file: Path) -> None:
        result = run_read(str(sample_file))
        assert isinstance(result, str)
