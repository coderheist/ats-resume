"""
Project Relevance sub-score (Semantic Fit spec, scoring dimension #7).

How many of the JD's important skills are demonstrated specifically
inside the candidate's `projects[]` entries -- a JD-relevant side project
is real, additional evidence distinct from work-experience-based skill
matching.
"""
from __future__ import annotations

from app.core.scoring.skill_extraction import extract_canonical_skills
from app.schemas.json_resume import JsonResume


def project_relevance_score(resume: JsonResume, jd_skill_set: set[str]) -> tuple[float, list[str]]:
    """Returns (score in [0,1], names of projects that touch a JD skill).

    Score is normalized against min(project count, 3) rather than the
    full project count -- a candidate with 8 projects and 3 relevant ones
    shouldn't score worse than a candidate with exactly 3 projects, all
    relevant; both demonstrate the same thing (a handful of genuinely
    on-topic projects), and requiring *every* project to be JD-relevant
    would penalize a candidate for having a broad portfolio.
    """
    if not jd_skill_set:
        return 1.0, []
    if not resume.projects:
        return 0.0, []

    relevant_projects: list[str] = []
    for project in resume.projects:
        project_text = " ".join(filter(None, [project.description, *project.highlights]))
        project_skills = extract_canonical_skills(project_text)
        if project_skills & jd_skill_set:
            relevant_projects.append(project.name)

    denom = min(len(resume.projects), 3)
    score = min(1.0, len(relevant_projects) / denom) if denom else 0.0
    return score, relevant_projects
