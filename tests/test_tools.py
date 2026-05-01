"""Tests for agent tools module."""

import os
import tempfile
from pathlib import Path

import pytest

from mini_agent.agent.tools import (
    run_bash,
    run_edit,
    run_read,
    run_write,
    safe_path,
)
from mini_agent.config import WORKDIR


class TestRunBash:
    def test_dangerous_rm(self) -> None:
        result = run_bash("rm -rf /")
        assert "blocked" in result and "rm -rf /" in result

    def test_dangerous_sudo(self) -> None:
        result = run_bash("sudo ls")
        assert "blocked" in result

    def test_dangerous_shutdown(self) -> None:
        result = run_bash("shutdown -h now")
        assert "blocked" in result

    def test_dangerous_reboot(self) -> None:
        result = run_bash("reboot")
        assert "blocked" in result

    def test_dev_non_null_blocked(self) -> None:
        result = run_bash("echo hi > /dev/sda")
        assert "blocked" in result and "/dev/sda" in result

    def test_dev_null_allowed(self) -> None:
        result = run_bash("echo hi > /dev/null")
        assert "blocked" not in result

    def test_normal_command(self) -> None:
        result = run_bash("echo hello world")
        assert result == "hello world"

    def test_empty_output(self) -> None:
        result = run_bash("true")
        assert result == "(no output)"

    def test_output_truncation(self) -> None:
        result = run_bash("python3 -c \"print('x'*50001)\"")
        assert len(result) == 50000

    def test_stderr_captured(self) -> None:
        result = run_bash("python3 -c \"import sys; print('err', file=sys.stderr)\"")
        assert result == "err"

    def test_blocked_env_file_cat(self) -> None:
        result = run_bash("cat /path/to/.env")
        assert "blocked" in result and ".env" in result

    def test_blocked_env_file_ls(self) -> None:
        result = run_bash("ls -la .env.prod")
        assert "blocked" in result

    def test_blocked_ssh_key(self) -> None:
        result = run_bash("cat ~/.ssh/id_ed25519")
        assert "blocked" in result

    def test_blocked_authorized_keys(self) -> None:
        result = run_bash("cat ~/.ssh/authorized_keys")
        assert "blocked" in result

    def test_write_redirect_to_etc_blocked(self) -> None:
        result = run_bash("echo hi > /etc/evil.conf")
        assert "blocked" in result and "/etc/evil.conf" in result

    def test_append_redirect_to_etc_blocked(self) -> None:
        result = run_bash("echo hi >> /etc/passwd")
        assert "blocked" in result

    def test_write_redirect_to_tmp_allowed(self) -> None:
        path = Path(f"/tmp/test_bash_{os.urandom(4).hex()}.txt")
        try:
            result = run_bash(f"echo hi > {path}")
            assert "blocked" not in result
        finally:
            path.unlink(missing_ok=True)

    def test_tee_to_etc_blocked(self) -> None:
        result = run_bash("tee /etc/evil.conf")
        assert "blocked" in result

    def test_tee_to_tmp_allowed(self) -> None:
        path = Path(f"/tmp/test_tee_{os.urandom(4).hex()}.txt")
        try:
            result = run_bash(f"tee {path}")
            assert "blocked" not in result
        finally:
            path.unlink(missing_ok=True)

    def test_dd_of_etc_blocked(self) -> None:
        result = run_bash("dd if=/dev/zero of=/etc/evil count=1")
        assert "blocked" in result

    def test_dd_of_tmp_allowed(self) -> None:
        path = Path(f"/tmp/test_dd_{os.urandom(4).hex()}")
        try:
            result = run_bash(f"dd if=/dev/zero of={path} count=1")
            assert "blocked" not in result
        finally:
            path.unlink(missing_ok=True)


class TestSafePath:
    def test_relative_path_within_workdir(self) -> None:
        p = safe_path(".")
        assert p == WORKDIR.resolve()

    def test_relative_path_subdir(self) -> None:
        p = safe_path("src")
        assert p == (WORKDIR / "src").resolve()

    def test_relative_path_with_dotdot_inside(self) -> None:
        sub = WORKDIR / "src" / ".."
        p = safe_path(str(sub))
        assert p == WORKDIR.resolve()

    def test_tmp_absolute_path(self) -> None:
        p = safe_path("/tmp")
        assert p == Path("/tmp").resolve()

    def test_absolute_path_escapes(self) -> None:
        with pytest.raises(ValueError, match="Path escapes workspace"):
            safe_path("/etc/passwd")

    def test_relative_path_escapes(self) -> None:
        with pytest.raises(ValueError, match="Path escapes workspace"):
            safe_path("../../etc/passwd")


