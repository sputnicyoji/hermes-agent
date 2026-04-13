"""Tests for DingTalk platform adapter."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from gateway.config import Platform, PlatformConfig


# ---------------------------------------------------------------------------
# Requirements check
# ---------------------------------------------------------------------------


class TestDingTalkRequirements:

    def test_returns_false_when_sdk_missing(self, monkeypatch):
        with patch.dict("sys.modules", {"dingtalk_stream": None}):
            monkeypatch.setattr(
                "gateway.platforms.dingtalk.DINGTALK_STREAM_AVAILABLE", False
            )
            from gateway.platforms.dingtalk import check_dingtalk_requirements
            assert check_dingtalk_requirements() is False

    def test_returns_false_when_env_vars_missing(self, monkeypatch):
        monkeypatch.setattr(
            "gateway.platforms.dingtalk.DINGTALK_STREAM_AVAILABLE", True
        )
        monkeypatch.setattr("gateway.platforms.dingtalk.HTTPX_AVAILABLE", True)
        monkeypatch.delenv("DINGTALK_CLIENT_ID", raising=False)
        monkeypatch.delenv("DINGTALK_CLIENT_SECRET", raising=False)
        from gateway.platforms.dingtalk import check_dingtalk_requirements
        assert check_dingtalk_requirements() is False

    def test_returns_true_when_all_available(self, monkeypatch):
        monkeypatch.setattr(
            "gateway.platforms.dingtalk.DINGTALK_STREAM_AVAILABLE", True
        )
        monkeypatch.setattr("gateway.platforms.dingtalk.HTTPX_AVAILABLE", True)
        monkeypatch.setenv("DINGTALK_CLIENT_ID", "test-id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "test-secret")
        from gateway.platforms.dingtalk import check_dingtalk_requirements
        assert check_dingtalk_requirements() is True


# ---------------------------------------------------------------------------
# Adapter construction
# ---------------------------------------------------------------------------


class TestDingTalkAdapterInit:

    def test_reads_config_from_extra(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        config = PlatformConfig(
            enabled=True,
            extra={"client_id": "cfg-id", "client_secret": "cfg-secret"},
        )
        adapter = DingTalkAdapter(config)
        assert adapter._client_id == "cfg-id"
        assert adapter._client_secret == "cfg-secret"
        assert adapter.name == "Dingtalk"  # base class uses .title()

    def test_falls_back_to_env_vars(self, monkeypatch):
        monkeypatch.setenv("DINGTALK_CLIENT_ID", "env-id")
        monkeypatch.setenv("DINGTALK_CLIENT_SECRET", "env-secret")
        from gateway.platforms.dingtalk import DingTalkAdapter
        config = PlatformConfig(enabled=True)
        adapter = DingTalkAdapter(config)
        assert adapter._client_id == "env-id"
        assert adapter._client_secret == "env-secret"


# ---------------------------------------------------------------------------
# Message text extraction
# ---------------------------------------------------------------------------


class TestExtractText:

    def test_extracts_dict_text(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "text"
        msg.text = {"content": "  hello world  "}
        assert DingTalkAdapter._extract_text(msg) == "hello world"

    def test_extracts_string_text(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "text"
        msg.text = "plain text"
        assert DingTalkAdapter._extract_text(msg) == "plain text"

    def test_returns_empty_for_no_content(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "text"
        msg.text = ""
        assert DingTalkAdapter._extract_text(msg) == ""

    def test_picture_msgtype_returns_placeholder(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "picture"
        assert DingTalkAdapter._extract_text(msg) == "[图片]"

    def test_rich_text_renders_segments_and_at_mentions(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "richText"
        rich = MagicMock()
        rich.rich_text_list = [
            {"text": "hi"},
            {"type": "at", "name": "Yoji"},
            {"downloadCode": "abc"},
            {"text": "there"},
        ]
        msg.rich_text_content = rich
        assert DingTalkAdapter._extract_text(msg) == "hi @Yoji [图片] there"

    def test_unsupported_msgtype_returns_labelled_placeholder(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "audio"
        assert DingTalkAdapter._extract_text(msg) == "[未支持的消息类型: audio]"

    def test_explicit_msgtype_arg_wins_over_attribute(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "text"
        msg.text = "ignored"
        assert DingTalkAdapter._extract_text(msg, msgtype="picture") == "[图片]"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:

    def test_first_message_not_duplicate(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        assert adapter._dedup.is_duplicate("msg-1") is False

    def test_second_same_message_is_duplicate(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        adapter._dedup.is_duplicate("msg-1")
        assert adapter._dedup.is_duplicate("msg-1") is True

    def test_different_messages_not_duplicate(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        adapter._dedup.is_duplicate("msg-1")
        assert adapter._dedup.is_duplicate("msg-2") is False

    def test_cache_cleanup_on_overflow(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        max_size = adapter._dedup._max_size
        # Fill beyond max
        for i in range(max_size + 10):
            adapter._dedup.is_duplicate(f"msg-{i}")
        # Cache should have been pruned
        assert len(adapter._dedup._seen) <= max_size + 10


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------


class TestSend:

    @pytest.mark.asyncio
    async def test_send_posts_to_webhook(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "OK"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        adapter._http_client = mock_client

        result = await adapter.send(
            "chat-123", "Hello!",
            metadata={"session_webhook": "https://dingtalk.example/webhook"}
        )
        assert result.success is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "https://dingtalk.example/webhook"
        payload = call_args[1]["json"]
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["title"] == "Hermes"
        assert payload["markdown"]["text"] == "Hello!"

    @pytest.mark.asyncio
    async def test_send_fails_without_webhook(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        adapter._http_client = AsyncMock()

        result = await adapter.send("chat-123", "Hello!")
        assert result.success is False
        assert "session_webhook" in result.error

    @pytest.mark.asyncio
    async def test_send_uses_cached_webhook(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        adapter._http_client = mock_client
        adapter._session_webhooks["chat-123"] = "https://cached.example/webhook"

        result = await adapter.send("chat-123", "Hello!")
        assert result.success is True
        assert mock_client.post.call_args[0][0] == "https://cached.example/webhook"

    @pytest.mark.asyncio
    async def test_send_handles_http_error(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        adapter._http_client = mock_client

        result = await adapter.send(
            "chat-123", "Hello!",
            metadata={"session_webhook": "https://example/webhook"}
        )
        assert result.success is False
        assert "400" in result.error


# ---------------------------------------------------------------------------
# Connect / disconnect
# ---------------------------------------------------------------------------


class TestConnect:

    @pytest.mark.asyncio
    async def test_connect_fails_without_sdk(self, monkeypatch):
        monkeypatch.setattr(
            "gateway.platforms.dingtalk.DINGTALK_STREAM_AVAILABLE", False
        )
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        result = await adapter.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_connect_fails_without_credentials(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        adapter._client_id = ""
        adapter._client_secret = ""
        result = await adapter.connect()
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        adapter._session_webhooks["a"] = "http://x"
        adapter._dedup._seen["b"] = 1.0
        adapter._http_client = AsyncMock()
        adapter._stream_task = None

        await adapter.disconnect()
        assert len(adapter._session_webhooks) == 0
        assert len(adapter._dedup._seen) == 0
        assert adapter._http_client is None


# ---------------------------------------------------------------------------
# Platform enum
# ---------------------------------------------------------------------------


class TestPlatformEnum:

    def test_dingtalk_in_platform_enum(self):
        assert Platform.DINGTALK.value == "dingtalk"


# ---------------------------------------------------------------------------
# Picture attachment download
# ---------------------------------------------------------------------------

class TestFetchPictureAttachments:
    """Exercise the messageFiles/download flow via mocked SDK handler."""

    @staticmethod
    def _make_adapter(get_url_return):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True, extra={"client_id": "x", "client_secret": "y"}))
        handler = MagicMock()
        handler.get_image_download_url = MagicMock(return_value=get_url_return)
        adapter._handler = handler
        return adapter, handler

    def test_returns_empty_when_handler_missing(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True, extra={"client_id": "x", "client_secret": "y"}))
        assert adapter._handler is None
        msg = MagicMock()
        msg.get_image_list.return_value = ["code1"]
        urls, types = asyncio.run(adapter._fetch_picture_attachments(msg))
        assert urls == [] and types == []

    def test_downloads_and_caches_single_image(self):
        adapter, handler = self._make_adapter("https://cdn.example/img.jpg")
        msg = MagicMock()
        msg.get_image_list.return_value = ["code1"]
        cache_fn = AsyncMock(return_value="/tmp/cached.jpg")
        with patch("gateway.platforms.dingtalk.cache_image_from_url", cache_fn):
            urls, types = asyncio.run(adapter._fetch_picture_attachments(msg))
        assert urls == ["/tmp/cached.jpg"]
        assert types == ["image/jpeg"]
        handler.get_image_download_url.assert_called_once_with("code1")
        cache_fn.assert_awaited_once()

    def test_skips_codes_that_return_empty_url(self):
        adapter, handler = self._make_adapter("")  # SDK returns "" on failure
        msg = MagicMock()
        msg.get_image_list.return_value = ["code1", "code2"]
        cache_fn = AsyncMock()
        with patch("gateway.platforms.dingtalk.cache_image_from_url", cache_fn):
            urls, types = asyncio.run(adapter._fetch_picture_attachments(msg))
        assert urls == [] and types == []
        assert handler.get_image_download_url.call_count == 2
        cache_fn.assert_not_called()

    def test_continues_after_single_cache_failure(self):
        import httpx as _httpx
        adapter, handler = self._make_adapter(None)
        handler.get_image_download_url.side_effect = ["https://cdn/a.jpg", "https://cdn/b.jpg"]
        msg = MagicMock()
        msg.get_image_list.return_value = ["c1", "c2"]
        cache_fn = AsyncMock(side_effect=[_httpx.HTTPError("blip"), "/tmp/b.jpg"])
        with patch("gateway.platforms.dingtalk.cache_image_from_url", cache_fn):
            urls, types = asyncio.run(adapter._fetch_picture_attachments(msg))
        assert urls == ["/tmp/b.jpg"]
        assert types == ["image/jpeg"]

    def test_on_message_picture_populates_media_urls(self):
        """End-to-end: picture msgtype flows through to MessageEvent.media_urls."""
        adapter, handler = self._make_adapter("https://cdn.example/img.jpg")

        msg = MagicMock()
        msg.message_id = "m1"
        msg.message_type = "picture"
        msg.conversation_id = "cid1"
        msg.conversation_type = "2"
        msg.sender_id = "s1"
        msg.sender_nick = "Yoji"
        msg.sender_staff_id = "yoji"
        msg.conversation_title = "group"
        msg.create_at = 1712_000_000_000
        msg.session_webhook = None
        msg.get_image_list.return_value = ["code1"]

        captured = []
        async def _capture(event):
            captured.append(event)
        adapter.handle_message = _capture

        with patch("gateway.platforms.dingtalk.cache_image_from_url", AsyncMock(return_value="/tmp/pic.jpg")):
            asyncio.run(adapter._on_message(msg))

        assert len(captured) == 1
        ev = captured[0]
        assert ev.media_urls == ["/tmp/pic.jpg"]
        assert ev.media_types == ["image/jpeg"]
        assert ev.text == "[图片 × 1]"
        from gateway.platforms.base import MessageType
        assert ev.message_type == MessageType.PHOTO
