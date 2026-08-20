"""
JSON Resume schema, implemented as Pydantic models.

Every layer of this application (parsing, scoring, the voice agent, exports)
reads and writes this schema exclusively. Nothing in the system edits a
rendered PDF/DOCX directly -- see Section 4.5 of the architecture blueprint.

Spec reference: https://jsonresume.org/schema/
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


def _normalize_highlight(item: Any) -> Any:
    """Accepts either a plain string or a `{"text": "..."}` object and
    normalizes to the object shape WorkHighlight expects.

    Real-world resume JSON (hand-written, LLM-extracted, or exported from
    another tool) is inconsistent about this -- some highlight lists are
    plain strings, some are objects carrying extra fields. Coercing here,
    once, means every producer of a JsonResume (the new file/text-paste
    parser included) doesn't have to match one exact shape, and callers
    downstream (readiness.py's `h.text` access) can keep assuming the
    object form unconditionally instead of type-checking at every call site.
    """
    if isinstance(item, str):
        return {"text": item}
    return item


class Basics(BaseModel):
    name: Optional[str] = None
    label: Optional[str] = None  # e.g. "Senior Full-Stack Engineer"
    email: Optional[str] = None
    phone: Optional[str] = None
    summary: Optional[str] = None
    location: Optional[str] = None


class WorkHighlight(BaseModel):
    text: str
    # Set by the scoring engine when a highlight is checked for quantified
    # impact -- used by the JD-less "readiness" scorer (Section 4.2/3, Mode 2).
    has_metric: Optional[bool] = None
    action_verb: Optional[str] = None


class Work(BaseModel):
    name: str  # company name
    position: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None  # None/omitted = current role
    highlights: list[WorkHighlight] = Field(default_factory=list)

    @field_validator("highlights", mode="before")
    @classmethod
    def _accept_plain_strings(cls, v: Any) -> Any:
        if isinstance(v, list):
            return [_normalize_highlight(item) for item in v]
        return v


class Education(BaseModel):
    institution: str
    area: Optional[str] = None
    study_type: Optional[str] = None  # e.g. "Bachelor"
    end_date: Optional[str] = None


class Skill(BaseModel):
    name: str  # canonical skill group, e.g. "Web Development"
    level: Optional[str] = None
    keywords: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: Optional[str] = None
    highlights: list[str] = Field(default_factory=list)

    @field_validator("highlights", mode="before")
    @classmethod
    def _accept_highlight_objects(cls, v: Any) -> Any:
        """Mirror image of Work._accept_plain_strings: Project.highlights
        is plain list[str] (see all_text() / class docstring), so a
        `{"text": ...}` object -- the shape Work.highlights uses, and an
        easy shape to send by mistake given the two fields look identical
        at a glance -- gets unwrapped to its string instead of raising."""
        if isinstance(v, list):
            return [
                item["text"] if isinstance(item, dict) and "text" in item else item
                for item in v
            ]
        return v


class JsonResume(BaseModel):
    """The canonical, structured record for one candidate resume."""

    schema_version: str = "v1.0.0"
    basics: Basics = Field(default_factory=Basics)
    work: list[Work] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)

    def all_text(self) -> str:
        """Flatten the resume into plain text for embedding / scoring.

        This is the single place that defines "what text represents this
        resume" -- every scoring module calls this rather than re-walking
        the schema, so the definition of "resume text" only lives once.
        """
        parts: list[str] = []
        if self.basics.summary:
            parts.append(self.basics.summary)
        for job in self.work:
            parts.append(f"{job.position} at {job.name}")
            parts.extend(h.text for h in job.highlights)
        for edu in self.education:
            parts.append(f"{edu.study_type or ''} {edu.area or ''} {edu.institution}")
        for skill in self.skills:
            parts.append(skill.name)
            parts.extend(skill.keywords)
        for proj in self.projects:
            if proj.description:
                parts.append(proj.description)
            parts.extend(proj.highlights)
        return "\n".join(p.strip() for p in parts if p and p.strip())

    def all_skill_keywords(self) -> set[str]:
        kws: set[str] = set()
        for skill in self.skills:
            kws.add(skill.name.lower())
            kws.update(k.lower() for k in skill.keywords)
        return kws
