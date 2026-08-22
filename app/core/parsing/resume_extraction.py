"""
Raw resume text -> structured JsonResume.

Two tiers, in preference order, orchestrated as a small LangGraph graph
(`_compiled_graph` near the bottom of this file) -- an LLM node, a
conditional edge that only continues to a heuristic fallback node if the
LLM node didn't produce a resume, and a heuristic node. This is a
genuinely natural fit for LangGraph (not a forced one): it's a two-step
pipeline with a real conditional branch already, previously just
hand-coded as sequential if-statements in `parse_resume_text` -- see that
function for the graph invocation.

1. LLM extraction (app/core/llm, TaskType.RESUME_EXTRACTION) -- far more
   reliable on real-world resume formatting (inconsistent section names,
   multi-line job headers, prose-style bullets). Which provider answers
   this is a per-request choice, not a fixed env var: pass `tier`
   ("basic" = Groq, "medium" = Gemini, "advanced" = Claude -- see
   router.py's Tier enum) to `parse_resume_text()`, and that request uses
   exactly that provider's key, regardless of what LLM_PROVIDER the
   process happens to be started with. This is deliberate: before tiers
   existed, this always used `active_provider()` (LLM_PROVIDER, defaulting
   to "claude"), so configuring a GEMINI_API_KEY or GROQ_API_KEY alone did
   nothing unless LLM_PROVIDER was *also* set to match -- a real, reported
   point of confusion this tier system fixes by making the provider
   explicit per call instead of inferred from an env var. Any failure
   here (no key configured, package not installed, network error, the
   model returning something that doesn't parse as the expected JSON)
   falls through to tier 2 -- the person uploading a resume should get a
   usable, if rougher, result, not a 500 -- but the specific reason is
   preserved in `ParsedResumeResult.warnings` (e.g. "no GEMINI_API_KEY
   configured for the 'medium' tier") rather than a generic message,
   precisely because "which env var is missing" used to be the confusing
   part.

2. Heuristic extraction (regex + section-header + bullet-line splitting,
   `_heuristic_extract` below) -- has no dependency on any API key or
   network access, so it's what runs when no tier/provider is available
   (or `prefer_llm=False`). It works reasonably on a "normal" single-
   column resume with conventional section headers (EXPERIENCE /
   EDUCATION / SKILLS / PROJECTS) and bulleted highlights. It will NOT
   reliably handle: multi-column layouts (text may interleave),
   unconventional section names, or resumes that put dates/company/
   position across an unusual line arrangement. This is a real, known
   limitation, not a bug to silently paper over -- `parse_method` and
   `warnings` in the API response exist specifically so the caller can
   show "this was a rough automated parse, please review" rather than
   presenting a heuristic guess with the same confidence as a verified
   LLM extraction.

Either tier's output goes through JsonResume.model_validate() before
being returned, so a caller never receives a malformed resume object --
worst case is a JsonResume with fewer fields filled in than a human would
have entered, never an invalid one.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, TypedDict

from pydantic import ValidationError

from app.core.llm.router import PROVIDER_TO_TIER, Provider, TaskType, Tier, active_provider, provider_for_tier
from app.schemas.json_resume import JsonResume

# --------------------------------------------------------------------
# Tier 1: LLM extraction
# --------------------------------------------------------------------

_PROVIDER_ENV_KEYS = {
    Provider.CLAUDE: "ANTHROPIC_API_KEY",
    Provider.GEMINI: "GEMINI_API_KEY",
    Provider.GROQ: "GROQ_API_KEY",
}

EXTRACTION_INSTRUCTIONS = """\
You extract structured data from resume text into a specific JSON shape.
Read the resume text the user provides and respond with ONLY a single JSON
object -- no markdown code fences, no commentary before or after -- matching
exactly this shape (omit a field, or use null/empty list, if the resume
doesn't contain that information -- never invent information):

{
  "basics": {"name": str|null, "label": str|null, "email": str|null,
             "phone": str|null, "summary": str|null, "location": str|null},
  "work": [{"name": str, "position": str, "start_date": str|null,
            "end_date": str|null, "highlights": [str, ...]}],
  "education": [{"institution": str, "area": str|null,
                 "study_type": str|null, "end_date": str|null}],
  "skills": [{"name": str, "keywords": [str, ...]}],
  "projects": [{"name": str, "description": str|null, "highlights": [str, ...]}]
}

Rules:
- "name" in work is the employer/company name; "position" is the job title.
- Dates: use whatever granularity the resume gives (e.g. "2021-03" or "Mar 2021"
  or just "2021"); use null for end_date on a current/present role.
- highlights are the bullet points under a role or project, one string each,
  with bullet markers/punctuation stripped -- not re-written or summarized.
- Group skills under a "name" that reflects how the resume grouped them (e.g.
  "Languages", "Frameworks") if it did; otherwise use one group named "Skills".
- Every string must be plain text with no markdown formatting.
"""


def _configured_api_key(provider: Provider) -> str | None:
    return os.environ.get(_PROVIDER_ENV_KEYS[provider])


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_via_llm(raw_text: str, provider: Provider) -> JsonResume | None:
    """Returns None (never raises) on any failure -- see module docstring
    on why this always falls through to the heuristic tier instead. Takes
    an explicit `provider` (resolved from a tier or an override -- see
    parse_resume_text) rather than reading active_provider() itself, so
    the caller's tier choice is exactly what gets used, not whatever
    LLM_PROVIDER the process happens to be started with."""
    if not _configured_api_key(provider):
        return None
    try:
        from app.core.llm.client_factory import get_client_for

        client, model = get_client_for(TaskType.RESUME_EXTRACTION, provider=provider)
        raw = client.create_message(
            model=model,
            system=EXTRACTION_INSTRUCTIONS,
            messages=[{"role": "user", "content": raw_text}],
            max_tokens=4096,
        )
        text = raw["content"][0]["text"]
        parsed = json.loads(_strip_code_fence(text))
        return JsonResume.model_validate(parsed)
    except Exception:  # noqa: BLE001 -- any failure here just falls back to heuristic
        return None


# --------------------------------------------------------------------
# Tier 2: heuristic extraction (no LLM, always available)
# --------------------------------------------------------------------

_SECTION_HEADERS = {
    "work": ("experience", "work experience", "professional experience",
             "employment history", "work history"),
    "education": ("education", "academic background"),
    "skills": ("skills", "technical skills", "core competencies", "technologies"),
    "projects": ("projects", "personal projects", "key projects", "academic projects"),
    "summary": ("summary", "objective", "professional summary", "about"),
}
_ALL_HEADER_STRINGS = {h for headers in _SECTION_HEADERS.values() for h in headers}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(\(?\+?\d[\d\-.\s()]{7,}\d)")
_LOCATION_RE = re.compile(r"\b([A-Z][a-zA-Z.\s]+,\s*[A-Z]{2})\b")
_BULLET_RE = re.compile(r"^\s*[•\-\*▪◦]\s*")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
_DATE_RANGE_RE = re.compile(
    rf"({_MONTH}\.?\s+\d{{4}}|\d{{4}})\s*(?:[-–—to]{{1,4}})\s*"
    rf"(Present|Current|{_MONTH}\.?\s+\d{{4}}|\d{{4}})",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_DEGREE_RE = re.compile(
    r"\b(Bachelor|Master|B\.?S\.?|M\.?S\.?|B\.?A\.?|M\.?A\.?|Ph\.?D\.?|Associate)\b",
    re.IGNORECASE,
)


def _clean_line(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def _find_sections(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Returns {canonical_section: (start_line_idx_after_header, end_line_idx)}
    plus a synthetic "header" entry for everything before the first
    recognized section (name/contact info/summary live there)."""
    header_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip().strip(":").lower()
        if not stripped or len(stripped) > 40:
            continue
        for canonical, variants in _SECTION_HEADERS.items():
            if stripped in variants:
                header_positions.append((i, canonical))
                break

    sections: dict[str, tuple[int, int]] = {}
    first_header_idx = header_positions[0][0] if header_positions else len(lines)
    sections["header"] = (0, first_header_idx)
    for idx, (start_idx, canonical) in enumerate(header_positions):
        end_idx = header_positions[idx + 1][0] if idx + 1 < len(header_positions) else len(lines)
        sections[canonical] = (start_idx + 1, end_idx)
    return sections


def _extract_basics(header_lines: list[str], full_text: str) -> dict:
    basics: dict = {}
    non_empty = [l.strip() for l in header_lines if l.strip()]
    for line in non_empty[:4]:
        if _EMAIL_RE.search(line) or _PHONE_RE.search(line):
            continue
        if "name" not in basics:
            basics["name"] = line
        elif "label" not in basics and len(line) < 60:
            basics["label"] = line
    email_match = _EMAIL_RE.search(full_text)
    if email_match:
        basics["email"] = email_match.group(0)
    phone_match = _PHONE_RE.search(" ".join(non_empty))
    if phone_match:
        basics["phone"] = phone_match.group(0).strip()
    location_match = _LOCATION_RE.search(" ".join(non_empty))
    if location_match:
        basics["location"] = location_match.group(1)
    return basics


def _split_entries(lines: list[str]) -> list[list[str]]:
    """Splits a section's lines into per-entry blocks, using a detected
    date range as the entry boundary (the one structural signal that's
    fairly consistent across resume templates for work/education).
    Looks back up to 2 lines before each date line, since a common
    template puts title and company on two separate lines above a
    standalone date line -- 1 line back would only catch a single-line
    "Title, Company" header, not that variant."""
    boundaries = [i for i, line in enumerate(lines) if _DATE_RANGE_RE.search(line)]
    if not boundaries:
        # No date ranges found -- fall back to blank-line-separated blocks.
        entries, current = [], []
        for line in lines:
            if not line.strip():
                if current:
                    entries.append(current)
                    current = []
            else:
                current.append(line)
        if current:
            entries.append(current)
        return entries

    entries = []
    prev_end = 0
    for i, b in enumerate(boundaries):
        start = max(prev_end, b - 2, 0)
        end = boundaries[i + 1] - 2 if i + 1 < len(boundaries) else len(lines)
        end = max(end, b + 1)
        entries.append(lines[start:end])
        prev_end = end
    return entries


def _split_position_company(header_line: str) -> tuple[str, str]:
    parts = re.split(r"\s*[,|]\s*| at | @ ", header_line, maxsplit=1)
    if len(parts) > 1:
        return parts[0].strip(), parts[1].strip()
    # A single unlabeled line is treated as the company name (matches the
    # common "Company\n<dates>" template) rather than guessed as a title.
    return "Unknown position", header_line.strip()


def _parse_work_entry(entry_lines: list[str]) -> dict | None:
    non_empty = [l for l in entry_lines if l.strip()]
    if not non_empty:
        return None
    date_line_idx = next((i for i, l in enumerate(non_empty) if _DATE_RANGE_RE.search(l)), None)
    if date_line_idx is None:
        return None

    date_match = _DATE_RANGE_RE.search(non_empty[date_line_idx])
    start_date, end_date = date_match.group(1), date_match.group(2)
    if end_date.lower() in ("present", "current"):
        end_date = None

    header_line = re.sub(_DATE_RANGE_RE, "", non_empty[date_line_idx]).strip(" ,|-\t")
    consumed = {date_line_idx}

    if header_line:
        # The date line itself carries the position/company text too
        # (e.g. "Software Engineer, Acme    Mar 2021 - Present").
        position, company = _split_position_company(header_line)
    else:
        # Dates sit on their own line -- look at up to 2 non-bullet,
        # non-date lines immediately above for a "Title" / "Company" pair.
        candidates: list[int] = []
        idx = date_line_idx - 1
        while (
            idx >= 0 and len(candidates) < 2
            and not _BULLET_RE.match(non_empty[idx])
            and not _DATE_RANGE_RE.search(non_empty[idx])
        ):
            candidates.insert(0, idx)
            idx -= 1
        consumed.update(candidates)
        candidate_lines = [non_empty[i].strip() for i in candidates]
        if len(candidate_lines) >= 2:
            position, company = candidate_lines[-2], candidate_lines[-1]
        elif len(candidate_lines) == 1:
            position, company = _split_position_company(candidate_lines[0])
        else:
            position, company = "Unknown position", "Unknown company"

    highlight_lines = [
        _clean_line(l) for i, l in enumerate(non_empty)
        if i not in consumed and _clean_line(l)
    ]
    return {
        "name": company or "Unknown company",
        "position": position or "Unknown position",
        "start_date": start_date,
        "end_date": end_date,
        "highlights": highlight_lines,
    }


def _parse_education_entry(entry_lines: list[str]) -> dict | None:
    non_empty = [l.strip() for l in entry_lines if l.strip()]
    if not non_empty:
        return None
    joined = "\n".join(non_empty)
    degree_match = _DEGREE_RE.search(joined)
    year_match = _YEAR_RE.search(joined)
    # Prefer "in <Area>" (e.g. "...in Computer Science") over "of <Area>"
    # ("Bachelor of Science in Computer Science" has both -- "in" is the
    # one that actually names the field of study; "of" alone would grab
    # everything from "of Science in Computer Science" instead).
    area_match = re.search(r"\bin\s+([A-Za-z][a-zA-Z\s]+?)(?=\n|$)", joined) or \
        re.search(r"\bof\s+([A-Za-z][a-zA-Z\s]+?)(?=\n|$)", joined)

    institution = next((l for l in non_empty if not _DEGREE_RE.search(l)), non_empty[0])
    return {
        "institution": institution,
        "area": area_match.group(1).strip() if area_match else None,
        "study_type": degree_match.group(0) if degree_match else None,
        "end_date": year_match.group(0) if year_match else None,
    }


def _parse_skills(lines: list[str]) -> list[dict]:
    skills: list[dict] = []
    generic: list[str] = []
    for line in lines:
        line = _clean_line(line)
        if not line:
            continue
        if ":" in line and len(line.split(":")[0]) < 30:
            label, rest = line.split(":", 1)
            keywords = [k.strip() for k in re.split(r"[,;/]", rest) if k.strip()]
            if keywords:
                skills.append({"name": label.strip(), "keywords": keywords})
                continue
        generic.extend(k.strip() for k in re.split(r"[,;/]", line) if k.strip())
    if generic:
        skills.append({"name": "Skills", "keywords": generic})
    return skills


def _parse_projects(lines: list[str]) -> list[dict]:
    entries = _split_entries_by_blank_or_header_line(lines)
    projects = []
    for entry_lines in entries:
        non_empty = [l for l in entry_lines if l.strip()]
        if not non_empty:
            continue
        header = non_empty[0].strip()
        name, description = header, None
        for sep in (" — ", " - ", " | ", ": "):
            if sep in header:
                name, description = header.split(sep, 1)
                name, description = name.strip(), description.strip()
                break
        highlights = [_clean_line(l) for l in non_empty[1:] if _clean_line(l)]
        projects.append({"name": name, "description": description, "highlights": highlights})
    return projects


def _split_entries_by_blank_or_header_line(lines: list[str]) -> list[list[str]]:
    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        is_bullet = bool(_BULLET_RE.match(line))
        is_blank = not line.strip()
        if is_blank:
            if current:
                entries.append(current)
                current = []
            continue
        if not is_bullet and current and any(_BULLET_RE.match(l) for l in current):
            # a new non-bullet line after we've already seen bullets in the
            # current block signals the start of the next project
            entries.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        entries.append(current)
    return entries


def _heuristic_extract(raw_text: str) -> JsonResume:
    lines = raw_text.splitlines()
    sections = _find_sections(lines)

    header_start, header_end = sections["header"]
    basics = _extract_basics(lines[header_start:header_end], raw_text)

    if "summary" in sections:
        s, e = sections["summary"]
        summary_text = " ".join(l.strip() for l in lines[s:e] if l.strip())
        if summary_text:
            basics["summary"] = summary_text

    work = []
    if "work" in sections:
        s, e = sections["work"]
        for entry_lines in _split_entries(lines[s:e]):
            parsed = _parse_work_entry(entry_lines)
            if parsed:
                work.append(parsed)

    education = []
    if "education" in sections:
        s, e = sections["education"]
        for entry_lines in _split_entries(lines[s:e]) or [lines[s:e]]:
            parsed = _parse_education_entry(entry_lines)
            if parsed:
                education.append(parsed)

    skills = []
    if "skills" in sections:
        s, e = sections["skills"]
        skills = _parse_skills(lines[s:e])

    projects = []
    if "projects" in sections:
        s, e = sections["projects"]
        projects = _parse_projects(lines[s:e])

    return JsonResume.model_validate({
        "basics": basics, "work": work, "education": education,
        "skills": skills, "projects": projects,
    })


# --------------------------------------------------------------------
# Public entry point -- orchestrated as a small LangGraph graph
# --------------------------------------------------------------------

@dataclass
class ParsedResumeResult:
    resume: JsonResume
    parse_method: str  # "llm" | "heuristic"
    warnings: list[str] = field(default_factory=list)


class _ExtractionState(TypedDict):
    raw_text: str
    provider: Provider | None  # None -> skip the LLM node, go straight to heuristic
    resume: JsonResume | None
    parse_method: str
    warnings: list[str]


def _llm_node(state: _ExtractionState) -> dict[str, Any]:
    provider = state["provider"]
    if provider is None:
        return {}
    resume = _extract_via_llm(state["raw_text"], provider)
    if resume is not None:
        return {"resume": resume, "parse_method": "llm"}

    if _configured_api_key(provider):
        warning = (
            "LLM-based extraction didn't succeed (see server logs) -- used a "
            "lower-accuracy automated parse instead. Please review the result below."
        )
    else:
        env_var = _PROVIDER_ENV_KEYS[provider]
        tier_name = PROVIDER_TO_TIER[provider].value
        warning = (
            f"No {env_var} configured for the '{tier_name}' tier ({provider.value}) -- "
            f"used a lower-accuracy automated parse instead. Set {env_var} in the "
            f"environment, or pick a different tier, and try again."
        )
    return {"warnings": [*state["warnings"], warning]}


def _heuristic_node(state: _ExtractionState) -> dict[str, Any]:
    try:
        resume = _heuristic_extract(state["raw_text"])
    except (ValidationError, Exception):  # noqa: BLE001 -- never fail the request
        return {
            "resume": JsonResume(), "parse_method": "heuristic",
            "warnings": [*state["warnings"],
                         "Automated parsing couldn't make sense of this document -- "
                         "please fill in the details manually."],
        }

    warnings = list(state["warnings"])
    if not resume.work and not resume.projects and not resume.education:
        warnings.append(
            "Couldn't confidently identify Experience/Education/Projects sections. "
            "This works best with resumes that use conventional section headers "
            "(Experience, Education, Skills, Projects) -- please review and edit "
            "the result below."
        )
    return {"resume": resume, "parse_method": "heuristic", "warnings": warnings}


def _after_llm_node(state: _ExtractionState) -> str:
    """The conditional edge: only fall through to the heuristic node if
    the LLM node didn't produce a resume (no provider selected, no key
    configured, or the call/parse failed)."""
    from langgraph.graph import END
    return END if state.get("resume") is not None else "heuristic"


def _build_extraction_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_ExtractionState)
    graph.add_node("llm", _llm_node)
    graph.add_node("heuristic", _heuristic_node)
    graph.add_edge(START, "llm")
    graph.add_conditional_edges("llm", _after_llm_node, {"heuristic": "heuristic", END: END})
    graph.add_edge("heuristic", END)
    return graph.compile()


