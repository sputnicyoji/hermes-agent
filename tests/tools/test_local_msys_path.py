"""Tests for MSYS -> Windows path normalization in LocalEnvironment.

On Windows + Git Bash, `pwd -P` returns paths like `/d/Hermes_Agent`. Those
cannot be passed to `subprocess.Popen(cwd=...)` directly — Windows raises
`NotADirectoryError: [WinError 267]`. The local backend must translate them
back to native form before they leak into self.cwd.
"""

from unittest.mock import patch

import pytest

from tools.environments import local as local_mod
from tools.environments.local import _msys_to_windows_path


@pytest.fixture
def windows_host(monkeypatch):
    """Force the Windows code paths regardless of test host OS."""
    monkeypatch.setattr(local_mod, "_IS_WINDOWS", True)


class TestMsysToWindowsPath:
    def test_converts_drive_path(self, windows_host):
        assert _msys_to_windows_path("/d/Hermes_Agent") == "D:\\Hermes_Agent"

    def test_converts_nested_path(self, windows_host):
        assert (
            _msys_to_windows_path("/c/Users/zhangxuechen")
            == "C:\\Users\\zhangxuechen"
        )

    def test_drive_root_only(self, windows_host):
        assert _msys_to_windows_path("/c") == "C:\\"
        assert _msys_to_windows_path("/c/") == "C:\\"

    def test_uppercases_drive_letter(self, windows_host):
        assert _msys_to_windows_path("/d/foo") == "D:\\foo"

    def test_passthrough_native_windows_path(self, windows_host):
        assert _msys_to_windows_path("D:\\Hermes_Agent") == "D:\\Hermes_Agent"
        assert _msys_to_windows_path("C:/Users/foo") == "C:/Users/foo"

    def test_passthrough_non_drive_posix_path(self, windows_host):
        # `/tmp/foo` is not an MSYS drive path — leave it alone. Popen will
        # still fail, but that is a separate problem, not one we can paper
        # over with a path translation.
        assert _msys_to_windows_path("/tmp/foo") == "/tmp/foo"

    def test_passthrough_unc_path(self, windows_host):
        # UNC paths start with `//` — second char is `/`, not a drive letter.
        assert _msys_to_windows_path("//server/share") == "//server/share"

    def test_passthrough_tilde(self, windows_host):
        assert _msys_to_windows_path("~") == "~"
        assert _msys_to_windows_path("~/projects") == "~/projects"

    def test_empty_string(self, windows_host):
        assert _msys_to_windows_path("") == ""

    def test_no_op_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        assert _msys_to_windows_path("/d/Hermes_Agent") == "/d/Hermes_Agent"


class TestUpdateCwdNormalizesMsysPath:
    """`_update_cwd` reads the cwd file written by `pwd -P` and assigns it
    to self.cwd. On Windows that value must be normalized before any
    subsequent Popen call uses it.
    """

    def _make_env_without_init(self):
        # Bypass __init__ + init_session so we can drive _update_cwd in
        # isolation without spawning bash.
        env = local_mod.LocalEnvironment.__new__(local_mod.LocalEnvironment)
        env.cwd = "D:\\Hermes_Agent"
        env._cwd_marker = "__HERMES_CWD_test__"
        return env

    def test_file_source_normalized(self, windows_host, tmp_path):
        env = self._make_env_without_init()
        cwd_file = tmp_path / "hermes-cwd.txt"
        cwd_file.write_text("/d/Hermes_Agent\n")
        env._cwd_file = str(cwd_file)

        env._update_cwd({"output": ""})
        assert env.cwd == "D:\\Hermes_Agent"

    def test_marker_source_normalized(self, windows_host, tmp_path):
        env = self._make_env_without_init()
        # No cwd file -> file branch is a no-op, marker branch wins.
        env._cwd_file = str(tmp_path / "missing.txt")
        marker = env._cwd_marker
        result = {"output": f"hello\n{marker}/c/Users/foo{marker}\n"}

        env._update_cwd(result)
        assert env.cwd == "C:\\Users\\foo"
        assert marker not in result["output"]

    def test_non_windows_keeps_posix(self, monkeypatch, tmp_path):
        monkeypatch.setattr(local_mod, "_IS_WINDOWS", False)
        env = self._make_env_without_init()
        env.cwd = "/home/user"
        cwd_file = tmp_path / "hermes-cwd.txt"
        cwd_file.write_text("/home/user/projects\n")
        env._cwd_file = str(cwd_file)

        env._update_cwd({"output": ""})
        assert env.cwd == "/home/user/projects"
