from app.core.scoring.content_quality import analyze_content_quality, annotate_resume_with_quality_flags
from app.schemas.json_resume import JsonResume, Work, WorkHighlight


def _resume(highlights: list[str], position: str = "Database Administrator") -> JsonResume:
    return JsonResume(work=[Work(
        name="Acme", position=position,
        highlights=[WorkHighlight(text=t) for t in highlights],
    )])


def test_strong_verb_and_metric_bullet_has_no_issues():
    resume = _resume(["Reduced query latency by 40% across the primary cluster."])
    report = analyze_content_quality(resume)
    assert report.unquantified_bullets == []
    assert report.weak_verb_bullets == []
    assert report.passive_voice_bullets == []


def test_bullet_missing_metric_is_flagged_with_job_title():
    resume = _resume(["Reduced query latency across the primary cluster."])
    report = analyze_content_quality(resume)
    assert len(report.unquantified_bullets) == 1
    assert report.unquantified_bullets[0].job_title == "Database Administrator"


def test_bullet_with_weak_opener_is_flagged():
    resume = _resume(["Helped with the migration project."])
    report = analyze_content_quality(resume)
    assert len(report.weak_verb_bullets) == 1


def test_passive_voice_tell_phrase_detected():
    resume = _resume(["Was responsible for managing the on-call rotation."])
    report = analyze_content_quality(resume)
    assert len(report.passive_voice_bullets) == 1


def test_passive_be_verb_pattern_detected():
    resume = _resume(["The database was migrated to a new cluster in Q3."])
    report = analyze_content_quality(resume)
    assert len(report.passive_voice_bullets) == 1


def test_densities_computed_correctly_across_multiple_bullets():
    resume = _resume([
        "Led the migration of the ingestion pipeline, cutting latency 42%.",  # verb + metric
        "Helped with various backend tasks.",  # weak verb, no metric
    ])
    report = analyze_content_quality(resume)
    assert report.action_verb_density == 0.5
    assert report.quantified_metric_density == 0.5


def test_empty_resume_returns_zeroed_report():
    resume = JsonResume(work=[])
    report = analyze_content_quality(resume)
    assert report.bullet_issues == []
    assert report.action_verb_density == 0.0
    assert report.quantified_metric_density == 0.0


def test_annotate_resume_populates_previously_unused_schema_fields():
    resume = _resume(["Led the redesign of the billing service, cutting errors 30%.", "Helped out sometimes."])
    annotated = annotate_resume_with_quality_flags(resume)

    strong = annotated.work[0].highlights[0]
    weak = annotated.work[0].highlights[1]

    assert strong.has_metric is True
    assert strong.action_verb == "led"
    assert weak.has_metric is False
    assert weak.action_verb is None  # not a strong verb -> no verb recorded, per design


def test_annotate_resume_does_not_mutate_the_input():
    resume = _resume(["Led the redesign of the billing service, cutting errors 30%."])
    original_highlight = resume.work[0].highlights[0]
    assert original_highlight.has_metric is None  # schema default, unset

    annotate_resume_with_quality_flags(resume)

    # Original object's highlight must be untouched.
    assert resume.work[0].highlights[0].has_metric is None
