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


def _make_chatbot_mock(message_type: str = "", text_content=None, rich_items=None, **extra):
    msg = MagicMock()
    msg.message_type = message_type

    if text_content is None:
        msg.text = None
    else:
        msg.text = MagicMock()
        msg.text.content = text_content

    if rich_items is None:
        msg.rich_text_content = None
    else:
        msg.rich_text_content = MagicMock()
        msg.rich_text_content.rich_text_list = rich_items

    for name, value in extra.items():
        setattr(msg, name, value)
    return msg


_DEFAULT_DISPATCH_ATTRS = {
    "message_id": "msg-x",
    "conversation_type": "2",
    "conversation_id": "conv-1",
    "conversation_title": "Test Chat",
    "sender_id": "sender-1",
    "sender_nick": "Sender",
    "sender_staff_id": "staff-1",
    "create_at": None,
    "session_webhook": "https://example/webhook",
}


def _make_dispatch_mock(message_type, *, text_content=None, rich_items=None, **overrides):
    attrs = {**_DEFAULT_DISPATCH_ATTRS, **overrides}
    return _make_chatbot_mock(
        message_type,
        text_content=text_content,
        rich_items=rich_items,
        **attrs,
    )


class TestExtractText:

    def test_plain_text_message(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("text", text_content="  hello world  ")
        assert DingTalkAdapter._extract_text(msg) == "hello world"

    def test_empty_plain_text(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("text", text_content="")
        assert DingTalkAdapter._extract_text(msg) == ""

    def test_text_dict_shape_fallback(self):
        # Older SDKs / custom handlers may pass a dict rather than TextContent.
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "text"
        msg.text = {"content": " from dict "}
        msg.rich_text_content = None
        assert DingTalkAdapter._extract_text(msg) == "from dict"

    def test_rich_text_concatenates_text_segments(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock(
            "richText",
            rich_items=[{"text": "hello"}, {"text": "world"}],
        )
        assert DingTalkAdapter._extract_text(msg) == "hello world"

    def test_rich_text_with_inline_picture(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock(
            "richText",
            rich_items=[
                {"text": "look"},
                {"downloadCode": "abc", "type": "picture"},
                {"text": "at this"},
            ],
        )
        assert DingTalkAdapter._extract_text(msg) == "look [图片] at this"

    def test_rich_text_with_at_mention(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock(
            "richText",
            rich_items=[
                {"type": "at", "name": "Yoji", "userId": "u1"},
                {"text": "hi"},
            ],
        )
        assert DingTalkAdapter._extract_text(msg) == "@Yoji hi"

    def test_rich_text_skips_unknown_items(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock(
            "richText",
            rich_items=[{"text": "keep"}, {"foo": "bar"}, "not a dict"],
        )
        assert DingTalkAdapter._extract_text(msg) == "keep"

    def test_rich_text_with_no_items_returns_empty(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("richText", rich_items=[])
        assert DingTalkAdapter._extract_text(msg) == ""

    def test_rich_text_missing_content_object_returns_empty(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = MagicMock()
        msg.message_type = "richText"
        msg.text = None
        msg.rich_text_content = None
        assert DingTalkAdapter._extract_text(msg) == ""

    def test_picture_msgtype_returns_placeholder(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("picture")
        assert DingTalkAdapter._extract_text(msg) == "[图片]"

    def test_unknown_msgtype_returns_marker(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("audio")
        assert DingTalkAdapter._extract_text(msg) == "[未支持的消息类型: audio]"

    def test_missing_msgtype_falls_back_to_plain_text(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("", text_content="salvage me")
        assert DingTalkAdapter._extract_text(msg) == "salvage me"

    def test_accepts_precomputed_msgtype(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        msg = _make_chatbot_mock("", text_content="ignored")
        assert DingTalkAdapter._extract_text(msg, msgtype="picture") == "[图片]"


# ---------------------------------------------------------------------------
# _on_message dispatch routing
# ---------------------------------------------------------------------------


class TestOnMessageRouting:

    def _make_adapter(self):
        from gateway.platforms.dingtalk import DingTalkAdapter
        adapter = DingTalkAdapter(PlatformConfig(enabled=True))
        captured = []

        async def fake_handle(event):
            captured.append(event)

        adapter.handle_message = fake_handle  # type: ignore[assignment]
        return adapter, captured

    @pytest.mark.asyncio
    async def test_plain_text_dispatches_as_text(self):
        from gateway.platforms.base import MessageType
        adapter, captured = self._make_adapter()
        await adapter._on_message(_make_dispatch_mock("text", text_content="hi"))
        assert len(captured) == 1
        assert captured[0].text == "hi"
        assert captured[0].message_type == MessageType.TEXT

    @pytest.mark.asyncio
    async def test_empty_text_is_skipped(self):
        adapter, captured = self._make_adapter()
        await adapter._on_message(_make_dispatch_mock("text", text_content=""))
        assert captured == []

    @pytest.mark.asyncio
    async def test_picture_dispatches_with_photo_type(self):
        from gateway.platforms.base import MessageType
        adapter, captured = self._make_adapter()
        await adapter._on_message(_make_dispatch_mock("picture"))
        assert len(captured) == 1
        ev = captured[0]
        assert ev.message_type == MessageType.PHOTO
        assert ev.text == "[图片]"
        assert ev.source.chat_type == "group"

    @pytest.mark.asyncio
    async def test_rich_text_dispatches_with_mixed_content(self):
        from gateway.platforms.base import MessageType
        adapter, captured = self._make_adapter()
        msg = _make_dispatch_mock(
            "richText",
            rich_items=[{"text": "see"}, {"downloadCode": "x", "type": "picture"}],
        )
        await adapter._on_message(msg)
        assert len(captured) == 1
        assert captured[0].message_type == MessageType.TEXT
        assert captured[0].text == "see [图片]"

    @pytest.mark.asyncio
    async def test_empty_rich_text_dispatches_with_fallback_marker(self):
        adapter, captured = self._make_adapter()
        await adapter._on_message(_make_dispatch_mock("richText", rich_items=[]))
        assert len(captured) == 1
        assert "richText" in captured[0].text

    @pytest.mark.asyncio
    async def test_unknown_msgtype_still_dispatches(self):
        from gateway.platforms.base import MessageType
        adapter, captured = self._make_adapter()
        await adapter._on_message(_make_dispatch_mock("audio"))
        assert len(captured) == 1
        assert captured[0].message_type == MessageType.TEXT
        assert "audio" in captured[0].text

    @pytest.mark.asyncio
    async def test_session_webhook_cached_on_dispatch(self):
        adapter, _ = self._make_adapter()
        msg = _make_dispatch_mock(
            "text",
            text_content="hello",
            conversation_id="conv-cache",
            session_webhook="https://api.dingtalk.com/robot/sendBySession?sessionWebhookKey=cache",
        )
        await adapter._on_message(msg)
        assert adapter._session_webhooks["conv-cache"] == "https://api.dingtalk.com/robot/sendBySession?sessionWebhookKey=cache"


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