_compiled_graph = _build_extraction_graph()


def parse_resume_text(
    raw_text: str,
    *,
    prefer_llm: bool = True,
    tier: Tier | str | None = None,
    provider: Provider | None = None,
) -> ParsedResumeResult:
    """The one function callers (the API route) should use. Always
    returns a valid JsonResume -- see module docstring for the two-tier
    fallback behavior and its known limitations.

    `tier` ("basic"/"medium"/"advanced", see router.py's Tier enum) is
    the per-request way to pick which provider answers the LLM tier --
    prefer this over `provider` from an API boundary, since it's what the
    frontend's tier selector sends and raises a clear ValueError on an
    invalid value (the route turns that into a 400). `provider` is for
    direct/internal callers that already have a resolved Provider. If
    neither is given, falls back to `active_provider()` (the LLM_PROVIDER
    env var) -- the pre-tier-selector default behavior, unchanged for
    callers that don't pass either.
    """
    if not raw_text or not raw_text.strip():
        return ParsedResumeResult(resume=JsonResume(), parse_method="heuristic", warnings=["No text to parse."])

    resolved_provider: Provider | None = None
    if prefer_llm:
        if tier is not None:
            resolved_provider = provider_for_tier(tier)  # raises ValueError on an invalid tier string
        else:
            resolved_provider = provider or active_provider()

    initial_state: _ExtractionState = {
        "raw_text": raw_text, "provider": resolved_provider,
        "resume": None, "parse_method": "heuristic", "warnings": [],
    }
    final_state = _compiled_graph.invoke(initial_state)
    return ParsedResumeResult(
        resume=final_state["resume"] or JsonResume(),
        parse_method=final_state["parse_method"],
        warnings=final_state["warnings"],
    )
