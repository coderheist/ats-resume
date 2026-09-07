"""
Confidence scoring for the deterministic (heuristic) resume parse --
the piece the target architecture's diagram calls for that didn't exist
before this: a real "is this good enough, or should we escalate to an
LLM" check, rather than the previous all-or-nothing "did the LLM
succeed" branch.

Five auditable signals, each worth a fixed share of the total -- not a
black box, and not ML-based (nothing here needs training data or is
itself an LLM call, which would defeat the point of a *cheap* gate
that runs before deciding whether an LLM call is warranted):

  - Contact info found (email or phone)                        0.15
  - At least one structural section found                       0.20
  - Most work entries have both a position and a start date      0.25
  - At least one work highlight/bullet was extracted at all       0.20
  - Extracted structure isn't tiny relative to the raw text        0.20
    (protects against a parse that "succeeded" on paper but only
    captured a fragment of a much longer document -- a real failure
    mode of header/bullet-line heuristics on unconventional layouts)

HIGH_CONFIDENCE_THRESHOLD is intentionally conservative (requires
several positive signals, not just one) -- a wrong parse silently
shown to a user is worse than one extra LLM call, so this errs toward
escalating when genuinely uncertain rather than maximizing the
0-LLM-calls count at the expense of accuracy.
"""
from __future__ import annotations

from app.schemas.json_resume import JsonResume

HIGH_CONFIDENCE_THRESHOLD = 0.7


def compute_confidence(resume: JsonResume, raw_text: str) -> float:
    score = 0.0

    if resume.basics.email or resume.basics.phone:
        score += 0.15

    if resume.work or resume.education or resume.skills:
        score += 0.20

    if resume.work:
        with_position = sum(1 for w in resume.work if w.position)
        with_date = sum(1 for w in resume.work if w.start_date)
        if with_position / len(resume.work) >= 0.5 and with_date / len(resume.work) >= 0.5:
            score += 0.25

    total_highlights = sum(len(w.highlights) for w in resume.work)
    if total_highlights > 0:
        score += 0.20

    if raw_text:
        extracted_chars = len(resume.all_text())
        if extracted_chars / len(raw_text) > 0.25:
            score += 0.20

    return round(min(score, 1.0), 3)


def is_high_confidence(resume: JsonResume, raw_text: str) -> bool:
    return compute_confidence(resume, raw_text) >= HIGH_CONFIDENCE_THRESHOLD
