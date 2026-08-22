from app.core.llm.oss_extraction_client import FakeOSSExtractionClient


def test_fake_client_records_calls_and_returns_openai_shaped_response():
    client = FakeOSSExtractionClient()
    client.next_content = '{"foo": "bar"}'
    response = client.create_message(
        model="qwen3.6-35b-a3b-instruct",
        system="Extract fields.",
        messages=[{"role": "user", "content": "resume text"}],
        json_schema={"type": "object"},
    )
    assert response["choices"][0]["message"]["content"] == '{"foo": "bar"}'
    assert "usage" in response
    assert len(client.calls) == 1
    assert client.calls[0]["json_schema"] == {"type": "object"}


def test_fake_client_accepts_content_block_system_like_anthropic_shape():
    """Some call sites pass the same content-block system list used for
    Anthropic (from prompt_cache.py) even though this backend has no
    cache_control concept -- the fake should accept that shape without
    erroring, same as the real adapter's flatten-to-text handling."""
    client = FakeOSSExtractionClient()
    response = client.create_message(
        model="qwen3.6-35b-a3b-instruct",
        system=[{"type": "text", "text": "instructions", "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "hi"}],
    )
    assert response["choices"][0]["finish_reason"] == "stop"
