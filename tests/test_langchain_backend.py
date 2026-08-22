"""
Tests for app/core/llm/langchain_backend.py -- the shared implementation
behind AnthropicClient/GeminiClient/GroqClient's create_message(). Since
this is the one place all three providers' request/response translation
now lives (see that module's docstring), this file is where that logic
actually gets exercised -- with LangChain's own FakeListChatModel /
GenericFakeChatModel standing in for a real provider connection, so
message conversion, tool translation, and response normalization are all
genuinely covered without needing a live API key.
"""
from unittest.mock import patch

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.core.llm import langchain_backend
from app.core.llm.router import Provider


def _patched(monkeypatch, chat_model):
    monkeypatch.setattr(langchain_backend, "_chat_model_for", lambda *a, **k: chat_model)


def test_invoke_returns_anthropic_shaped_dict(monkeypatch):
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="hello there")]))
    _patched(monkeypatch, fake)

    result = langchain_backend.invoke(
        provider=Provider.CLAUDE, model="claude-sonnet-5",
        system="Be helpful.", messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )
    assert result["content"] == [{"type": "text", "text": "hello there"}]
    assert result["stop_reason"] == "end_turn"
    assert set(result["usage"].keys()) == {
        "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
    }
    assert result["id"]


def test_invoke_extracts_real_usage_metadata(monkeypatch):
    ai_msg = AIMessage(
        content="ok",
        usage_metadata={"input_tokens": 42, "output_tokens": 7, "total_tokens": 49},
    )
    fake = GenericFakeChatModel(messages=iter([ai_msg]))
    _patched(monkeypatch, fake)

    result = langchain_backend.invoke(
        provider=Provider.GEMINI, model="gemini-3.6-flash",
        system="sys", messages=[{"role": "user", "content": "hi"}],
    )
    assert result["usage"]["input_tokens"] == 42
    assert result["usage"]["output_tokens"] == 7
    # This codebase's cache-token fields are Anthropic-only (see
    # gemini_client.py/groq_client.py docstrings) -- always 0 here.
    assert result["usage"]["cache_creation_input_tokens"] == 0
    assert result["usage"]["cache_read_input_tokens"] == 0


def test_invoke_handles_missing_usage_metadata_gracefully(monkeypatch):
    fake = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))  # no usage_metadata
    _patched(monkeypatch, fake)

    result = langchain_backend.invoke(
        provider=Provider.GROQ, model="openai/gpt-oss-120b",
        system="sys", messages=[{"role": "user", "content": "hi"}],
    )
    assert result["usage"]["input_tokens"] == 0
    assert result["usage"]["output_tokens"] == 0


def test_invoke_handles_multi_turn_conversation(monkeypatch):
    """Confirms role mapping (assistant -> AIMessage, user -> HumanMessage)
    for a multi-turn history, not just a single user message -- matters
    for any future call site (e.g. the voice agent) that sends prior turns."""
    captured_messages = {}

    class CapturingFake(GenericFakeChatModel):
        def invoke(self, messages, *a, **kw):
            captured_messages["messages"] = messages
            return AIMessage(content="ack")

    fake = CapturingFake(messages=iter([]))
    _patched(monkeypatch, fake)

    langchain_backend.invoke(
        provider=Provider.CLAUDE, model="claude-sonnet-5",
        system="Be helpful.",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
            {"role": "user", "content": "third"},
        ],
    )
    lc_messages = captured_messages["messages"]
    # SystemMessage, then Human/AI/Human in order
    assert lc_messages[0].content == "Be helpful."
    assert lc_messages[1].content == "first" and lc_messages[1].type == "human"
    assert lc_messages[2].content == "second" and lc_messages[2].type == "ai"
    assert lc_messages[3].content == "third" and lc_messages[3].type == "human"


