from app.core.llm.claude_client import BatchRequestSpec
from app.core.llm.groq_client import FakeGroqClient
from app.core.llm.router import Provider, TaskType, route


def test_create_message_with_cost_attaches_real_cost_breakdown():
    client = FakeGroqClient()
    client.next_usage = {
        "input_tokens": 400, "output_tokens": 60,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    }
    result = client.create_message_with_cost(
        model=route(TaskType.FAST_CLASSIFICATION, provider=Provider.GROQ),
        system="Classify this.",
        messages=[{"role": "user", "content": "resume text"}],
    )
    assert result.cost.total_cost > 0
    assert result.stop_reason == "end_turn"
    assert result.content[0]["text"] == "[fake groq response]"


def test_batch_shim_round_trips_custom_ids():
    client = FakeGroqClient()
    model = route(TaskType.DEEP_REASONING, provider=Provider.GROQ)
    requests = [
        BatchRequestSpec(custom_id="cand_1", model=model, system="rank",
                          messages=[{"role": "user", "content": "score 1"}]),
        BatchRequestSpec(custom_id="cand_2", model=model, system="rank",
                          messages=[{"role": "user", "content": "score 2"}]),
    ]
    batch = client.create_message_batch(requests)
    assert batch["processing_status"] == "ended"

    results = client.retrieve_batch_results(batch["id"])
    returned_ids = {r["custom_id"] for r in results}
    assert returned_ids == {"cand_1", "cand_2"}
    for r in results:
        assert r["result"]["type"] == "succeeded"


def test_real_client_create_message_delegates_to_langchain_backend(monkeypatch):
    """GroqClient.create_message is now a thin call into
    langchain_backend.invoke() -- see that module's docstring for why."""
    import app.core.llm.groq_client as groq_client_module

    captured = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return {"id": "x", "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr("app.core.llm.langchain_backend.invoke", fake_invoke)
    client = groq_client_module.GroqClient(api_key="test-key")
    result = client.create_message(
        model="openai/gpt-oss-120b", system="sys", messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
    )
    assert result["content"][0]["text"] == "ok"
    assert captured["provider"] == Provider.GROQ
    assert captured["model"] == "openai/gpt-oss-120b"
    assert captured["api_key"] == "test-key"
    assert captured["max_tokens"] == 256
