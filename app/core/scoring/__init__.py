"""
Shared scoring engine architecture -- Phase 2 of the architecture plan.

The audit that led to this: "don't build two separate systems for JD
and non-JD scoring, share engines between them." Investigating found
that this was **already true in practice** -- the engines below are
already imported and used by both the JD-based path (hybrid_score.py,
screening_report.py) and the JD-less path (readiness.py) -- but nothing
made that sharing *visible*. A reader opening this package saw 12 files
with no indication which ones were foundational/shared versus which
were JD-specific or readiness-specific, and had to trace imports by
hand to find out (exactly what the paragraph below does once, here,
instead of every reader doing it themselves).

This is a documentation and import-surface change, not a file-moving
one: physically relocating already-correct, already-tested modules
would be pure churn risk (331 passing tests depend on these import
paths) for no behavioral difference. The engines were already shared
correctly; what was missing was a map.

Confirmed by tracing actual imports (not assumed):

    SHARED (used by both JD and non-JD paths)
    +-- content_quality.py    -- action-verb / quantified-metric / passive-
    |                            voice analysis. hybrid_score.py,
    |                            screening_report.py, AND readiness.py all
    |                            call analyze_content_quality() directly.
    +-- skill_extraction.py   -- canonical skill vocabulary + extraction.
                                 hybrid_score.py uses skill_match_score();
                                 screening_report.py uses
                                 extract_canonical_skills() +
                                 CANONICAL_SKILLS; readiness.py uses
                                 extract_canonical_skills() too, for role
                                 inference against its own ontology.

    CROSS-MODE REUSE (a JD-mode file calling a readiness.py function)
    readiness.py's structural_completeness_score() and
    format_issues_for() are called directly by screening_report.py
    (the JD-mode's "ATS readability" dimension) and by
    suggestion_engine.py -- readiness.py isn't only the standalone/
    no-JD entry point, it's also where the structural-completeness
    check *itself* lives, reused rather than reimplemented.

    JD-MODE SPECIFIC (no non-JD caller)
    embeddings.py (semantic similarity -- JD text vs. resume text has no
    equivalent without a JD to compare against), experience_match.py
    (requires a stated JD experience requirement to score against),
    education_match.py, seniority.py, project_relevance.py,
    jd_requirement_extractor.py, requirement_matching.py -- all
    inherently JD-comparison concepts.

    ORCHESTRATORS (compose the engines above into a final score)
    hybrid_score.py (Mode 1, the original 3-weight JD-match formula),
    screening_report.py (the 7-dimension Semantic Fit report,
    POST /score/full-report), readiness.py (Mode 2, JD-less readiness,
    POST /score/standalone), suggestion_engine.py (Top-5 Suggestions,
    mode-aware: with-JD vs. no-JD).

Nothing here changes how these modules are imported elsewhere --
`from app.core.scoring.content_quality import analyze_content_quality`
still works exactly as it did before, and every existing test still
imports that way. This is additive documentation of what already
existed, not a new required import convention.
"""
