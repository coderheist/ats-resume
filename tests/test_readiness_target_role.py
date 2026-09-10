"""
Caller-specified target role for the JD-less readiness score.

Role inference rests on two things that can each be wrong: how much the
parser managed to extract, and how well a fixed tech-scoped ontology
happens to describe this person. When a sparse parse yields only a
couple of canonical skills, several roles tie on the same generic ones
-- and the tie used to resolve, silently, to whichever role was declared
first in ROLE_ONTOLOGY. That is software_engineer, whose skill set
(python, sql, git) is the most generic in the file, which is how an AI
engineer's resume came back labelled a software engineer.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.scoring.readiness import (
    AVAILABLE_ROLES, ROLE_ONTOLOGY, coverage_for_role, score_standalone_readiness,
)
from app.main import app
from app.schemas.json_resume import JsonResume

# Deliberately sparse: an AI engineer whose resume text only surfaces the
# generic trio. This is the shape a weak parse produces, and the case
# where inference is least trustworthy.
SPARSE_AI_RESUME = {
    "basics": {"name": "Archit", "email": "a@example.com", "phone": "1", "summary": "AI Engineer."},
    "work": [{"name": "Lab", "position": "AI Engineer", "highlights": [
        {"text": "Wrote Python services versioned in Git, backed by SQL."},
    ]}],
    "education": [{"institution": "Uni", "area": "CS"}],
    "skills": [{"name": "Python"}],
}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sparse_resume():
    return JsonResume.model_validate(SPARSE_AI_RESUME)


class TestOntology:
    def test_ai_engineer_exists(self):
        """Its absence meant an AI engineer had no correct label available
        at all -- the closest was ml_engineer, and a sparse parse fell
        through to software_engineer instead."""
        assert "ai_engineer" in ROLE_ONTOLOGY

    def test_available_roles_is_sorted_and_complete(self):
        assert AVAILABLE_ROLES == sorted(ROLE_ONTOLOGY)

    def test_every_expected_skill_is_a_real_canonical_id(self):
        """An id here that no extractor can ever produce would silently
        depress coverage for that role and never match anything."""
        from app.core.scoring.skill_extraction import CANONICAL_SKILLS

        known = set(CANONICAL_SKILLS.values()) | set(CANONICAL_SKILLS)
        for role, expected in ROLE_ONTOLOGY.items():
            unknown = expected - known
            assert not unknown, f"{role} expects non-canonical skill ids: {sorted(unknown)}"


class TestTargetRole:
    def test_stated_role_is_used_verbatim(self, sparse_resume):
        result = score_standalone_readiness(sparse_resume, target_role="ai_engineer")
        assert result.inferred_role == "ai_engineer"
        assert result.role_source == "user_specified"

    def test_stated_role_beats_the_inferred_one(self, sparse_resume):
        """The whole point: inference on this resume produces something
        other than the role the candidate actually wants."""
        inferred = score_standalone_readiness(sparse_resume)
        stated = score_standalone_readiness(sparse_resume, target_role="ai_engineer")

        assert inferred.inferred_role != "ai_engineer"
        assert inferred.role_source == "inferred"
        assert stated.inferred_role == "ai_engineer"

    def test_stated_role_reports_the_real_gap(self, sparse_resume):
        """Inference picks whichever role this resume already matches, so
        it reports a flattering coverage against a role nobody asked
        about. Scoring against the stated role is what surfaces the
        actual missing skills."""
        stated = score_standalone_readiness(sparse_resume, target_role="ai_engineer")

        assert stated.skill_coverage_score < 0.5
        assert {"machine_learning", "pytorch", "tensorflow"} <= stated.missing_ontology_skills

    def test_omitting_it_preserves_the_old_behaviour(self, sparse_resume):
        result = score_standalone_readiness(sparse_resume)
        assert result.role_source == "inferred"
        assert result.inferred_role in ROLE_ONTOLOGY

    def test_unknown_role_raises_rather_than_falling_back(self, sparse_resume):
        """Silently inferring instead would answer a different question
        while looking like a successful request."""
        with pytest.raises(ValueError, match="astronaut"):
            score_standalone_readiness(sparse_resume, target_role="astronaut")

    def test_coverage_for_role_is_consistent_with_the_scorer(self, sparse_resume):
        missing, coverage = coverage_for_role(sparse_resume, "ai_engineer")
        scored = score_standalone_readiness(sparse_resume, target_role="ai_engineer")
        assert missing == scored.missing_ontology_skills
        assert coverage == scored.skill_coverage_score


class TestInferenceRanking:
    def test_a_tie_is_not_decided_by_declaration_order(self):
        """Regression guard for the actual bug. software_engineer is first
        in ROLE_ONTOLOGY and its skills are the most generic there, so a
        strict `overlap > best` comparison handed it every tie."""
        from app.core.scoring.readiness import _infer_role

        # "python" alone ties a large number of roles on one skill each.
        resume = JsonResume.model_validate({
            "basics": {"name": "X"},
            "work": [{"name": "Co", "position": "Dev", "highlights": [{"text": "Used Python daily."}]}],
            "education": [], "skills": [{"name": "Python"}],
        })
        role, _, coverage = _infer_role(resume)

        tied = [r for r, e in ROLE_ONTOLOGY.items() if "python" in e]
        assert len(tied) > 1, "this test is meaningless without a real tie"
        # Among equally-overlapping roles the tighter one wins, rather
        # than whichever happens to be declared first.
        assert coverage == max(1 / len(ROLE_ONTOLOGY[r]) for r in tied)

    def test_a_smaller_role_wins_on_equal_overlap(self):
        """3-of-5 is a better fit than 3-of-6; raw overlap alone could not
        tell them apart."""
        from app.core.scoring.readiness import _infer_role

        resume = JsonResume.model_validate({
            "basics": {"name": "X"},
            "work": [{"name": "Co", "position": "QA", "highlights": [
                {"text": "Python and SQL test automation, versioned in Git."},
            ]}],
            "education": [], "skills": [{"name": "Python"}, {"name": "SQL"}, {"name": "Git"}],
        })
        role, _, coverage = _infer_role(resume)

        # qa_engineer expects 5 skills and matches 3; software_engineer
        # expects 6 and also matches 3.
        assert role == "qa_engineer"
        assert coverage == pytest.approx(3 / 5)


class TestRolesEndpoint:
    def test_lists_every_role_with_its_expected_skills(self, client):
        body = client.get("/score/roles").json()
        ids = [r["id"] for r in body["roles"]]

        assert ids == AVAILABLE_ROLES
        assert "ai_engineer" in ids
        for row in body["roles"]:
            assert row["expected_skills"] == sorted(ROLE_ONTOLOGY[row["id"]])
            assert row["label"]

    def test_standalone_accepts_a_target_role(self, client):
        resp = client.post("/score/standalone", json={"resume": SPARSE_AI_RESUME, "target_role": "ai_engineer"})
        body = resp.json()

        assert resp.status_code == 200
        assert body["inferred_role"] == "ai_engineer"
        assert body["role_source"] == "user_specified"

    def test_unknown_role_is_a_400_naming_the_valid_ones(self, client):
        resp = client.post("/score/standalone", json={"resume": SPARSE_AI_RESUME, "target_role": "astronaut"})

        assert resp.status_code == 400
        # These are internal ids, not free text, so a rejection without
        # the list leaves no way to guess the right value.
        assert "ai_engineer" in resp.json()["detail"]
