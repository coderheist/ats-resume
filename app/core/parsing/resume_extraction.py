"""
Raw resume text -> structured JsonResume.

Deterministic-first, orchestrated as a small LangGraph graph
(`_compiled_graph` near the bottom of this file): a heuristic node runs
first, a confidence gate (parse_confidence.py) decides whether the
result is good enough on its own, and an LLM node only runs as a
fallback when it isn't. This inverts an earlier version of this module,
which ran the LLM node first and only fell through to the heuristic on
failure -- meaning *every* upload cost an LLM call regardless of how
clean the resume was. Target: 0 LLM calls for the default free path,
LLM only for genuinely low-confidence parses or an explicitly requested
tier. See `_after_heuristic_node`'s docstring for the exact gate logic.

1. Heuristic extraction (regex + section-header + bullet-line splitting,
   `_heuristic_extract` below) -- runs first, always, no dependency on
   any API key or network access. It works reasonably on a "normal"
   single-column resume with conventional section headers (EXPERIENCE /
   EDUCATION / SKILLS / PROJECTS) and bulleted highlights. It will NOT
   reliably handle: multi-column layouts (text may interleave),
   unconventional section names, or resumes that put dates/company/
   position across an unusual line arrangement -- `compute_confidence()`
   is specifically what's meant to catch these cases and escalate,
   rather than silently returning a rough guess with false confidence.

2. LLM extraction (app/core/llm, TaskType.RESUME_EXTRACTION) -- the
   fallback, reached when confidence is below threshold, or when a
   caller explicitly requested a tier/provider (which always escalates,
   regardless of confidence -- an explicit request for LLM quality
   shouldn't be silently downgraded). Which provider answers this is a
   per-request choice, not a fixed env var: pass `tier` ("basic" = Groq,
   "medium" = Gemini, "advanced" = Claude -- see router.py's Tier enum)
   to `parse_resume_text()`, and that request uses exactly that
   provider's key, regardless of what LLM_PROVIDER the process happens
   to be started with. Any failure here (no key configured, package not
   installed, network error, the model returning something that doesn't
   parse as the expected JSON) keeps the heuristic result already
   computed in step 1 -- the person uploading a resume should get a
   usable result, not a 500 -- but the specific reason is preserved in
   `ParsedResumeResult.warnings` (e.g. "no GEMINI_API_KEY configured for
   the 'medium' tier") rather than a generic message.

Either path's output goes through JsonResume.model_validate() before
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
from app.core.parsing.parse_confidence import HIGH_CONFIDENCE_THRESHOLD, compute_confidence
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
        if "usage" in raw:
            from app.core.llm.token_pricing import record_llm_usage
            record_llm_usage(model, raw["usage"], provider=provider.value)
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
# MM/YYYY, MM-YYYY, MM.YYYY -- the exact format ATS guidance commonly
# recommends specifically because it's unambiguous, and a format the
# original regex below didn't recognize at all (only "Jan 2020"-style
# month names or a bare 4-digit year), which meant conventionally
# ATS-formatted resumes could score *worse* on heuristic-parse
# confidence than ones using prose-style dates -- backwards from intent.
_NUMERIC_MONTH_YEAR = r"(?:0?[1-9]|1[0-2])[/.\-]\d{4}"
_DATE_TOKEN = rf"(?:{_MONTH}\.?\s+\d{{4}}|{_NUMERIC_MONTH_YEAR}|\d{{4}})"
# Separator as a real alternation, not a character class -- `[-–—to]`
# (the original) puts "t" and "o" in separately as individual matchable
# characters, not the literal word "to"; harmless in that it still
# matched *a* character, but never actually validated "to" as a whole
# word the way the pattern's own name implied it did.
_DATE_SEP = r"(?:\s*[-–—]\s*|\s+to\s+)"
_DATE_RANGE_RE = re.compile(
    rf"({_DATE_TOKEN}){_DATE_SEP}(Present|Current|{_DATE_TOKEN})",
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


_MONTH_NUM = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _normalize_date_token(raw: str) -> str:
    """Whatever the date regex matched (a month name + year, numeric
    MM/YYYY, or a bare year) -> the canonical "YYYY-MM" or "YYYY" form
    the rest of the schema (JsonResume, experience_match.py's
    _parse_year_month) already expects. Normalizing once here, at
    extraction time, means every downstream consumer keeps working with
    one format instead of each separately having to handle every raw
    variant a resume might use -- experience_match.py's own date parser
    doesn't recognize "01/2020" and would silently drop the month back
    to January if handed that string unnormalized."""
    raw = raw.strip()
    numeric_match = re.match(r"(\d{1,2})[/.\-](\d{4})", raw)
    if numeric_match:
        month, year = numeric_match.groups()
        return f"{year}-{int(month):02d}"
    month_match = re.match(rf"({_MONTH})\.?\s+(\d{{4}})", raw, re.IGNORECASE)
    if month_match:
        month_name, year = month_match.groups()
        month_num = _MONTH_NUM.get(month_name[:3].lower())
        return f"{year}-{month_num}" if month_num else year
    year_match = re.match(r"\d{4}", raw)
    if year_match:
        return year_match.group(0)
    return raw  # the regex that produced `raw` guarantees one of the above matches


def _parse_work_entry(entry_lines: list[str]) -> dict | None:
    non_empty = [l for l in entry_lines if l.strip()]
    if not non_empty:
        return None
    date_line_idx = next((i for i, l in enumerate(non_empty) if _DATE_RANGE_RE.search(l)), None)
    if date_line_idx is None:
        return None

    date_match = _DATE_RANGE_RE.search(non_empty[date_line_idx])
    raw_start, raw_end = date_match.group(1), date_match.group(2)
    start_date = _normalize_date_token(raw_start)
    end_date = None if raw_end.lower() in ("present", "current") else _normalize_date_token(raw_end)

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
    # Which provider actually produced this result, or None when the
    # heuristic answered. This has to be reported back rather than left
    # for the caller to infer from what it *requested*: the confidence
    # gate can escalate to active_provider() on a request that named no
    # tier at all, so "what the caller asked for" and "what answered"
    # are genuinely different values on the default upload path. The
    # route used to reconstruct it from the requested tier and crashed
    # with AttributeError on exactly that path -- see
    # app/api/routes/resume.py.
    provider_used: Provider | None = None


class _ExtractionState(TypedDict):
    raw_text: str
    provider: Provider | None  # None -> the LLM fallback is never eligible, regardless of confidence
    force_llm: bool  # True when an explicit tier/provider was given -- skip the confidence gate entirely
    resume: JsonResume | None
    parse_method: str
    confidence: float
    warnings: list[str]
    provider_used: Provider | None  # set by _llm_node only when the LLM call actually succeeds


def _heuristic_node(state: _ExtractionState) -> dict[str, Any]:
    try:
        resume = _heuristic_extract(state["raw_text"])
    except (ValidationError, Exception):  # noqa: BLE001 -- never fail the request
        return {
            "resume": JsonResume(), "parse_method": "heuristic", "confidence": 0.0,
            "warnings": [*state["warnings"],
                         "Automated parsing couldn't make sense of this document -- "
                         "please fill in the details manually."],
        }

    confidence = compute_confidence(resume, state["raw_text"])
    warnings = list(state["warnings"])
    if not resume.work and not resume.projects and not resume.education:
        warnings.append(
            "Couldn't confidently identify Experience/Education/Projects sections. "
            "This works best with resumes that use conventional section headers "
            "(Experience, Education, Skills, Projects) -- please review and edit "
            "the result below."
        )
    return {"resume": resume, "parse_method": "heuristic", "confidence": confidence, "warnings": warnings}


def _llm_node(state: _ExtractionState) -> dict[str, Any]:
    """Fallback node -- only reached when the conditional edge decided the
    heuristic parse wasn't good enough (or an explicit tier/provider
    forced this path). If the LLM call succeeds, its result REPLACES the
    heuristic one (parse_method becomes "llm"); if it fails, the
    heuristic result already in state is kept as-is, with a warning
    explaining why extraction quality may be lower than ideal."""
    provider = state["provider"]
    if provider is None:
        return {}
    resume = _extract_via_llm(state["raw_text"], provider)
    if resume is not None:
        # Explicitly clear warnings (not just leave them unset): a
        # heuristic-specific caveat like "couldn't confidently identify
        # sections" was possibly already added to state by _heuristic_node
        # (which always runs first now, to compute confidence) -- that
        # warning no longer applies once the LLM result replaces the
        # heuristic one, and LangGraph's state merge would otherwise
        # silently carry it forward as a stale, confusing leftover.
        return {"resume": resume, "parse_method": "llm", "warnings": [], "provider_used": provider}

    if _configured_api_key(provider):
        warning = (
            "LLM-based extraction didn't succeed (see server logs) -- kept the "
            "automated parse instead. Please review the result below."
        )
    else:
        env_var = _PROVIDER_ENV_KEYS[provider]
        tier_name = PROVIDER_TO_TIER[provider].value
        warning = (
            f"No {env_var} configured for the '{tier_name}' tier ({provider.value}) -- "
            f"kept the automated parse instead. Set {env_var} in the "
            f"environment, or pick a different tier, and try again."
        )
    return {"warnings": [*state["warnings"], warning]}


def _after_heuristic_node(state: _ExtractionState) -> str:
    """
    The confidence gate -- this is the piece that didn't exist before:
    previously the only branch condition was "did the LLM node produce a
    resume" (an LLM-first design where the heuristic was purely a
    failure fallback). Now the heuristic runs first, and this decides
    whether it was good enough on its own:

    - No provider available at all (no tier/key configured) -> nothing
      to escalate to, stop here regardless of confidence.
    - force_llm (an explicit tier or provider was requested) -> always
      escalate, the caller asked for LLM quality specifically and
      shouldn't be silently downgraded to a heuristic result they didn't
      ask for.
    - Otherwise -> escalate only when confidence is below threshold.
    """
    from langgraph.graph import END

    if state["provider"] is None:
        return END
    if state["force_llm"]:
        return "llm"
    return END if state["confidence"] >= HIGH_CONFIDENCE_THRESHOLD else "llm"


def _build_extraction_graph():
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_ExtractionState)
    graph.add_node("heuristic", _heuristic_node)
    graph.add_node("llm", _llm_node)
    graph.add_edge(START, "heuristic")
    graph.add_conditional_edges("heuristic", _after_heuristic_node, {"llm": "llm", END: END})
    graph.add_edge("llm", END)
    return graph.compile()


_compiled_graph = _build_extraction_graph()


def parse_resume_text(
    raw_text: str,
    *,
    prefer_llm: bool = True,
    tier: Tier | str | None = None,
    provider: Provider | None = None,
) -> ParsedResumeResult:
    """The one function callers (the API route) should use.

    Deterministic-first: the heuristic parser always runs first (no cost,
    no network, no key required), and a confidence score decides whether
    an LLM call is even worth making -- see parse_confidence.py and
    _after_heuristic_node's docstring above. This inverts the previous
    LLM-first design, where the heuristic only ran when the LLM call
    failed; that meant *every* upload cost an LLM call regardless of how
    clean the resume was. Target architecture: 0 LLM calls for the
    default free path, LLM only for genuinely low-confidence parses.

    `tier` ("basic"/"medium"/"advanced") or `provider` (see below) are
    treated as an explicit request for LLM quality -- passing either
    skips the confidence gate entirely and always escalates, since a
    caller who explicitly asked for a specific tier shouldn't be
    silently downgraded to a heuristic-only result they didn't ask for.

    `prefer_llm=False` (unchanged meaning): heuristic-only, the LLM
    fallback is never eligible regardless of confidence -- for callers
    that explicitly don't want any LLM cost at all, e.g. a "basic/free"
    UI path with a hard guarantee.

    `provider` is for direct/internal callers that already have a
    resolved Provider; `tier` is what the frontend's tier selector sends
    and raises a clear ValueError on an invalid value (the route turns
    that into a 400). If neither is given and prefer_llm=True (the
    default), the fallback provider is `active_provider()` (the
    LLM_PROVIDER env var), used only if the confidence gate actually
    triggers.
    """
    if not raw_text or not raw_text.strip():
        return ParsedResumeResult(resume=JsonResume(), parse_method="heuristic", warnings=["No text to parse."])

    force_llm = tier is not None or provider is not None
    resolved_provider: Provider | None = None
    if prefer_llm:
        if tier is not None:
            resolved_provider = provider_for_tier(tier)  # raises ValueError on an invalid tier string
        else:
            resolved_provider = provider or active_provider()

    initial_state: _ExtractionState = {
        "raw_text": raw_text, "provider": resolved_provider, "force_llm": force_llm,
        "resume": None, "parse_method": "heuristic", "confidence": 0.0, "warnings": [],
        "provider_used": None,
    }
    final_state = _compiled_graph.invoke(initial_state)
    return ParsedResumeResult(
        resume=final_state["resume"] or JsonResume(),
        parse_method=final_state["parse_method"],
        warnings=final_state["warnings"],
        provider_used=final_state.get("provider_used"),
    )
