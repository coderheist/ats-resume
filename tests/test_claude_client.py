from app.core.llm.claude_client import AnthropicClient, BatchRequestSpec, FakeAnthropicClient
from app.core.llm.router import Provider, TaskType, route


def test_create_message_with_cost_attaches_real_cost_breakdown():
    client = FakeAnthropicClient()
    client.next_usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    result = client.create_message_with_cost(
        model=route(TaskType.CONVERSATIONAL_AGENT),
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.cost.total_cost > 0
    assert result.stop_reason == "end_turn"
    assert result.content[0]["text"] == "[fake response]"


def test_second_call_with_cache_hit_costs_less_than_first():
    """Simulates the realistic pattern: first call writes the cache,
    second call reads it -- the second call's dollar cost for the shared
    prefix should be far lower."""
    client = FakeAnthropicClient()
    model = route(TaskType.CONVERSATIONAL_AGENT)

    client.next_usage = {
        "input_tokens": 10, "output_tokens": 50,
        "cache_creation_input_tokens": 5000, "cache_read_input_tokens": 0,
    }
    first = client.create_message_with_cost(model=model, system="x", messages=[])

    client.next_usage = {
        "input_tokens": 10, "output_tokens": 50,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5000,
    }
    second = client.create_message_with_cost(model=model, system="x", messages=[])

    assert second.cost.total_cost < first.cost.total_cost
    assert len(client.calls) == 2


def test_batch_lifecycle_round_trips_custom_ids():
    client = FakeAnthropicClient()
    requests = [
        BatchRequestSpec(custom_id="resume_1", model="claude-haiku-4-5-20251001",
                          system="classify", messages=[{"role": "user", "content": "doc 1"}]),
        BatchRequestSpec(custom_id="resume_2", model="claude-haiku-4-5-20251001",
                          system="classify", messages=[{"role": "user", "content": "doc 2"}]),
    ]
    batch = client.create_message_batch(requests)
    assert batch["processing_status"] == "ended"

    status = client.get_batch_status(batch["id"])
    assert status["id"] == batch["id"]

    results = client.retrieve_batch_results(batch["id"])
    returned_ids = {r["custom_id"] for r in results}
    assert returned_ids == {"resume_1", "resume_2"}
    for r in results:
        assert r["result"]["type"] == "succeeded"


def test_real_client_create_message_delegates_to_langchain_backend(monkeypatch):
    """AnthropicClient.create_message is now a thin call into
    langchain_backend.invoke() -- see that module's docstring for why.
    The Batch API methods deliberately do NOT go through this (Anthropic's
    real Batch endpoint has no LangChain equivalent) -- see claude_client.py's
    module docstring -- so this only covers create_message."""
    client = AnthropicClient(api_key="test-key")
    captured = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return {"id": "x", "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr("app.core.llm.langchain_backend.invoke", fake_invoke)
    result = client.create_message(
        model="claude-sonnet-5", system="sys", messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
    )
    assert result["content"][0]["text"] == "ok"
    assert captured["provider"] == Provider.CLAUDE
    assert captured["model"] == "claude-sonnet-5"
    assert captured["api_key"] == "test-key"
    assert captured["max_tokens"] == 256
