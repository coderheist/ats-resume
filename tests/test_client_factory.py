import os

import pytest

from app.core.llm.claude_client import AnthropicClient
from app.core.llm.client_factory import get_client_for
from app.core.llm.gemini_client import GeminiClient
from app.core.llm.groq_client import GroqClient
from app.core.llm.oss_extraction_client import OSSExtractionClient
from app.core.llm.router import Provider, TaskType


@pytest.fixture(autouse=True)
def _clear_llm_provider_env(monkeypatch):
    """Every test starts from the unset-env default (Claude) unless it
    sets LLM_PROVIDER itself."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)


def test_defaults_to_anthropic_when_env_unset():
    client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT)
    assert isinstance(client, AnthropicClient)
    assert "claude" in model.lower()


def test_env_var_switches_to_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT)
    assert isinstance(client, GeminiClient)
    assert "gemini" in model.lower()


def test_env_var_switches_to_groq(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    client, model = get_client_for(TaskType.FAST_CLASSIFICATION)
    assert isinstance(client, GroqClient)
    assert model == "openai/gpt-oss-20b"


def test_explicit_provider_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT, provider=Provider.GEMINI)
    assert isinstance(client, GeminiClient)
    assert "gemini" in model.lower()


def test_extraction_crosscheck_always_oss_regardless_of_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    client, model = get_client_for(TaskType.EXTRACTION_CROSSCHECK)
    assert isinstance(client, OSSExtractionClient)
    assert "claude" not in model.lower()
    assert "gemini" not in model.lower()


def test_invalid_provider_env_falls_back_to_claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-real-provider")
    client, model = get_client_for(TaskType.DEEP_REASONING)
    assert isinstance(client, AnthropicClient)
    assert "claude" in model.lower()
