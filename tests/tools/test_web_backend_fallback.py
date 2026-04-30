"""Tests for the web backend chain + fallback behavior.

Verifies that ``web.fallback_backends`` configuration is honored, that
each per-backend exception (rate limit, payment required, network error)
hands off to the next entry instead of failing the whole tool call, and
that the chain surfaces a clear error only when every backend has been
exhausted.
"""

import asyncio
import json
import os
from unittest.mock import patch, MagicMock

import pytest


# ─── _get_backend_chain ─────────────────────────────────────────────────────


class TestGetBackendChain:
    def test_primary_only(self):
        from tools.web_tools import _get_backend_chain
        with patch("tools.web_tools._load_web_config", return_value={"backend": "exa"}):
            assert _get_backend_chain() == ["exa"]

    def test_primary_with_fallbacks(self):
        from tools.web_tools import _get_backend_chain
        with patch(
            "tools.web_tools._load_web_config",
            return_value={"backend": "exa", "fallback_backends": ["tavily", "firecrawl"]},
        ):
            assert _get_backend_chain() == ["exa", "tavily", "firecrawl"]

    def test_drops_unknown_backends(self):
        from tools.web_tools import _get_backend_chain
        with patch(
            "tools.web_tools._load_web_config",
            return_value={"backend": "exa", "fallback_backends": ["bogus", "tavily"]},
        ):
            assert _get_backend_chain() == ["exa", "tavily"]

    def test_dedups_backends(self):
        from tools.web_tools import _get_backend_chain
        with patch(
            "tools.web_tools._load_web_config",
            return_value={"backend": "exa", "fallback_backends": ["exa", "tavily", "tavily"]},
        ):
            assert _get_backend_chain() == ["exa", "tavily"]

    def test_string_fallback_coerced_to_list(self):
        # YAML allows a single string instead of a list. Don't crash on that.
        from tools.web_tools import _get_backend_chain
        with patch(
            "tools.web_tools._load_web_config",
            return_value={"backend": "exa", "fallback_backends": "tavily"},
        ):
            assert _get_backend_chain() == ["exa", "tavily"]

    def test_no_primary_falls_back_to_legacy_get_backend(self):
        # Empty config → chain is whatever the legacy auto-detect picks,
        # so single-backend deployments behave as before.
        from tools.web_tools import _get_backend_chain
        with patch("tools.web_tools._load_web_config", return_value={}):
            with patch("tools.web_tools._get_backend", return_value="firecrawl"):
                assert _get_backend_chain() == ["firecrawl"]


# ─── web_search_tool fallback ───────────────────────────────────────────────


class TestWebSearchFallback:
    def test_first_backend_succeeds_no_fallback(self):
        from tools import web_tools

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(
                web_tools, "_search_with_backend",
                return_value={"success": True, "data": {"web": [{"title": "ok"}]}},
            ) as mock_search:
                result = json.loads(web_tools.web_search_tool("query", limit=1))

        assert result["success"] is True
        assert result["data"]["web"][0]["title"] == "ok"
        # Only the primary should have been called.
        assert mock_search.call_count == 1
        assert mock_search.call_args.args[0] == "exa"

    def test_falls_back_when_primary_raises(self):
        from tools import web_tools

        def fake_search(backend, query, limit):
            if backend == "exa":
                raise RuntimeError("HTTP 402 Payment Required")
            return {"success": True, "data": {"web": [{"title": f"from {backend}"}]}}

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(web_tools, "_search_with_backend", side_effect=fake_search) as mock_search:
                result = json.loads(web_tools.web_search_tool("query", limit=1))

        assert result["success"] is True
        assert result["data"]["web"][0]["title"] == "from tavily"
        assert mock_search.call_count == 2
        assert [c.args[0] for c in mock_search.call_args_list] == ["exa", "tavily"]

    def test_all_backends_fail_returns_aggregated_error(self):
        from tools import web_tools

        def fake_search(backend, query, limit):
            raise RuntimeError(f"{backend} is down")

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(web_tools, "_search_with_backend", side_effect=fake_search):
                result = json.loads(web_tools.web_search_tool("query", limit=1))

        # tool_error returns {"error": "..."} — no "success" field. Both
        # backends must appear in the message so a misconfigured chain is
        # recoverable from the log.
        assert "error" in result
        assert "exa" in result["error"]
        assert "tavily" in result["error"]
        assert "tavily is down" in result["error"]


# ─── web_extract_tool fallback ──────────────────────────────────────────────


class TestWebExtractFallback:
    @staticmethod
    def _run(coro):
        return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)

    def test_first_backend_succeeds_no_fallback(self):
        from tools import web_tools

        async def fake_extract(backend, urls, fmt):
            return [{"url": urls[0], "title": "ok", "content": "body", "metadata": {}}]

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(web_tools, "_extract_with_backend", side_effect=fake_extract) as mock_extract:
                result = json.loads(asyncio.run(
                    web_tools.web_extract_tool(
                        urls=["https://example.com"],
                        use_llm_processing=False,
                    )
                ))

        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "ok"
        assert mock_extract.call_count == 1
        assert mock_extract.call_args.args[0] == "exa"

    def test_falls_back_when_primary_raises(self):
        from tools import web_tools

        call_log = []

        async def fake_extract(backend, urls, fmt):
            call_log.append(backend)
            if backend == "exa":
                raise RuntimeError("network unreachable")
            return [{"url": urls[0], "title": "from " + backend, "content": "body", "metadata": {}}]

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(web_tools, "_extract_with_backend", side_effect=fake_extract):
                result = json.loads(asyncio.run(
                    web_tools.web_extract_tool(
                        urls=["https://example.com"],
                        use_llm_processing=False,
                    )
                ))

        assert call_log == ["exa", "tavily"]
        assert result["results"][0]["title"] == "from tavily"

    def test_all_backends_fail_emits_per_url_error(self):
        from tools import web_tools

        async def fake_extract(backend, urls, fmt):
            raise RuntimeError(f"{backend} blew up")

        with patch.object(web_tools, "_get_backend_chain", return_value=["exa", "tavily"]):
            with patch.object(web_tools, "_extract_with_backend", side_effect=fake_extract):
                result = json.loads(asyncio.run(
                    web_tools.web_extract_tool(
                        urls=["https://example.com", "https://example.org"],
                        use_llm_processing=False,
                    )
                ))

        # The pipeline keeps the {"results": [...]} shape; each URL gets
        # an error entry that names the chain that was tried.
        assert len(result["results"]) == 2
        for entry in result["results"]:
            assert "All web_extract backends failed" in entry["error"]
            assert "exa" in entry["error"]
            assert "tavily" in entry["error"]
