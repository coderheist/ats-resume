import pytest

from app.core.llm.router import (
    OSS_TASKS,
    PROVIDER_TO_TIER,
    TIER_TO_PROVIDER,
    Provider,
    TaskType,
    Tier,
    active_provider,
    provider_for_tier,
    route,
)


@pytest.fixture(autouse=True)
def _clear_llm_provider_env(monkeypatch):
    """Every test starts from the unset-env default (Claude) unless it
    sets LLM_PROVIDER itself -- prevents state leaking between tests."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def test_every_task_type_has_a_route():
    for task in TaskType:
        model = route(task)
        assert isinstance(model, str) and model


def test_extraction_crosscheck_routes_to_open_weight_model_not_a_closed_vendor():
    model = route(TaskType.EXTRACTION_CROSSCHECK)
    assert "claude" not in model.lower()
    assert "gpt" not in model.lower()
    assert "gemini" not in model.lower()


def test_extraction_crosscheck_is_the_only_oss_task():
    assert OSS_TASKS == frozenset({TaskType.EXTRACTION_CROSSCHECK})


def test_fast_classification_and_conversational_agent_stay_on_claude():
    """Default provider (no LLM_PROVIDER set) must stay Claude -- this is
    the production default and shouldn't silently change."""
    assert "claude" in route(TaskType.FAST_CLASSIFICATION).lower()
    assert "claude" in route(TaskType.CONVERSATIONAL_AGENT).lower()
    assert "claude" in route(TaskType.DEEP_REASONING).lower()


def test_active_provider_defaults_to_claude_when_env_unset():
    assert active_provider() == Provider.CLAUDE


def test_active_provider_reads_llm_provider_env_var(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert active_provider() == Provider.GEMINI

    monkeypatch.setenv("LLM_PROVIDER", "GROQ")  # case-insensitive
    assert active_provider() == Provider.GROQ


def test_active_provider_falls_back_to_claude_on_garbage_value(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "chatgpt")  # not a supported provider
    assert active_provider() == Provider.CLAUDE


def test_route_follows_llm_provider_env_var_for_switchable_tasks(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert "gemini" in route(TaskType.CONVERSATIONAL_AGENT).lower()
    assert "gemini" in route(TaskType.DEEP_REASONING).lower()
    assert "gemini" in route(TaskType.FAST_CLASSIFICATION).lower()

    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert route(TaskType.CONVERSATIONAL_AGENT) == "openai/gpt-oss-120b"
    assert route(TaskType.DEEP_REASONING) == "qwen/qwen3.6-27b"
    assert route(TaskType.FAST_CLASSIFICATION) == "openai/gpt-oss-20b"


def test_route_explicit_provider_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert "claude" in route(TaskType.CONVERSATIONAL_AGENT, provider=Provider.CLAUDE).lower()


def test_extraction_crosscheck_ignores_provider_switch(monkeypatch):
    """The crosscheck task stays on the open-weight model regardless of
    LLM_PROVIDER -- see router.py's module docstring for why."""
    claude_default = route(TaskType.EXTRACTION_CROSSCHECK)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    assert route(TaskType.EXTRACTION_CROSSCHECK) == claude_default
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert route(TaskType.EXTRACTION_CROSSCHECK) == claude_default


def test_every_provider_has_every_switchable_task_routed():
    switchable_tasks = [t for t in TaskType if t not in OSS_TASKS]
    for provider in Provider:
        for task in switchable_tasks:
            model = route(task, provider=provider)
            assert isinstance(model, str) and model


# --------------------------------------------------------------------
# Tier selector (Basic/Medium/Advanced -> Groq/Gemini/Claude)
# --------------------------------------------------------------------

def test_tier_to_provider_mapping_matches_stated_basic_medium_advanced():
    assert provider_for_tier(Tier.BASIC) == Provider.GROQ
    assert provider_for_tier(Tier.MEDIUM) == Provider.GEMINI
    assert provider_for_tier(Tier.ADVANCED) == Provider.CLAUDE


def test_provider_for_tier_accepts_plain_strings_too():
    """The API route receives tier as a plain string from JSON/form data,
    not a Tier enum instance -- this must work directly, not require the
    caller to construct Tier(...) first."""
    assert provider_for_tier("basic") == Provider.GROQ
    assert provider_for_tier("medium") == Provider.GEMINI
    assert provider_for_tier("advanced") == Provider.CLAUDE


def test_provider_for_tier_raises_on_invalid_value():
    with pytest.raises(ValueError):
        provider_for_tier("expert")
    with pytest.raises(ValueError):
        provider_for_tier("")


def test_provider_to_tier_is_the_exact_inverse_mapping():
    for tier, provider in TIER_TO_PROVIDER.items():
        assert PROVIDER_TO_TIER[provider] == tier
    # Every Provider has exactly one corresponding Tier -- no gaps, no
    # provider left without a user-facing tier label.
    assert set(PROVIDER_TO_TIER.keys()) == set(Provider)