def test_invoke_flattens_system_content_blocks_and_drops_cache_control(monkeypatch):
    captured_messages = {}

    class CapturingFake(GenericFakeChatModel):
        def invoke(self, messages, *a, **kw):
            captured_messages["messages"] = messages
            return AIMessage(content="ack")

    fake = CapturingFake(messages=iter([]))
    _patched(monkeypatch, fake)

    system_blocks = [{"type": "text", "text": "be concise", "cache_control": {"type": "ephemeral"}}]
    langchain_backend.invoke(
        provider=Provider.CLAUDE, model="claude-sonnet-5",
        system=system_blocks, messages=[{"role": "user", "content": "hi"}],
    )
    assert captured_messages["messages"][0].content == "be concise"


def test_invoke_binds_tools_when_provided(monkeypatch):
    bind_calls = []

    class TrackingFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            bind_calls.append(tools)
            return self

        def invoke(self, messages, *a, **kw):
            return AIMessage(content="ack")

    fake = TrackingFake(messages=iter([]))
    _patched(monkeypatch, fake)

    tools = [{"name": "lookup", "description": "look something up",
              "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}]
    langchain_backend.invoke(
        provider=Provider.CLAUDE, model="claude-sonnet-5",
        system="sys", messages=[{"role": "user", "content": "hi"}], tools=tools,
    )
    assert len(bind_calls) == 1
    assert bind_calls[0][0]["type"] == "function"
    assert bind_calls[0][0]["function"]["name"] == "lookup"


def test_invoke_skips_bind_tools_when_no_tools_given(monkeypatch):
    class TrackingFake(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            raise AssertionError("bind_tools should not be called with no tools")

        def invoke(self, messages, *a, **kw):
            return AIMessage(content="ack")

    fake = TrackingFake(messages=iter([]))
    _patched(monkeypatch, fake)

    result = langchain_backend.invoke(
        provider=Provider.CLAUDE, model="claude-sonnet-5",
        system="sys", messages=[{"role": "user", "content": "hi"}],
    )
    assert result["content"][0]["text"] == "ack"


def test_chat_model_for_dispatches_to_correct_langchain_class():
    """Confirms the constructor kwargs line up with each package's real
    (installed, inspected) field names -- anthropic_api_key vs
    google_api_key vs api_key, max_tokens vs max_output_tokens, etc."""
    with patch("langchain_anthropic.ChatAnthropic") as MockAnthropic:
        langchain_backend._chat_model_for(Provider.CLAUDE, "claude-sonnet-5", "key123", 512)
        MockAnthropic.assert_called_once_with(model="claude-sonnet-5", api_key="key123", max_tokens=512)

    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as MockGemini:
        langchain_backend._chat_model_for(Provider.GEMINI, "gemini-3.6-flash", "key456", 512)
        MockGemini.assert_called_once_with(model="gemini-3.6-flash", google_api_key="key456", max_output_tokens=512)

    with patch("langchain_groq.ChatGroq") as MockGroq:
        langchain_backend._chat_model_for(Provider.GROQ, "openai/gpt-oss-120b", "key789", 512)
        MockGroq.assert_called_once_with(model="openai/gpt-oss-120b", api_key="key789", max_tokens=512)


def test_text_from_content_handles_plain_string_and_block_list():
    assert langchain_backend._text_from_content("plain text") == "plain text"
    assert langchain_backend._text_from_content(None) == ""
    blocks = [{"type": "text", "text": "part one"}, {"type": "tool_use", "text": "ignored"},
              {"type": "text", "text": "part two"}]
    assert langchain_backend._text_from_content(blocks) == "part one\npart two"


def test_stop_reason_maps_known_values_and_defaults_to_end_turn():
    class Msg:
        response_metadata = {"stop_reason": "max_tokens"}
    assert langchain_backend._stop_reason_from(Msg()) == "max_tokens"

    class MsgNoMeta:
        response_metadata = {}
    assert langchain_backend._stop_reason_from(MsgNoMeta()) == "end_turn"