class TestRunRead:
    def test_read_safe_path_allowed(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir="/tmp"
        ) as f:
            f.write("hello world")
            path = Path(f.name)
        try:
            result = run_read(str(path))
            assert result == "hello world"
        finally:
            path.unlink(missing_ok=True)

    def test_read_any_path_allowed(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("outside content")
            path = Path(f.name)
        try:
            result = run_read(str(path))
            assert result == "outside content"
        finally:
            path.unlink(missing_ok=True)

    def test_read_env_file_blocked(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False, dir="/tmp"
        ) as f:
            f.write("SECRET=xxx")
            path = Path(f.name)
        try:
            result = run_read(str(path))
            assert "blocked" in result and ".env" in result
        finally:
            path.unlink(missing_ok=True)

    def test_read_ssh_key_blocked(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="id_ed25519", delete=False, dir="/tmp"
        ) as f:
            f.write("-----BEGIN OPENSSH PRIVATE KEY-----")
            path = Path(f.name)
        try:
            result = run_read(str(path))
            assert "blocked" in result and "id_ed25519" in result
        finally:
            path.unlink(missing_ok=True)

    def test_read_nonexistent_file(self) -> None:
        result = run_read("/nonexistent/path.txt")
        assert "Error" in result

    def test_read_with_limit(self) -> None:
        content = "\n".join(f"line {i}" for i in range(20))
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, dir="/tmp"
        ) as f:
            f.write(content)
            path = Path(f.name)
        try:
            result = run_read(str(path), limit=5)
            lines = result.splitlines()
            assert len(lines) == 6
            assert "... (15 more lines)" in result
        finally:
            path.unlink(missing_ok=True)


class TestRunWrite:
    def test_write_in_tmp(self) -> None:
        path = Path("/tmp") / f"test_write_{os.urandom(4).hex()}.txt"
        try:
            result = run_write(str(path), "content")
            assert "Wrote" in result
            assert path.read_text() == "content"
        finally:
            path.unlink(missing_ok=True)

    def test_write_env_file_blocked(self) -> None:
        path = Path("/tmp") / f".env.{os.urandom(4).hex()}"
        result = run_write(str(path), "SECRET=xxx")
        assert "blocked" in result
        assert not path.exists()

    def test_write_ssh_key_blocked(self) -> None:
        path = Path("/tmp") / f"id_ed25519_{os.urandom(4).hex()}"
        result = run_write(str(path), "ssh-key")
        assert "blocked" in result
        assert not path.exists()

    def test_write_outside_safe_path_blocked(self) -> None:
        result = run_write("/etc/evil.sh", "rm -rf /")
        assert "Error" in result


class TestRunEdit:
    def test_edit_safe_path(self) -> None:
        path = Path("/tmp") / f"test_edit_{os.urandom(4).hex()}.txt"
        try:
            path.write_text("hello world")
            result = run_edit(str(path), "world", "there")
            assert result == f"Edited {path}"
            assert path.read_text() == "hello there"
        finally:
            path.unlink(missing_ok=True)

    def test_edit_env_file_blocked(self) -> None:
        path = Path("/tmp") / f".env.{os.urandom(4).hex()}"
        path.write_text("OLD=val")
        try:
            result = run_edit(str(path), "OLD", "NEW")
            assert "blocked" in result
        finally:
            path.unlink(missing_ok=True)

    def test_edit_ssh_key_blocked(self) -> None:
        path = Path("/tmp") / f"id_ed25519_{os.urandom(4).hex()}"
        path.write_text("old key data")
        try:
            result = run_edit(str(path), "old", "new")
            assert "blocked" in result
        finally:
            path.unlink(missing_ok=True)

    def test_edit_outside_safe_path_blocked(self) -> None:
        result = run_edit("/etc/passwd", "root", "nope")
        assert "Error" in result

    def test_edit_text_not_found(self) -> None:
        path = Path("/tmp") / f"test_edit_{os.urandom(4).hex()}.txt"
        try:
            path.write_text("hello")
            result = run_edit(str(path), "nope", "new")
            assert "not found" in result
        finally:
            path.unlink(missing_ok=True)
