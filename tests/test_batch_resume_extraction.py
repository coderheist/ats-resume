import asyncio

from app.core.llm.batch_resume_extraction import (
    BacklogResume,
    build_classification_batch_requests,
    run_crosscheck_concurrently,
    submit_classification_batch,
)
from app.core.llm.claude_client import FakeAnthropicClient
from app.core.llm.oss_extraction_client import FakeOSSExtractionClient


def _backlog():
    return [
        BacklogResume("resume_1", "# Jane Doe\nSoftware Engineer at Acme..."),
        BacklogResume("resume_2", "# John Roe\nData Scientist at Beta Corp..."),
    ]


def test_classification_batch_requests_share_cached_instructions():
    requests = build_classification_batch_requests(_backlog())
    assert len(requests) == 2
    system_texts = {r.system[0]["text"] for r in requests}
    assert len(system_texts) == 1  # identical instructions across the whole backlog
    assert all(r.system[0]["cache_control"] == {"type": "ephemeral"} for r in requests)


def test_classification_batch_custom_ids_match_resume_ids():
    requests = build_classification_batch_requests(_backlog())
    assert [r.custom_id for r in requests] == ["resume_1", "resume_2"]


def test_submit_classification_batch_end_to_end():
    client = FakeAnthropicClient()
    batch_id = submit_classification_batch(client, _backlog())
    assert client.get_batch_status(batch_id)["processing_status"] == "ended"
    results = client.retrieve_batch_results(batch_id)
    assert {r["custom_id"] for r in results} == {"resume_1", "resume_2"}


def test_crosscheck_concurrent_success_path():
    client = FakeOSSExtractionClient()
    client.next_content = (
        '{"candidate_years_experience": 5, "most_recent_title": "Engineer", "skills": ["python"]}'
    )
    results = asyncio.run(run_crosscheck_concurrently(client, _backlog()))
    assert len(results) == 2
    assert all(r.succeeded for r in results)
    assert {r.resume_id for r in results} == {"resume_1", "resume_2"}
    assert results[0].extracted["most_recent_title"] == "Engineer"
    # both resumes were actually sent to the fake client
    assert len(client.calls) == 2


def test_crosscheck_handles_malformed_json_gracefully():
    client = FakeOSSExtractionClient()
    client.next_content = "not valid json"
    results = asyncio.run(run_crosscheck_concurrently(client, _backlog()))
    assert all(not r.succeeded for r in results)
    assert all(r.error is not None for r in results)


def test_crosscheck_respects_max_in_flight_without_deadlocking():
    """Not a timing assertion (too flaky) -- just confirms bounding
    concurrency doesn't break correctness on a backlog larger than the
    cap."""
    client = FakeOSSExtractionClient()
    client.next_content = '{"candidate_years_experience": 1, "most_recent_title": "x", "skills": []}'
    backlog = [BacklogResume(f"resume_{i}", f"doc {i}") for i in range(25)]
    results = asyncio.run(run_crosscheck_concurrently(client, backlog, max_in_flight=3))
    assert len(results) == 25
    assert all(r.succeeded for r in results)
