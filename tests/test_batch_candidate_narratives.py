from app.core.llm.batch_candidate_narratives import (
    CandidateScoreInput,
    build_narrative_batch_requests,
    parse_narrative_batch_results,
    run_candidate_pool_narratives,
)
from app.core.llm.claude_client import FakeAnthropicClient


def _sample_candidates():
    return [
        CandidateScoreInput("cand_1", {"score": 82.0, "matched_skills": ["python", "react"]}),
        CandidateScoreInput("cand_2", {"score": 41.0, "matched_skills": ["react"]}),
        CandidateScoreInput("cand_3", {"score": 95.0, "matched_skills": ["python", "react", "aws"]}),
    ]


def test_every_request_shares_identical_cached_jd_prefix():
    """This is the entire cost-saving mechanism for this module: every
    candidate's request must carry the byte-identical system prefix so
    the batch's cache write happens once, not N times."""
    requests = build_narrative_batch_requests(
        jd_text="Senior backend engineer, Python + AWS.",
        candidates=_sample_candidates(),
    )
    assert len(requests) == 3
    system_texts = {r.system[0]["text"] for r in requests}
    assert len(system_texts) == 1  # identical across every request
    assert "Senior backend engineer" in next(iter(system_texts))
    for r in requests:
        assert r.system[0]["cache_control"] == {"type": "ephemeral"}


def test_custom_id_matches_candidate_id_for_joinability():
    requests = build_narrative_batch_requests(
        jd_text="JD text", candidates=_sample_candidates(),
    )
    assert [r.custom_id for r in requests] == ["cand_1", "cand_2", "cand_3"]


def test_per_candidate_message_contains_only_that_candidates_data():
    requests = build_narrative_batch_requests(jd_text="JD", candidates=_sample_candidates())
    assert "cand_1" not in requests[1].messages[0]["content"]
    assert "82.0" in requests[0].messages[0]["content"]
    assert "41.0" in requests[1].messages[0]["content"]


def test_end_to_end_with_fake_client():
    client = FakeAnthropicClient()
    client.next_usage = {
        "input_tokens": 20, "output_tokens": 80,
        "cache_creation_input_tokens": 400, "cache_read_input_tokens": 0,
    }
    batch_id = run_candidate_pool_narratives(
        client, jd_text="Senior backend role", candidates=_sample_candidates(),
    )
    status = client.get_batch_status(batch_id)
    assert status["processing_status"] == "ended"

    raw_results = client.retrieve_batch_results(batch_id)
    narratives = parse_narrative_batch_results(raw_results)
    assert len(narratives) == 3
    assert all(n.succeeded for n in narratives)
    assert all(n.narrative == "[fake batch response]" for n in narratives)


def test_parse_handles_a_failed_entry_without_crashing():
    raw_results = [
        {"custom_id": "cand_1", "result": {"type": "succeeded",
         "message": {"content": [{"type": "text", "text": "Strong fit on Python."}]}}},
        {"custom_id": "cand_2", "result": {"type": "errored",
         "error": {"message": "rate_limited"}}},
    ]
    parsed = parse_narrative_batch_results(raw_results)
    assert parsed[0].succeeded and parsed[0].narrative == "Strong fit on Python."
    assert not parsed[1].succeeded
    assert parsed[1].error == "rate_limited"
