"""
Shared bullet-level content-quality analysis, used by both Mode 1
(hybrid_score.py, JD match) and Mode 2 (readiness.py, JD-less readiness) --
approved design: one module, both modes get full bullet-level detail.

This used to exist only inside readiness.py as an aggregate density
calculation (verb_density, metric_density) with no per-bullet detail.
Pulled out and made per-bullet because the Top-5 Suggestions engine
(suggestion_engine.py) needs to name exactly *which* bullet, on *which*
role, is missing a metric ("Add a measurable result to your Database
Administrator role") -- an aggregate ratio can't express that.

Also finally wires up JsonResume.WorkHighlight.has_metric / action_verb --
those fields have existed on the schema, with a comment saying "set by
the scoring engine", since the schema was written; nothing ever set them
until annotate_resume_with_quality_flags() below.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.json_resume import JsonResume, Work

STRONG_ACTION_VERBS = {
    "led", "built", "launched", "scaled", "designed", "architected",
    "reduced", "increased", "shipped", "drove", "optimized", "automated",
    "negotiated", "delivered", "spearheaded", "migrated", "implemented",
}

_METRIC_PATTERN = re.compile(r"\d")

# Lightweight heuristic, not a dependency parse -- same philosophy as the
# rest of this codebase's auditable-regex layer (skill_extraction.py,
# jd_bias_scanner.py, seniority.py): catches the common "be-verb + past
# participle" construction plus a short list of classic passive-voice
# tells. Swap for a real POS-tagger in production; see module docstrings
# throughout app/core/scoring/ for the established pattern of doing that.
_PASSIVE_BE_VERB_PATTERN = re.compile(r"\b(?:was|were|is|are|been|being)\s+\w+ed\b", re.IGNORECASE)

PASSIVE_TELL_PHRASES = {
    "was responsible for", "were responsible for", "was tasked with",
    "were tasked with", "was assigned", "were assigned", "was involved in",
    "were involved in", "was in charge of",
}


def _leads_with_strong_verb(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first_word = stripped.split(" ", 1)[0].lower().rstrip(".,;:")
    return first_word in STRONG_ACTION_VERBS


def _has_metric(text: str) -> bool:
    return bool(_METRIC_PATTERN.search(text))


def _is_passive_voice(text: str) -> bool:
    lowered = text.lower()
    if any(phrase in lowered for phrase in PASSIVE_TELL_PHRASES):
        return True
    return bool(_PASSIVE_BE_VERB_PATTERN.search(text))


@dataclass
class BulletIssue:
    """One work-highlight's quality flags, tagged with which role it
    belongs to and its position in resume.work[], so downstream feedback
    can both name it in prose and patch it back precisely if needed."""

    job_title: str
    highlight_text: str
    has_metric: bool
    leads_with_strong_verb: bool
    is_passive_voice: bool
    work_index: int
    highlight_index: int


@dataclass
class ContentQualityReport:
    bullet_issues: list[BulletIssue] = field(default_factory=list)
    action_verb_density: float = 0.0
    quantified_metric_density: float = 0.0
    passive_voice_count: int = 0

    @property
    def unquantified_bullets(self) -> list[BulletIssue]:
        return [b for b in self.bullet_issues if not b.has_metric]

    @property
    def weak_verb_bullets(self) -> list[BulletIssue]:
        return [b for b in self.bullet_issues if not b.leads_with_strong_verb]

    @property
    def passive_voice_bullets(self) -> list[BulletIssue]:
        return [b for b in self.bullet_issues if b.is_passive_voice]


def analyze_content_quality(resume: JsonResume) -> ContentQualityReport:
    issues: list[BulletIssue] = []
    for work_index, job in enumerate(resume.work):
        job_title = job.position or job.name or "an unlabeled role"
        for highlight_index, highlight in enumerate(job.highlights):
            text = highlight.text
            issues.append(
                BulletIssue(
                    job_title=job_title,
                    highlight_text=text,
                    has_metric=_has_metric(text),
                    leads_with_strong_verb=_leads_with_strong_verb(text),
                    is_passive_voice=_is_passive_voice(text),
                    work_index=work_index,
                    highlight_index=highlight_index,
                )
            )

    n = len(issues)
    if n == 0:
        return ContentQualityReport()

    return ContentQualityReport(
        bullet_issues=issues,
        action_verb_density=sum(1 for b in issues if b.leads_with_strong_verb) / n,
        quantified_metric_density=sum(1 for b in issues if b.has_metric) / n,
        passive_voice_count=sum(1 for b in issues if b.is_passive_voice),
    )


def annotate_resume_with_quality_flags(resume: JsonResume) -> JsonResume:
    """
    Returns a new JsonResume with WorkHighlight.has_metric / action_verb
    populated, per the schema's original intent. Does not mutate the
    input -- same immutable-update pattern as voice_agent/gap_resolution.py.

    action_verb is only populated with the leading word when it's a
    *strong* one -- matches the field's evident intent (naming which verb
    was used); a bullet that doesn't lead with a strong verb doesn't have
    "a" action verb worth recording, it has a gap, which shows up in
    ContentQualityReport.weak_verb_bullets instead.
    """
    new_work: list[Work] = []
    for job in resume.work:
        new_highlights = []
        for highlight in job.highlights:
            text = highlight.text
            stripped = text.strip()
            first_word = stripped.split(" ", 1)[0].lower().rstrip(".,;:") if stripped else None
            new_highlights.append(
                highlight.model_copy(
                    update={
                        "has_metric": _has_metric(text),
                        "action_verb": first_word if _leads_with_strong_verb(text) else None,
                    }
                )
            )
        new_work.append(job.model_copy(update={"highlights": new_highlights}))
    return resume.model_copy(update={"work": new_work})
