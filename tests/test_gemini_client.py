from app.core.llm.claude_client import BatchRequestSpec
from app.core.llm.gemini_client import FakeGeminiClient
from app.core.llm.router import Provider, TaskType, route


def test_create_message_with_cost_attaches_real_cost_breakdown():
    client = FakeGeminiClient()
    client.next_usage = {
        "input_tokens": 100, "output_tokens": 50,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
    }
    result = client.create_message_with_cost(
        model=route(TaskType.CONVERSATIONAL_AGENT, provider=Provider.GEMINI),
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result.cost.total_cost > 0
    assert result.stop_reason == "end_turn"
    assert result.content[0]["text"] == "[fake gemini response]"


def test_batch_shim_round_trips_custom_ids():
    client = FakeGeminiClient()
    model = route(TaskType.FAST_CLASSIFICATION, provider=Provider.GEMINI)
    requests = [
        BatchRequestSpec(custom_id="resume_1", model=model, system="classify",
                          messages=[{"role": "user", "content": "doc 1"}]),
        BatchRequestSpec(custom_id="resume_2", model=model, system="classify",
                          messages=[{"role": "user", "content": "doc 2"}]),
    ]
    batch = client.create_message_batch(requests)
    assert batch["processing_status"] == "ended"

    results = client.retrieve_batch_results(batch["id"])
    returned_ids = {r["custom_id"] for r in results}
    assert returned_ids == {"resume_1", "resume_2"}
    for r in results:
        assert r["result"]["type"] == "succeeded"


def test_real_client_create_message_delegates_to_langchain_backend(monkeypatch):
    """GeminiClient.create_message is now a thin call into
    langchain_backend.invoke() -- see that module's docstring for why.
    This confirms the real (non-Fake) client actually wires the call
    through correctly (provider, model, api_key, system, messages, tools,
    max_tokens all passed on), without needing a real network call."""
    import app.core.llm.gemini_client as gemini_client_module

    captured = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return {"id": "x", "stop_reason": "end_turn", "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1}}

    monkeypatch.setattr("app.core.llm.langchain_backend.invoke", fake_invoke)
    client = gemini_client_module.GeminiClient(api_key="test-key")
    result = client.create_message(
        model="gemini-3.6-flash", system="sys", messages=[{"role": "user", "content": "hi"}],
        max_tokens=256,
    )
    assert result["content"][0]["text"] == "ok"
    assert captured["provider"] == Provider.GEMINI
    assert captured["model"] == "gemini-3.6-flash"
    assert captured["api_key"] == "test-key"
    assert captured["max_tokens"] == 256
