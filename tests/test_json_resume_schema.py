import pytest
from pydantic import ValidationError

from app.schemas.json_resume import JsonResume


def test_project_highlights_accept_text_objects_not_just_plain_strings():
    """Regression test: this is the exact shape that produced a 422
    ("Input should be a valid string") before the fix -- Project.highlights
    is list[str], but Work.highlights uses {"text": ...} objects, and it's
    an easy shape to send by mistake since the two fields look identical."""
    resume = JsonResume.model_validate({
        "projects": [{
            "name": "Plant Disease Detector",
            "highlights": [
                {"text": "Trained a ResNet34 model, achieving 98% test accuracy."},
                {"text": "Built a responsive React interface."},
            ],
        }],
    })
    assert resume.projects[0].highlights == [
        "Trained a ResNet34 model, achieving 98% test accuracy.",
        "Built a responsive React interface.",
    ]


def test_project_highlights_still_accept_plain_strings():
    resume = JsonResume.model_validate({
        "projects": [{"name": "P", "highlights": ["Plain string highlight."]}],
    })
    assert resume.projects[0].highlights == ["Plain string highlight."]


def test_project_highlights_accept_mixed_shapes_in_one_list():
    resume = JsonResume.model_validate({
        "projects": [{
            "name": "P",
            "highlights": ["Plain string.", {"text": "Object-shaped."}],
        }],
    })
    assert resume.projects[0].highlights == ["Plain string.", "Object-shaped."]


def test_work_highlights_accept_plain_strings_not_just_text_objects():
    """Symmetric fix on the other field -- Work.highlights normally wants
    {"text": ...} objects, but a plain string list should work too, since
    an LLM/heuristic extractor won't always produce the object form."""
    resume = JsonResume.model_validate({
        "work": [{
            "name": "Acme", "position": "Engineer",
            "highlights": ["Did a thing.", {"text": "Did another thing."}],
        }],
    })
    assert [h.text for h in resume.work[0].highlights] == ["Did a thing.", "Did another thing."]


def test_all_text_still_works_after_normalization():
    resume = JsonResume.model_validate({
        "work": [{"name": "Acme", "position": "Engineer", "highlights": ["Shipped X."]}],
        "projects": [{"name": "P", "highlights": [{"text": "Built Y."}]}],
    })
    text = resume.all_text()
    assert "Shipped X." in text
    assert "Built Y." in text


def test_still_rejects_genuinely_invalid_highlight_shapes():
    """The fix normalizes the two known real-world shapes -- it shouldn't
    silently accept arbitrary garbage instead of the previous clear error."""
    with pytest.raises(ValidationError):
        JsonResume.model_validate({"projects": [{"name": "P", "highlights": [{"not_text": "oops"}]}]})
    with pytest.raises(ValidationError):
        JsonResume.model_validate({"work": [{"name": "A", "position": "B", "highlights": [42]}]})
