"""
Explicit skill match component (0.3 weight in the hybrid score).

Production note (blueprint Section 4.2): this should be a domain-tuned spaCy
NER pipeline trained on HR/recruiting text. This module implements a
synonym-normalizing keyword matcher instead -- same *contract* (resume text,
JD text -> matched/missing skill sets), swappable for a real NER pipeline
without touching hybrid_score.py.
"""
from __future__ import annotations

import re

# A small starter canonical-skill map. In production this is backed by the
# ontology/knowledge graph described in blueprint Section "Modality 2" --
# this is deliberately just enough to demonstrate the synonym-collapsing
# behavior that plain keyword matching can't do (e.g. "software development"
# and "software engineering" collapsing to the same canonical skill).
CANONICAL_SKILLS: dict[str, str] = {
    "software development": "software_engineering",
    "software engineering": "software_engineering",
    "software engineer": "software_engineering",
    "deep learning": "neural_networks",
    "neural networks": "neural_networks",
    "neural network": "neural_networks",
    "machine learning": "machine_learning",
    "ml": "machine_learning",
    "natural language processing": "nlp",
    "nlp": "nlp",
    "c++": "cpp",
    "c#": "csharp",
    ".net": "dotnet",
    "react": "react",
    "reactjs": "react",
    "react.js": "react",
    "postgres": "postgresql",
    "postgresql": "postgresql",
    # -- expanded for the Semantic Fit spec's broader requirement
    # categories (cloud, databases, languages, frameworks, tools).
    # Languages
    "python": "python", "javascript": "javascript", "typescript": "typescript",
    "java": "java", "golang": "go", "go": "go",
    # Cloud
    "aws": "aws", "amazon web services": "aws",
    "azure": "azure", "microsoft azure": "azure",
    "gcp": "gcp", "google cloud": "gcp", "google cloud platform": "gcp",
    # Containers / infra
    "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes",
    "terraform": "terraform", "ci/cd": "ci_cd", "jenkins": "ci_cd",
    # Databases
    "mysql": "mysql", "mongodb": "mongodb", "nosql": "nosql",
    "redis": "redis", "sql": "sql",
    # Frameworks / libraries
    "django": "django", "flask": "flask", "spring": "spring",
    "node.js": "nodejs", "nodejs": "nodejs", "node": "nodejs",
    "vue": "vue", "vue.js": "vue", "angular": "angular",
    "tensorflow": "tensorflow", "pytorch": "pytorch",
    "pandas": "pandas", "numpy": "numpy",
    # APIs / tools
    "rest api": "rest_api", "restful api": "rest_api", "graphql": "graphql",
    "git": "git", "agile": "agile", "scrum": "agile",
    "tableau": "tableau", "excel": "excel",
}

_TOKEN_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+#.]*(?:\s[a-zA-Z0-9+#.]+){0,2}")


def _canonicalize(term: str) -> str:
    key = term.lower().strip()
    return CANONICAL_SKILLS.get(key, key)


def phrase_present(phrase: str, lowered_text: str) -> bool:
    """Word-boundary-aware phrase search. Plain substring matching (the
    original implementation) is fine for longer phrases but breaks down
    for short tokens like "go" or "ml" -- "go" is a substring of
    "algorithm", "ml" is a substring of "html". \b doesn't work cleanly on
    "c++"/"c#"/".net" (non-word characters at the boundary), so those keep
    a plain substring check; every other phrase gets a real word-boundary
    regex."""
    if re.search(r"[^a-zA-Z0-9\s]", phrase):
        return phrase in lowered_text
    return re.search(rf"\b{re.escape(phrase)}\b", lowered_text) is not None


def extract_canonical_skills(text: str, known_terms: list[str] | None = None) -> set[str]:
    """
    Extract canonical skill identifiers from free text.

    `known_terms` lets callers pass an explicit skills list (e.g. from the
    JSON Resume `skills[].keywords` field) so we're not solely relying on
    naive n-gram scanning of prose.
    """
    found: set[str] = set()
    lowered = text.lower()

    for phrase in CANONICAL_SKILLS:
        if phrase_present(phrase, lowered):
            found.add(_canonicalize(phrase))

    if known_terms:
        for term in known_terms:
            found.add(_canonicalize(term))

    return found


def skill_match_score(resume_text: str, resume_skills: list[str], jd_text: str) -> tuple[float, set[str], set[str]]:
    """
    Returns (score in [0,1], matched canonical skills, missing canonical skills)

    `missing` is what should be surfaced verbatim in the XAI "skill gaps"
    panel (blueprint Section 5).
    """
    resume_skill_set = extract_canonical_skills(resume_text, resume_skills)
    jd_skill_set = extract_canonical_skills(jd_text)

    if not jd_skill_set:
        return 1.0, resume_skill_set, set()

    matched = resume_skill_set & jd_skill_set
    missing = jd_skill_set - resume_skill_set
    score = len(matched) / len(jd_skill_set)
    return score, matched, missing
