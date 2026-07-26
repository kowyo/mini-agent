from pathlib import Path

import pytest

from mini_agent.agent.tools.file import MAX_BYTES, MAX_LINES, run_read


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
