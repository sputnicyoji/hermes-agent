"""Tests for MSYS -> Windows path normalization in LocalEnvironment.

On Windows + Git Bash, `pwd -P` returns paths like `/d/Hermes_Agent`. Those
cannot be passed to `subprocess.Popen(cwd=...)` directly — Windows raises
`NotADirectoryError: [WinError 267]`. The local backend must translate them
back to native form before they leak into self.cwd.
"""

import pytest

from tools.environments import local as local_mod
from tools.environments.base import _cwd_marker
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

    def test_converts_wsl_drive_path(self, windows_host):
        # WSL bash emits `/mnt/c/...`. `_find_bash` avoids WSL, but the
        # normalizer must still understand the form for callers that
        # bypass `_find_bash` or persist a WSL path from a prior process.
        assert (
            _msys_to_windows_path("/mnt/c/Users/zhangxuechen")
            == "C:\\Users\\zhangxuechen"
        )

    def test_converts_wsl_nested(self, windows_host):
        assert (
            _msys_to_windows_path("/mnt/d/Hermes_Agent")
            == "D:\\Hermes_Agent"
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


class TestCwdSetterNormalizes:
    """Assigning to `LocalEnvironment.cwd` routes through the property
    setter so MSYS paths from any source — file, stdout marker, direct
    assignment — all get normalized at the single write boundary.
    """

    def _make_env_without_init(self, session_id: str = "test"):
        # Bypass __init__ + init_session so we can drive _update_cwd in
        # isolation without spawning bash. _update_cwd currently depends
        # on these instance attributes: cwd (property), _cwd_marker,
        # _cwd_file. If that list grows, this fixture must too.
        env = local_mod.LocalEnvironment.__new__(local_mod.LocalEnvironment)
        env._cwd = "D:\\seed"
        env._cwd_marker = _cwd_marker(session_id)
        return env

    def test_setter_normalizes_direct_assignment(self, windows_host):
        env = self._make_env_without_init()
        env.cwd = "/d/Hermes_Agent"
        assert env.cwd == "D:\\Hermes_Agent"

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
