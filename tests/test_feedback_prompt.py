from app.core.llm.claude_client import FakeAnthropicClient
from app.core.llm.feedback_prompt import (
    build_feedback_messages, build_feedback_system,
    generate_feedback_summary, template_feedback_summary,
    NO_JD_INSTRUCTIONS, WITH_JD_INSTRUCTIONS,
)
from app.core.scoring.suggestion_engine import Suggestion


def _sample_suggestions() -> list[Suggestion]:
    return [
        Suggestion(
            category="missing_skill",
            message='Add evidence of "machine learning" -- it\'s in the job description but not found anywhere in your resume.',
            target=None,
            estimated_impact=0.15,
            score_context="match_score",
        ),
        Suggestion(
            category="unquantified_bullet",
            message='Add a measurable result to your Database Administrator role: "Managed backups."',
            target="Database Administrator",
            estimated_impact=0.3,
            score_context="readability",
        ),
    ]


def test_build_feedback_system_picks_the_right_rubric():
    with_jd_blocks = build_feedback_system("with_jd")
    no_jd_blocks = build_feedback_system("no_jd")

    assert with_jd_blocks[-1]["text"] == WITH_JD_INSTRUCTIONS
    assert no_jd_blocks[-1]["text"] == NO_JD_INSTRUCTIONS
    assert "specific job" in WITH_JD_INSTRUCTIONS
    assert "not targeted a specific job" in NO_JD_INSTRUCTIONS


def test_build_feedback_messages_includes_jd_when_given():
    suggestions = _sample_suggestions()
    with_jd = build_feedback_messages(suggestions, jd_text="We need a backend engineer with React.")
    no_jd = build_feedback_messages(suggestions, jd_text=None)

    assert "Job description" in with_jd[0]["content"]
    assert "React" in with_jd[0]["content"]
    assert "Job description" not in no_jd[0]["content"]
    # Both include the ranked, factual suggestions -- the LLM shouldn't
    # have to infer what's wrong.
    assert "machine learning" in with_jd[0]["content"]
    assert "machine learning" in no_jd[0]["content"]


def test_generate_feedback_summary_calls_the_client_with_the_right_shape():
    client = FakeAnthropicClient()
    suggestions = _sample_suggestions()

    result = generate_feedback_summary(client, suggestions, mode="with_jd", jd_text="Backend role.", model="claude-x")

    assert result == "[fake response]"  # FakeAnthropicClient's fixed canned text
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "claude-x"
    assert call["messages"][0]["role"] == "user"
    assert "Backend role." in call["messages"][0]["content"]


def test_generate_feedback_summary_empty_suggestions_short_circuits_without_calling_client():
    client = FakeAnthropicClient()
    result = generate_feedback_summary(client, [], mode="no_jd")
    assert "good shape" in result.lower()
    assert client.calls == []


def test_template_feedback_summary_is_deterministic_and_needs_no_client():
    suggestions = _sample_suggestions()
    result = template_feedback_summary(suggestions)
    assert result == [s.message for s in suggestions]


def test_template_feedback_summary_empty_list_has_a_positive_message():
    result = template_feedback_summary([])
    assert len(result) == 1
    assert "good shape" in result[0].lower()
