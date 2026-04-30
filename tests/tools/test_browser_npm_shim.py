"""Tests for the Windows npm-shim → native-exe resolver.

``agent-browser``'s npm package ships a POSIX shell script as its bin
entry. On Windows, npm wraps that shell script in a ``.cmd`` shim that
calls ``/bin/sh`` — which doesn't exist on native Windows, so every
invocation fails with the unhelpful "The system cannot find the path
specified" error. The package also ships ``bin/agent-browser-win32-x64.exe``
that runs fine; ``_resolve_npm_shim_to_native`` swaps the broken shim
for the working exe whenever both are present.
"""

import os
from unittest.mock import patch

import pytest


class TestResolveNpmShimToNative:
    def test_returns_path_unchanged_on_non_windows(self, tmp_path):
        from tools import browser_tool
        with patch.object(browser_tool.sys, "platform", "linux"):
            shim = tmp_path / "agent-browser"
            shim.write_text("#!/bin/sh\n")
            assert browser_tool._resolve_npm_shim_to_native(str(shim)) == str(shim)

    def test_returns_path_unchanged_when_suffix_doesnt_match(self, tmp_path):
        from tools import browser_tool
        with patch.object(browser_tool.sys, "platform", "win32"):
            # No .cmd/.bat suffix — could be the native exe already, or
            # an unknown wrapper. Don't touch it.
            already_native = tmp_path / "agent-browser.exe"
            already_native.write_bytes(b"")
            assert browser_tool._resolve_npm_shim_to_native(str(already_native)) == str(already_native)

    def test_returns_shim_when_native_not_found(self, tmp_path):
        from tools import browser_tool
        with patch.object(browser_tool.sys, "platform", "win32"):
            shim = tmp_path / "agent-browser.CMD"
            shim.write_text("@echo off\n")
            # No node_modules/agent-browser/bin/ alongside it.
            assert browser_tool._resolve_npm_shim_to_native(str(shim)) == str(shim)

    def test_swaps_global_install_shim_for_native(self, tmp_path):
        from tools import browser_tool
        # Layout that mirrors a real npm global install:
        #   <npm root>/agent-browser.CMD
        #   <npm root>/node_modules/agent-browser/bin/agent-browser-win32-x64.exe
        npm_root = tmp_path / "npm"
        npm_root.mkdir()
        shim = npm_root / "agent-browser.CMD"
        shim.write_text("@echo off\n")
        bin_dir = npm_root / "node_modules" / "agent-browser" / "bin"
        bin_dir.mkdir(parents=True)
        native = bin_dir / "agent-browser-win32-x64.exe"
        native.write_bytes(b"")

        with patch.object(browser_tool.sys, "platform", "win32"):
            with patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "AMD64"}, clear=False):
                resolved = browser_tool._resolve_npm_shim_to_native(str(shim))

        assert os.path.normpath(resolved) == os.path.normpath(str(native))

    def test_swaps_node_modules_bin_shim_for_native(self, tmp_path):
        # ``npm install`` in a project root puts the .cmd shim under
        # node_modules/.bin/, not at the npm root. The resolver must
        # walk up one level into the sibling agent-browser package.
        from tools import browser_tool
        node_modules = tmp_path / "node_modules"
        bin_dir = node_modules / ".bin"
        bin_dir.mkdir(parents=True)
        shim = bin_dir / "agent-browser.CMD"
        shim.write_text("@echo off\n")
        native_dir = node_modules / "agent-browser" / "bin"
        native_dir.mkdir(parents=True)
        native = native_dir / "agent-browser-win32-x64.exe"
        native.write_bytes(b"")

        with patch.object(browser_tool.sys, "platform", "win32"):
            with patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "AMD64"}, clear=False):
                resolved = browser_tool._resolve_npm_shim_to_native(str(shim))

        assert os.path.normpath(resolved) == os.path.normpath(str(native))

    def test_picks_arm64_native_on_arm_host(self, tmp_path):
        from tools import browser_tool
        npm_root = tmp_path / "npm"
        npm_root.mkdir()
        shim = npm_root / "agent-browser.CMD"
        shim.write_text("@echo off\n")
        bin_dir = npm_root / "node_modules" / "agent-browser" / "bin"
        bin_dir.mkdir(parents=True)
        # Only the arm64 build is shipped on this fake install.
        native = bin_dir / "agent-browser-win32-arm64.exe"
        native.write_bytes(b"")

        with patch.object(browser_tool.sys, "platform", "win32"):
            with patch.dict(os.environ, {"PROCESSOR_ARCHITECTURE": "ARM64"}, clear=False):
                resolved = browser_tool._resolve_npm_shim_to_native(str(shim))

        assert os.path.normpath(resolved) == os.path.normpath(str(native))
