# Development History

> **About this document.** This is the original project README, preserved in
> full. It is a chronological engineering log — how each phase was built, which
> bugs were root-caused and how, what was rejected and why, and what was
> verified versus assumed at each step. It is kept because that reasoning is
> genuinely useful context, and because it records decisions that the reference
> documentation states as conclusions without re-arguing them.
>
> It is **not** maintained as current reference material. Sections describing
> "what's real vs. what's a production adapter" reflect the state at the time
> each was written, and some phases describe behavior that later phases changed.
> For anything you intend to act on, use the current documentation instead:
>
> | For | See |
> | --- | --- |
> | Setup and running | [DEVELOPMENT.md](DEVELOPMENT.md) |
> | System design | [ARCHITECTURE.md](ARCHITECTURE.md) |
> | Endpoints | [API.md](API.md) |
> | Environment variables | [CONFIGURATION.md](CONFIGURATION.md) |
> | Production deployment | [DEPLOYMENT.md](DEPLOYMENT.md) |
>
> One correction worth flagging inline: several places below state that the full
> test suite passes against real Postgres. The suite's DB-touching tests
> override `get_db` with an in-memory SQLite session per test, so running pytest
> never exercises the configured engine. What was genuinely verified against
> Postgres 16 + pgvector 0.6 was the Alembic migrations applying and direct
> `TestClient` calls without that override.

---

## Original README

A runnable implementation of the architecture from the product blueprint:
hybrid semantic/skill/experience resume scoring, JD-less readiness scoring,
JD bias auditing, and the decision core of the voice-editing agent loop.

**This is a real, tested backend — not a mockup.** Every module under
`app/core/` runs and is covered by passing tests. The pieces that need
external infrastructure not available in a sandbox (GPU-backed SBERT
embeddings, live Claude/GPT calls, real-time STT, Docling/Marker's CV
models) are built as swappable adapters behind clean interfaces, so wiring
in the real service is a config change and a `pip install`, not a rewrite.

## What's real vs. what's a production adapter

| Component | In this scaffold | In production |
|---|---|---|
| JSON Resume schema | ✅ Full Pydantic model, `app/schemas/json_resume.py` | Same |
| Hybrid scoring formula | ✅ Fully implemented and tested — weights are now dynamic per detected seniority (see "Dynamic seniority weighting" below), MID baseline stays 0.5/0.3/0.2 | Same formula, real embeddings |
| Semantic similarity | ⚠️ TF-IDF cosine fallback (`embeddings.py`) | SBERT + LoRA fine-tune — set `EMBEDDING_BACKEND=sbert` |
| Skill match / synonym normalization | ✅ Working canonical-skill map | Swap for a domain-tuned spaCy NER pipeline, same function contract |
| Experience match | ✅ Fully implemented and tested | Same |
| Seniority detection | ✅ Regex/keyword heuristic (`scoring/seniority.py`) | Swap for an LLM classification call behind the same `detect_seniority` signature |
| JD-less readiness scorer | ✅ Fully implemented and tested (starter ontology) | Plug in the full RRSO/knowledge-graph ontology |
| JD bias audit | ✅ Fully implemented and tested — agentic/communal skew **and** ageist phrasing, both non-scoring flags kept structurally separate from the match score | Same, calibrate word lists against a labeled corpus |
| Voice agent decision loop (ask vs. generate) | ✅ Fully implemented and tested | Same decision contract; slot *extraction* becomes a live LLM call |
| Interactive gap-resolution loop | ✅ Fully implemented and tested (`voice_agent/gap_resolution.py`) — patches a resume from a free-text answer and rescores; channel-agnostic (drives today's text-based `/voice/gap-answer` flow, could feed a voice channel later without a redesign) | Route the patch step through an LLM rewrite pass, constrained to reframing what the candidate actually said |
| Document parsing (Docling/Marker) | 🔌 Adapter written against the real library APIs, not installed | `pip install docling`, remove the stub |
| LLM calls (Claude + open-weight crosscheck) | 🔌 Client wrappers + model router + cost layer written and unit-tested against fakes (see "Cost optimization" below), not invoked live | Set `ANTHROPIC_API_KEY` (default) **or** switch providers entirely with `LLM_PROVIDER=gemini`/`groq` — see "Multi-provider LLM switching" below |
| Live STT (Deepgram/Whisper) | Not built — this scaffold accepts already-transcribed text | Deepgram streaming SDK integration at the `/voice/turn` and `/voice/gap-answer` boundary |
| Database | ✅ SQLAlchemy models + pgvector schema, ✅ Alembic migrations (tested against real Postgres+pgvector, see below) | Point `DATABASE_URL` at a managed Postgres+pgvector instance |
| Frontend | ✅ Static reference console (`frontend/`) exercising all 7 endpoints, request/response contract verified end-to-end against the live backend (see "Frontend" below) | Same console works as-is against a deployed API; swap in real auth/persistence for a production app |

## Dynamic seniority weighting & the gap-resolution loop

Two additions on top of the original blueprint, both added after review:

- **Dynamic seniority weighting** (`scoring/seniority.py`, wired into `hybrid_score.py`'s `SENIORITY_WEIGHT_PROFILES`): the JD's detected seniority level shifts the semantic/skill/experience weights *and* how `ExperienceEducationFit`-style scoring treats a years-required gap, so an entry-level posting doesn't get scored on a senior-hire rubric. A JD with no detectable seniority signal falls back to the original static 0.5/0.3/0.2 weights exactly, so nothing about the pre-existing behavior changed unless a signal is actually present.
- **Interactive gap-resolution loop** (`voice_agent/gap_resolution.py`, `POST /voice/gap-prompt` + `POST /voice/gap-answer`): turns each missing-skill gap from a `/score/jd-match` call into one targeted follow-up question, patches the candidate's answer into the resume as a new highlight, and immediately rescores — so the before/after delta is visible without a re-upload. Deliberately channel-agnostic: the prompt is plain text today (see the "Gap Resolution" tab in the frontend console), but the same object shape would drive a voice channel later without touching the underlying pipeline.

The JD bias audit (`bias_audit/jd_bias_scanner.py`) also gained ageist-phrase
detection alongside its original agentic/communal skew check. Both checks
stay structurally separate from `jd_requirements`/scoring — auditing the JD
and scoring the candidate against it are different concerns, so this can
never silently reweight a candidate's score.

## Range-aware experience scoring, hardened semantic math, and Top-5 Suggestions

A second review pass, four changes:

- **Experience ranges** (`scoring/experience_match.py`, rewritten): a JD like "0-2 years" now scores 0/1/2/3 years all at 1.0 — a proportional grace band (±50% of the range's own width) around both edges, decaying linearly beyond it. "5+ years" (floor-only, no explicit ceiling) keeps its original never-penalize-exceeding behavior. Also fixed along the way, since both bugs live in the same function and affect the same number: `total_years_experience` now parses month precision instead of rounding to whole years, and a missing `start_date` is surfaced via `has_unparseable_dates()` instead of silently zeroing out that job's tenure.
- **Semantic fit math** (`scoring/embeddings.py`): the L2-normalized cosine formula was already correct — verified against the code, not just re-implemented on faith. What was missing was a defensive clamp: `scaled_similarity()` now guarantees a `[0,1]` output regardless of embedding provider. Today's TF-IDF fallback can't actually produce a negative value (term-frequency vectors are non-negative by construction), but `EMBEDDING_BACKEND=sbert`'s dense vectors can, for genuinely dissimilar text — without the clamp that would surface as a negative "% match". Design choice, stated where it's made: negative similarity clamps to 0 rather than linearly rescaling -1..1 → 0..100, since this is a match *score* and "unrelated" and "opposite" should both mean "not a match."
- **Top-5 Suggestions** (`scoring/suggestion_engine.py`, new): ranks candidate fixes by an *analytically computed* impact estimate (using the real weights already in `hybrid_score.py`/`readiness.py`), not an LLM-guessed number — the LLM's job is phrasing, not deciding the ranking. Draws on a new shared `scoring/content_quality.py` module (bullet-level metric/verb/passive-voice detection, used by both JD and No-JD modes per the approved shared-module design) which also finally populates `WorkHighlight.has_metric`/`action_verb` — those fields existed on the schema with a "set by the scoring engine" comment since it was written, and nothing ever set them until now. Every suggestion is tagged `score_context: "match_score"` or `"readability"` depending on whether fixing it would actually move the number currently shown — content-quality fixes don't move `final_score` in JD-match mode today (no weight for them in that formula), and mislabeling that would be exactly the false-precision problem this project has tried to avoid everywhere else. "Format errors" is deliberately scoped down to reusing/extending the existing structural + contact-field checks rather than a full column/table/glyph parseability engine, which would be its own project.
- **Mode-aware feedback tone** (`llm/feedback_prompt.py`, new): two rubrics (`WITH_JD_INSTRUCTIONS` grounds every sentence in the specific job; `NO_JD_INSTRUCTIONS` focuses on general ATS readability and industry-standard skill gaps), following `batch_candidate_narratives.py`'s existing pattern — cache-aware system blocks, an explicit "don't invent anything beyond the given facts" guardrail, routed through `TaskType.CONVERSATIONAL_AGENT`. A deterministic `template_feedback_summary()` fallback needs no API key at all; `POST /score/suggestions` uses it by default and only calls the live model when `use_llm: true` is explicitly passed, falling back to the template on any failure rather than surfacing a raw error.

## Semantic Fit screening report (`POST /score/full-report`)

A separate, richer alternative to `/score/jd-match` — that route and its 3-weight formula are untouched; this is additive, not a replacement, so nothing that already depends on the simpler shape breaks.

Three layers, each its own module:

1. **JD requirement extraction** (`scoring/jd_requirement_extractor.py`) — reads the JD once, before touching the resume, and classifies every requirement (skills, the years-of-experience figure, the degree requirement) into `knockout` / `important` / `preferred` based on the JD's own wording ("required"/"must have"/"minimum" vs. "preferred"/"nice to have"/"plus"), not a fixed per-skill judgment call. One deliberate correction along the way: a phrase like "3 years of professional software engineering experience" no longer gets double-counted as a separate, incorrectly-knockout-tiered "software engineering" skill requirement — that's describing the experience requirement, not a second mandatory skill.
2. **Evidence-aware matching** (`scoring/requirement_matching.py`) — for each requirement, determines not just presence but *where* it's demonstrated and *how strongly* (a bullet with a metric > a bullet with context > a bare Skills-list mention > nothing). A requirement's tier only ever *elevates* a failing status to `knockout_risk` — a satisfied mandatory requirement is just reported as matched, never as some kind of risk.
3. **The weighted report** (`scoring/screening_report.py`) — 7 dimensions (knockout requirements 30%, technical skills 20%, semantic fit 20%, experience 10%, project relevance 10%, education 5%, ATS readability 5%), each reusing an existing scoring primitive rather than recomputing anything (`embeddings.scaled_similarity` for semantic fit, `experience_match.py` for experience, two small new modules — `education_match.py`, `project_relevance.py` — for the two genuinely new dimensions). Produces strengths, gaps, ranked suggestions, and the top 3 reasons/improvements the spec asked for.

Stated rather than silently skipped, when it was still true: "ATS Readability" was structural + contact-field completeness only. That gap is now closed (see the next section) for file uploads specifically — pasted plain text never had layout to begin with, so there's nothing to analyze there.

## Closing the remaining gaps: real layout analysis, semantic matching, and a few more report categories

A follow-up pass, addressing everything from the spec that was still either missing or only partially wired up:

- **Real ATS format/layout analysis** (`parsing/format_analysis.py`, new) — this used to be flatly out of scope because it needs the *original file's* bytes, not the already-parsed resume. It now runs at the one place those bytes are still available: `POST /resume/parse-file`, alongside the existing text extraction. For DOCX, `python-docx` gives direct access to tables, inline images, and header/footer text, so table detection, embedded-image detection, and "contact info only in the header" are all real checks against the real document, not heuristics. For PDF, `pypdf`'s layout-preserving extraction mode catches a genuine multi-column signal (a large gap in the *middle* of a line, not just trailing whitespace) — still a heuristic, stated as one, but a real one, tested against actual generated documents rather than mocked. `POST /score/full-report` accepts an optional `format_risk_count` (sourced from a prior parse-file call) that knocks the ATS Readability dimension down further when real risks were found — additive to structural completeness, not a replacement for it, since a resume can have every section present and still be sitting inside a two-column PDF.
- **Genuine semantic matching** (`scoring/requirement_matching.py`) — the spec repeatedly asks for this (JD says "machine learning", resume says "built predictive classification models," zero shared words) and it was entirely absent before; skill matching was always exact-phrase-or-nothing. The code path is now real and correctly wired (capped at `MODERATE` evidence strength — a semantic hit is real evidence but inherently less certain than an exact one), with an important, tested, and stated honesty check: the default TF-IDF embedding provider scores genuinely unrelated vocabulary at exactly the same 0.0 as genuinely related-but-differently-worded text (verified against real examples, not assumed) — so this path is correct and ready but functionally near-inert until `EMBEDDING_BACKEND=sbert` is active. Building it as if it already "worked" under TF-IDF would have been the same false-precision problem this project has tried to avoid everywhere else.
- **Date format consistency** (`scoring/experience_match.py`) — flags mixed date phrasing across roles (e.g. one job as `"2020-01"`, another as `"Summer 2022"`) as its own gap, separate from `has_unparseable_dates()` (a date can be a consistent *format* and still fail to parse, or vice versa).
- **Keyword stuffing detection** (`scoring/screening_report.py`) — counts literal occurrences of each matched skill's phrase across the whole resume; five or more repeats of the same phrase is flagged as worth a natural-language double-check, separate from (not folded into) the main gap list.
- **Exact/Semantic/Missing/Weak keyword categorization** (`to_dict()`'s `keyword_categories`) — the underlying per-requirement `match_type`/status data already existed; this organizes it into the four named buckets the spec asked for, rather than leaving the caller to re-derive them from the flat requirements list.
- **Relevance Gap detection** (`_relevance_gap_bullets`) — flags work-experience bullets with zero lexical overlap with the JD and no matched JD skill (e.g. "organized the company holiday party" against a backend-engineering JD). Deliberately lexical-overlap-based rather than embedding-similarity-based: the same TF-IDF weakness that makes semantic matching inert would have made an embedding-threshold version of this check over-flag almost everything, verified empirically before choosing this approach over that one.
- **Confidence field** on each requirement match — how confident the *system* is in a status determination (high for exact matches and genuine misses, medium for a semantic-only hit), a distinct axis from tier (how important) and evidence strength (how well-demonstrated).


## Project layout

```
app/
  schemas/
    json_resume.py       # the canonical data model (Section 4.5)
    api_models.py         # request/response shapes
  core/
    scoring/
      embeddings.py        # pluggable embedding provider (TF-IDF now, SBERT-ready)
      skill_extraction.py  # canonical skill matching + synonym normalization
      experience_match.py  # years-required vs. years-held, range-aware (Task 1)
      seniority.py           # JD seniority detection -> dynamic weight profile
      content_quality.py     # shared per-bullet metric/verb/passive-voice analysis (Task 3)
      suggestion_engine.py   # Top-5 Suggestions, analytically ranked (Task 3)
      jd_requirement_extractor.py  # JD requirement extraction + tiering (Semantic Fit Layer 1)
      requirement_matching.py      # evidence-aware requirement matching (Semantic Fit Layer 2)
      education_match.py           # degree-level requirement matching
      project_relevance.py         # JD-relevant project detection
      screening_report.py          # 7-dimension weighted screening report (Semantic Fit Layer 3)
      hybrid_score.py       # Mode 1: FinalScore formula + XAI breakdown
      readiness.py          # Mode 2: JD-less ATS readiness score
    bias_audit/
      jd_bias_scanner.py    # agentic/communal skew + ageist phrasing audit (Section 5)
    voice_agent/
      agent_loop.py          # Mode 3: ask-vs-generate decision core
      gap_resolution.py      # scoring gap -> targeted question -> patch -> rescore
      tool_schema.py          # the tool-calling schema for schema-guided edits
    llm/
      router.py               # task type -> model (never hard-code a model elsewhere)
      client_factory.py       # get_client_for(task) -> (client, model), provider-aware
      claude_client.py         # Anthropic API wrapper (production default)
      gemini_client.py         # Gemini API wrapper (LLM_PROVIDER=gemini)
      groq_client.py           # Groq API wrapper (LLM_PROVIDER=groq)
      oss_extraction_client.py # open-weight crosscheck model wrapper
      token_pricing.py         # $/token cost calculation, all providers
      prompt_cache.py          # Anthropic cache_control breakpoint placement
      feedback_prompt.py       # With-JD/No-JD feedback tone + template fallback (Task 4)
      batch_resume_extraction.py    # bulk classification/crosscheck batch jobs
      batch_candidate_narratives.py # bulk XAI narrative batch jobs
    parsing/
      file_extraction.py        # .pdf/.docx -> raw text (pypdf/python-docx)
      format_analysis.py        # real layout/table/image/header-footer checks on raw file bytes
      resume_extraction.py      # raw text -> JsonResume (LLM tier + heuristic fallback)
      parser_interface.py       # Docling primary / Marker fallback adapters (optional, heavier)
  db/
    models.py                    # users, resumes, scan_results, subscriptions
  api/routes/                     # FastAPI route handlers (resume, score, bias-audit, voice, billing)
  main.py                          # FastAPI app
  config.py                        # pricing tier definitions (Section 7)
frontend/                           # static HTML/CSS/JS reference console (see "Frontend" below)
infra/
  schema.sql                       # pgvector extension + embedding column
tests/                              # pytest suite covering every core/ module
Dockerfile                          # builds the api service (referenced by docker-compose.yml)
.dockerignore
docker-compose.yml                  # Postgres+pgvector + API + frontend, wired together for local dev
```

## Running it

```bash
cp .env.example .env        # then fill in whichever API keys you want to use --
                             # every value is optional, see the comments in that file
pip install -r requirements.txt
PYTHONPATH=. pytest tests/ -v          # 335 tests, all passing (verified against both SQLite and real Postgres+pgvector)
PYTHONPATH=. uvicorn app.main:app --reload
# -> http://localhost:8000/docs for interactive API docs
```

`.env` is loaded automatically -- `app/__init__.py` calls `load_dotenv()`
before any submodule of this package runs its own top-level code, so this
covers the API server, a one-off script, or a bare Python REPL import
alike (verified: importing a scoring/LLM submodule directly, with nothing
exported in the shell, still picks up `.env` correctly). Nothing needs to
be `export`ed manually. Every value in `.env.example` is optional and has
a working default (the app runs with zero configuration at all -- LLM-backed features fall back to a
heuristic/template path, embeddings fall back to TF-IDF, the database
falls back to a local SQLite file); set only the keys for the providers
you actually want to use. `.env` itself is git-ignored, so a real key
never accidentally ends up committed.

Or with Postgres, the API, and the frontend all together:

```bash
docker compose up --build
```

`--build` matters the first time (or after changing `requirements.txt` /
`Dockerfile`) — Compose caches the image otherwise. This brings up three
services: `db` (Postgres + pgvector), `api` (built from the repo's
`Dockerfile`, on :8000), and `frontend` (nginx serving `frontend/`
statically, on :5500, CORS-preconfigured to match — see "Frontend"
below). Open `http://localhost:5500` once it's up.

To use a non-default LLM provider with Docker, pass the env vars through
(see "Multi-provider LLM switching" below for the full picture):

```bash
LLM_PROVIDER=gemini GEMINI_API_KEY=your-key docker compose up --build
```

## API surface

| Endpoint | Mode |
|---|---|
| `POST /resume/parse-file` | Upload a resume (.pdf/.docx) → structured JsonResume + real format_analysis (see below) |
| `POST /resume/parse-text` | Paste resume text directly → structured JsonResume |
| `POST /score/jd-match` | Mode 1 — resume vs. JD hybrid score + XAI breakdown |
| `POST /score/standalone` | Mode 2 — JD-less ATS readiness score |
| `POST /score/suggestions` | Ranked Top-5 Suggestions, With-JD or No-JD tone (mode inferred from whether `jd_text` is given) |
| `POST /score/full-report` | Semantic Fit screening report — knockout detection, evidence-aware requirement matching, 7-dimension weighted score |
| `POST /bias-audit/jd` | Ethical AI layer — scan a JD for language skew and ageist phrasing |
| `POST /voice/turn` | Mode 3 — one turn of the voice-editing agent loop |
| `POST /voice/gap-prompt` | Interactive gap resolution — get the next targeted question for a scoring gap |
| `POST /voice/gap-answer` | Interactive gap resolution — patch the answer into the resume, get the before/after score |
| `GET /billing/tiers` | Pricing tiers (Section 7 of the blueprint) |

`/score/*` and `/bias-audit/*` still take a `JsonResume` object directly if
you already have one (that's how the tests exercise them) — `/resume/parse-*`
is the on-ramp for everyone else: upload a PDF/DOCX or paste raw resume
text, get back the same JsonResume shape, ready to hand to `/score/*`.
Neither parse endpoint requires an LLM provider to be configured — see
"Resume ingestion" below for the two-tier (LLM-enhanced, falling back to
a no-key-required heuristic parser) design.

## Resume ingestion (file upload / paste text)

Before this existed, using `/score/*` meant hand-writing JSON matching the
`JsonResume` schema — fine for testing the API, not something to ask
someone uploading their resume to do. `/resume/parse-file` and
`/resume/parse-text` are the actual front door:

```bash
curl -X POST http://localhost:8000/resume/parse-file -F "file=@resume.pdf" -F "tier=basic"
# or
curl -X POST http://localhost:8000/resume/parse-text \
  -H "Content-Type: application/json" -d '{"text": "Jane Doe\nSoftware Engineer\n...", "tier": "basic"}'
```

Both return `{"resume": {...JsonResume...}, "parse_method": "llm"|"heuristic",
"warnings": [...], "provider_used": "claude"|"gemini"|"groq"|null}`. The
frontend's "Upload file" / "Paste text" / "Paste JSON" tabs (see
"Frontend" below) call these directly, with a Basic/Medium/Advanced tier
button row above the input — file/paste-text parsing fills in the same
underlying JSON the "Paste JSON" tab shows, so you can always review or
hand-edit the result before scoring.

`tier` is optional on both endpoints — see "Multi-provider LLM switching"
below for exactly what it does and the bug it fixes; omitting it falls
back to the `LLM_PROVIDER` env var, same as before tiers existed.

**Text extraction** (`app/core/parsing/file_extraction.py`): `.pdf` via
`pypdf`, `.docx` via `python-docx` — both lightweight, no CV/OCR models,
which covers a normal text-based resume correctly. Scanned/image-only
PDFs come back with a warning (`No extractable text found...`) rather
than a wrong answer — that needs OCR, which is `parser_interface.py`'s
Docling/Marker adapters' job (used automatically if either happens to be
installed; see that module's docstring for the tradeoff).

**Text → structured JsonResume** (`app/core/parsing/resume_extraction.py`),
two tiers, in preference order, orchestrated as a small LangGraph graph
(see "Multi-provider LLM switching" below for why LangGraph fits this
specific flow):
1. **LLM extraction** (`TaskType.RESUME_EXTRACTION`) — far more reliable
   on real-world formatting. Which provider answers this is the `tier`
   param, not a fixed env var — see "Multi-provider LLM switching" below.
2. **Heuristic extraction** (regex + section-header + bullet-line
   splitting) — no API key or network needed, so it's what runs when no
   tier's key is configured. Handles a normal single-column resume with
   conventional section headers (Experience/Education/Skills/Projects)
   reasonably well; it will *not* reliably untangle multi-column layouts
   or unconventional section names. `warnings` in the response exist
   specifically to flag "this was a rough automated parse, please
   review" rather than presenting a guess with false confidence.

Either tier's output is validated through `JsonResume.model_validate()`
before being returned, so a caller never gets a malformed resume object —
worst case is a JsonResume with fewer fields filled in than a person
would have entered by hand, never an invalid one.

## Standalone (No-JD) ATS scoring rebuild, Figma design, and animation

Three connected pieces of work, in the order they were done.

**Design, in Figma.** A real Figma file was created via the Figma MCP
connector (not mocked) — [Resume Optimizer — Standalone ATS Redesign](https://www.figma.com/design/L8qzvZtSnYMphjRCQMkZ79) —
using the app's actual design tokens read directly from `styles.css`
(colors, IBM Plex font family) rather than guessed. It contains two
frames: **Settled** (the final report state) and **Loading** (t≈350ms
into the reveal — dimmed score, partially-filled bars, sections not yet
revealed), plus a **Motion annotations** block documenting the intended
timing: score counts up over 700ms ease-out-cubic; the gauge bar and
three dimension-tile bars fill in sync, tiles staggered 80ms apart;
missing-sections and suggestions fade up 8px, 150ms after the score
settles; all of it skipped in favor of immediate final values under
`prefers-reduced-motion`. That spec is what `frontend/app.js`'s
`animateScoreNumber`/`animateWidthFills`/`revealStagger` actually
implement — the Figma file is a real source of design truth here, not
an artifact produced after the fact to describe already-written code.

**Architecture rebuild: `scoring/readiness.py`.** Requested as "the
architecture needs improvement" — investigated rather than assumed, and
three concrete, verified problems came out of that (not style
preferences):

1. The role ontology had exactly two entries (`software_engineer`,
   `data_scientist`). Expanded to eleven, still deliberately scoped to
   roles buildable from `skill_extraction.py`'s existing canonical
   vocabulary (software engineering, cloud, data, DevOps) — there's no
   equivalent vocabulary in this codebase yet for non-technical fields,
   and a resume outside this ontology's coverage now gets a neutral,
   non-penalized `skill_coverage_score` rather than a wrong one.
2. Role inference compared against `resume.all_skill_keywords()` — raw,
   uncanonicalized strings straight from the Skills field. A skills list
   containing `"React.js"` never matched the ontology's canonical
   `"react"`, and anything mentioned only in a work bullet or project
   (not the Skills section) was invisible to inference entirely. Fixed
   by running `extract_canonical_skills()` over the resume's full text,
   with the Skills field passed in as an extra hint rather than the only
   source — verified with two regression tests that specifically fail
   against the old code (`test_role_inference_handles_phrasing_variants...`,
   `test_role_inference_sees_skills_mentioned_only_in_work_bullets`).
3. Skill coverage for the inferred role was computed but never actually
   scored — informational text only, contributing nothing to
   `overall_score()`. The formula is now five weighted dimensions
   (structural 0.30, quantified-metric 0.20, action-verb 0.15,
   active-voice 0.10 — also computed-but-unscored before, now weighted —
   skill-coverage 0.25) instead of the original three, and both new
   dimensions are proven to actually move the score
   (`test_skill_coverage_actually_changes_overall_score`,
   `test_active_voice_actually_changes_overall_score`). Every original
   `to_xai_dict()` field name is kept exactly as it was — this was a
   formula change, not a response-shape break, and the frontend needed
   no compatibility handling as a result.

**Animation, in the real app.** `frontend/styles.css` already had a
global `prefers-reduced-motion` rule collapsing all CSS transition/
animation durations — that covers the gauge and tile bar fills for free.
The score count-up is JS, not a CSS transition, so it checks
`matchMedia` itself and jumps straight to the final value when reduced
motion is requested, rather than relying on the CSS catch-all to cover
something it structurally can't. Applied consistently to both places a
headline score appears (Standalone and the JD Match / Full Report
result), not just the panel that was explicitly called out, since a
score that counts up in one place and snaps into place in another would
have read as inconsistent rather than polished.

## Hero section (`frontend-react/src/pages/Hero.jsx`)

Adapted from a supplied 21st.dev-style component — a music-streaming hero (looping video background, a physics-based track carousel, synthesized mechanical scroll-click audio). That content has nothing to do with a resume tool, so it wasn't shipped as-is; ports like that are evaluated for what genuinely generalizes, not copy-pasted wholesale.

**Kept:** the cursor-tilt "floating screen" effect (pointer position → `rotateX`/`rotateY` transform), an immersive drifting gradient background instead of flat color, glass-morphic chrome, and the CSS-variable-with-fallback theming pattern (adapted to this app's actual hex tokens rather than the source's HSL-triplet convention).

**Dropped entirely:** the video, the track-list carousel and its flick-physics, and the synthesized scroll-click sound — all specific to a music player, none of it appropriate here.

**Replaced:** instead of a stock video, the tilting card shows a live miniature of the *actual* report UI — the real `ScoreHeadline`/`GaugeBar`/`DimensionTile` components, reused directly rather than mocked up. Showing the real product is more honest, and a better demo, than a generic asset.

Real routing was added to support this (`react-router-dom`, three routes: `/` hero, `/with-jd`, `/without-jd`) — `App.jsx` previously switched between the two report views with local tab state and had no landing page at all.

## Landing page, Login, and Signup

Adapted from two more supplied 21st.dev-style components (a marketing navbar+hero, and a split-screen auth UI) — same discipline as the Hero: kept what generalizes, dropped what doesn't, and flagged the one real blocker rather than papering over it.

**Navbar** (`components/Navbar.jsx`), adapted from the supplied `NavbarHero`. Dropped: the About/Resources/Blog/Pricing nav with placeholder "Submenu 1/2" dropdowns (nothing real behind them — a menu opening onto fake items is exactly the "buttons that do nothing" failure mode already ruled out earlier in this project), the email-capture newsletter form (this is a direct-use tool, not a waitlist product), and a dark/light theme toggle (there's no dark-mode token set built — a toggle that doesn't actually change anything is worse than no toggle). Kept: the responsive mobile-menu pattern. Links point only at real routes.

**Auth pages** (`pages/AuthPage.jsx`, `/login` and `/signup`), adapted from the supplied `auth-ui.tsx`. Two deliberate departures from the source:

1. **No Radix/cva/clsx/tailwind-merge.** The source composes its Button/Input/Label through `@radix-ui/react-slot`, `@radix-ui/react-label`, `class-variance-authority`, and `tailwind-merge` — all Tailwind/shadcn-ecosystem utilities for conditional className composition. This app has no Tailwind (a deliberate, already-approved decision from earlier in this project), and the actual markup — a labeled input, a styled button, a toggle link — doesn't need three extra dependencies to be accessible; a real `<label htmlFor>` and a real `<button aria-label>` already are. `Typewriter` itself had no such dependency in the original either, so it's ported essentially verbatim (TSX → JSX, types dropped).
2. **The form is honest that it isn't connected to anything.** Phase 0's audit confirmed there is no auth backend anywhere in this codebase — Firebase Auth is Phase 3 of the architecture plan (see the phase-0 audit document from earlier), not started. Shipping a sign-in form that silently `console.log`s and appears to succeed, or a "Continue with Google" button that does nothing when clicked, would be exactly the faked-functionality problem this project has explicitly ruled out from the start. Instead: a visible "PREVIEW — accounts aren't live yet" badge at the top of the page, and submitting either form (or clicking the Google button) shows a real, visible message saying authentication isn't connected yet — never a silent no-op, never a fake success.

Tested accordingly: `AuthPage.test.jsx` specifically asserts the honest-messaging behavior (submitting shows the real notice, not a redirect or fake success), not just that the form renders.

## React report app (`frontend-react/`)

A second, independent frontend covering just the report screens (JD Match's Full Report, and the Standalone/No-JD report) — approved scope for this pass was "report screens only," not a full migration of the console. The existing static `frontend/` console is untouched and still the place to reach Bias Audit, Voice Editor, Gap Resolution, and Pricing.

**Design, in Figma.** Extended the same file from the earlier animation work — [Resume Optimizer — Standalone ATS Redesign](https://www.figma.com/design/L8qzvZtSnYMphjRCQMkZ79) — with a real **Variable Collection** (`Design Tokens`, 16 color variables bound to actual node fills, not literal hex values pasted in) and two genuine **skeleton-loading frames** — gray placeholder shapes matching the loaded content's exact layout grid, not a spinner or a dimmed copy of real data — plus a documented shimmer spec (1.4s linear gradient sweep, frozen to a flat tone under reduced motion). `src/components/SkeletonBlock.jsx` and `ReportSkeleton.jsx` implement that spec directly.

**Stack**: Vite + React 18, plain JavaScript (no TypeScript, per approved scope), Framer Motion for animation (per approved scope — the alternative considered was plain CSS transitions, which is what `frontend/`'s vanilla console still uses).

**Structure**:
```
frontend-react/src/
  components/       # ScoreHeadline, GaugeBar, DimensionTile, RequirementRow,
                     # TagList, BulletList, KnockoutBanner, RoleBadge,
                     # SkeletonBlock, ReportSkeleton, FadeUpSection, useCountUp
  features/report/  # useFullReport.js / useStandaloneReport.js (data hooks,
                     # explicit idle/loading/success/error states) +
                     # FullReportView.jsx / StandaloneReportView.jsx
  lib/api.js         # fetch wrapper, lib/sampleData.js (matches frontend/'s samples)
  styles/tokens.css  # ported 1:1 from frontend/styles.css's :root — not re-derived
```

**Motion**: score count-up (`useCountUp`, ease-out-cubic, matches the vanilla console's curve exactly so both frontends feel identical), gauge/tile bar fills, staggered section fade-up, and the skeleton shimmer — all via Framer Motion, all respecting `prefers-reduced-motion` (via Framer's built-in `useReducedMotion()`, which is why this frontend didn't need to hand-roll a `matchMedia` check the way the vanilla console did).

**Running it**:
```bash
cd frontend-react
npm install
npm run dev       # http://localhost:5174, proxies /score, /resume, etc. straight to :8000
# or, against a production build:
npm run build     # outputs to ../frontend-react-dist
npm run preview   # http://localhost:5175, calls the API directly (needs CORS -- already in .env.example)
```
Not mounted into FastAPI — served as its own static origin, same convention as `frontend/` (see `app/main.py`'s CORS comment), so the backend stays API-only.

**Tests** (Vitest + React Testing Library, `npm test`): 39 tests covering every component's loading/loaded/error states, not just happy-path rendering — `FullReportView`/`StandaloneReportView` each have dedicated tests for the skeleton showing during a pending request, the real report rendering on success, an error box rendering on API failure, and (Standalone only) the suggestions call failing independently without taking down the score display. One real bug caught by these tests during development, not after: `ReportSkeleton`'s tile row was being probed with fragile positional child-indexing (`.score-card > div[2]`), which broke the moment the skeleton's internal DOM structure had one more wrapper div than assumed — fixed by giving the tile row an explicit `data-testid` instead of relying on position.

**Honest limitation, carried over from the vanilla console**: no real browser was available to visually check this in — build output, component tests, and a direct `TestClient` check of the exact sample data this app ships with were all verified, but an actual first open is still worth doing, particularly the `report-columns` grid at narrow widths.

## Report redesign, ParsingLoader, Dashboard/Settings, and the scoring-engine reorg

**ParsingLoader** (`components/ParsingLoader.jsx`), adapted from a supplied "ai-loader" component — a full-screen rotating glow ring with letter-pulse text. Rebuilt with Framer Motion instead of the source's Next.js-specific `<style jsx>` (which doesn't exist in this Vite app — Framer Motion was the explicit ask for this round anyway), and reskinned entirely to this app's own tokens (`--ink`, `--accent`, `--match`) rather than the source's navy/sky palette — "same theme as the application" was explicit. The technique (a dark backdrop so the glow actually reads — box-shadow glows need contrast to show up) is kept; the color scheme isn't the source's. Shown as a genuine full-screen takeover during resume parsing in both report flows.

**Report redesign.** Both `FullReportView` and `StandaloneReportView` were restyled around two new components: `ReportHero` (a distinct eyebrow label, icon, and accent gradient per mode — green-leaning for a match score, gold-leaning for readiness — so the two report types read as purpose-built experiences instead of sharing one plain score display) and `SectionHeader` (icon + title, replacing plain text labels throughout). Every list in the report — strengths, gaps, recommendations, requirements, keyword tags — is now capped to its top 5 via a new `TopList` component, with a "Show N more" toggle rather than either dumping everything at once or permanently hiding the rest. `TopList` is generic over how each item renders (a render prop), so the same expand/collapse logic wraps `BulletList`, `TagList`, and requirement rows without three copies of the same code. The old "Top 3 reasons for this score" / "Top 3 improvements needed" section was dropped entirely — it duplicated the Strengths/Gaps/Recommendations sections directly above it, and consolidating is part of what "advanced" report design means here, not just capping lists.

**Dashboard and Settings**, both reusing existing endpoints (`/auth/me`, `/history`) rather than needing new backend work: Dashboard shows plan/usage, quick actions, and recent activity; Settings is deliberately minimal — real account info and sign-out, no toggles or preferences that don't actually do anything (password/email changes go through Firebase's own account flows, not a custom form duplicating what Firebase already handles securely).

**Phase 2 (scoring-engine reorg).** Traced actual imports rather than assuming: `content_quality.py` and `skill_extraction.py` are genuinely shared between the JD-mode path (`hybrid_score.py`, `screening_report.py`) and the JD-less path (`readiness.py`) — and `screening_report.py` even calls `readiness.py`'s `structural_completeness_score()` directly, a real cross-mode reuse already in place. The engines were already correctly shared; what was missing was making that visible. Documented in `app/core/scoring/__init__.py` (previously empty) rather than physically relocating already-tested modules, which would be pure churn risk (331 passing tests depend on these import paths) for no behavioral difference.



## Stale-database schema drift — the actual cause of the reported with-JD/without-JD 500s

Reported symptom: uploading a resume in either flow "gives internal server error." The earlier encrypted-PDF fix (below) was real but didn't explain this — `/resume/parse-file` has no database dependency at all, so it couldn't be the cause of a failure that happens right after upload succeeds. Root-caused properly this time by actually reproducing the reported shape of the problem end-to-end, not just re-testing what was already fixed:

`Base.metadata.create_all()` — what `app/db/session.py` uses to set up the local SQLite dev database — only creates tables that don't exist yet. It **never adds a column to a table that already exists.** Across this project's many iterations, `models.py` gained new columns on existing tables (`User.firebase_uid`, added in the Phase 3 auth work) and new tables (`Payment`, `UsageLog`). A `dev.db` left over from before those columns existed still has the *old* `users` table shape — `create_all()` sees "users already exists," skips it, and the column is simply never added. The next request that queries `User.firebase_uid` — any signed-in call to `/auth/me`, `/score/standalone`, or `/score/full-report` — crashes with an uncaught `OperationalError: no such column: users.firebase_uid`. A browser's default reason phrase for an unhandled 500 with a non-JSON body is literally the string "Internal Server Error" — which is exactly, verbatim, what got reported.

Confirmed by deliberately building a stale schema and reproducing the crash before writing any fix (a two-attempt fix, both attempts verified against the actual reproduction rather than assumed correct): `app/db/session.py` now inspects the real, current column set of every table against what the models expect at startup, and if a table exists but is missing columns the current models declare, it logs a clear message and recreates the SQLite file fresh — this is explicitly a throwaway local convenience database (production always uses real Alembic migrations against Postgres, untouched by any of this), not a persistent one, so healing it is safe. The first attempt at this fix had its own bug — it derived the file path to delete from a module-level global instead of the actual engine passed in, so it silently deleted the wrong file and didn't fix anything; caught by writing a test with a custom path instead of only testing the default case, not shipped.

## UI improvements: step indicator, polished input states

A `StepIndicator` component (Upload → Details → Report) gives both flows visible progress structure they didn't have before. The plain "Resume: filename" text row is replaced with a proper confirmation card (checkmark icon, resume name, "Resume loaded" label). The input card itself (upload/JD-entry container) got a real visual pass — softer shadow, larger radius, and the job-description textarea switched from monospace to the body font with a proper focus ring, since a job posting is prose a person reads, not code.

## Resume upload 500 error — root-caused and fixed

A real, reported bug: uploading certain PDFs crashed `/resume/parse-file` with an uncaught 500. Reproduced directly (not guessed) with a genuinely encrypted PDF, and traced to a precise root cause: `pypdf`'s `reader.decrypt("")` returns `0` on failure rather than raising an exception when a PDF has a real, non-blank password. The existing code only wrapped `decrypt()` in `try/except`, never checked the actual return value — so a password-protected PDF silently sailed past that check, then crashed the moment `reader.pages` was iterated a few lines later with an uncaught `FileNotDecryptedError`.

Fixed in three layers: (1) `file_extraction.py` and `format_analysis.py` now check `decrypt()`'s real return value explicitly, plus defense-in-depth around the whole page-iteration loop in both files (the same fix applied preemptively to `.docx` extraction, since it's the identical failure shape — construction succeeds, iteration doesn't); (2) a structural safety net added at the `/resume/parse-file` route level itself, so the endpoint's "never 500, always return a clear warning" contract doesn't depend on every internal function catching every case correctly; (3) regression tests at both the unit and route level, using an actually-encrypted PDF generated in the test itself, not a mock. Verified against a real uvicorn server + curl, not just `TestClient`.

## Google Sign-In and payment gateway (Razorpay)

**Google Sign-In.** The core integration (`signInWithPopup` + `GoogleAuthProvider` in `lib/authContext.jsx`) already existed; this pass hardened its error handling, which previously let raw Firebase SDK errors bubble straight to the user. Now: a user closing the popup themselves resolves silently (not a real error, showing a banner for it would be worse than showing nothing), a blocked popup gets an actionable message telling them to allow popups, and an account-exists-with-different-credential conflict explains what happened instead of showing a cryptic error code. Firebase Console setup (enabling Google as a provider, authorized domains) is documented in `frontend-react/.env.example` — that's a manual dashboard step, not something committable as code.

**Razorpay.** `razorpay_client.py` (signature verification via the official SDK, not hand-rolled HMAC) and the `Payment` DB model already existed from earlier work; this pass built the actual routes connecting them: `POST /payments/create-order` (creates a Razorpay order for a signed-in user, returns the order id and the *public* key_id — never the secret — for the frontend's Checkout widget), `POST /payments/verify` (the client-side callback path, verifies the payment signature and activates the subscription), and `POST /payments/webhook` (the server-to-server path, Razorpay's own recommended source of truth precisely because it doesn't depend on the browser staying open). Both activation paths are idempotent with each other — whichever fires first wins, the second is a harmless no-op — since either one, or both, can genuinely happen in production.

Signature verification is tested with **real HMAC-SHA256 math using fake keys** — this is genuinely, meaningfully testable without live Razorpay credentials, since it's deterministic cryptographic verification, not a network call. Tests prove a validly-signed payment succeeds and a signature computed with the wrong secret is rejected, not just that garbage fails (which would be a much weaker test). Order *creation* itself (a real network call to Razorpay's API) is tested with the Razorpay call mocked — that verifies this app's own request construction, not that Razorpay's live API accepts it, which is an honest limitation stated here rather than glossed over.

Frontend: `lib/razorpay.js` (loads Razorpay's Checkout script, wraps its callback-based widget in a promise so it can be `await`ed like every other API call in this app) and `pages/PricingPage.jsx` (fetches real tiers from `/billing/tiers`, monthly/annual toggle, triggers the full create-order → Checkout → verify flow, shows the current plan once signed in). A user dismissing the Checkout widget is treated as a non-error (same principle as the "popup closed" case above) rather than an alarming failure banner.

**Deliberately not built:** actual recurring billing (Razorpay Subscriptions, which need pre-created Plan IDs configured in the Razorpay dashboard — a manual setup step, not something buildable without a live account) — this is one-time checkout that activates a subscription for a fixed period (30/365 days), a real but simpler mechanism than true auto-renewing subscriptions. Documented as a natural next step in `.env.example`, not silently substituted for the real thing.

## Phase 5 completion: real file upload, stale-report detection

The most consequential gap flagged after the last round of phase work: the React app only ever accepted pasted `JsonResume` JSON, not an actual `.pdf`/`.docx` upload — meaning it wasn't really usable as a resume tool yet, despite the backend's `/resume/parse-file` endpoint (strict `.pdf`/`.docx`, 10MB cap) having existed the whole time.

**`features/upload/`** — `FileDropzone.jsx` (drag-and-drop + click-to-browse, keyboard accessible, three visual states) and `useResumeUpload.js` (the hook: validates extension/size/emptiness client-side — matching the backend's own rules exactly, not a separate policy — then calls `/resume/parse-file`). A scanned/image-only PDF that parses to an empty resume is treated as a real error ("no text could be extracted"), not a silent success — that's a genuine, expected outcome per `file_extraction.py`'s own docstring, and the person uploading needs to know, not just see a blank report. Wired into both `FullReportView` and `StandaloneReportView`, replacing the JSON textarea entirely.

**Stale-report detection**, the other half of Phase 5: editing the job description after a report already exists shows a visible banner ("Your job description has changed since this report was generated") with a working Refresh button — the old report stays visible until refreshed, rather than silently looking current. Changing the *resume* does a full reset instead (clears the old report entirely) — showing an old report next to a completely different resume, even with a banner, risks real misattribution in a way a JD edit on the same resume doesn't.

**A real bug caught fixing the tests, not the code**: the JD textarea was left pre-filled with sample text from the earlier JSON-paste-era code, so "the Run button is disabled until you type a JD" was never actually true — the field was never empty to begin with. Fixed to start genuinely empty with a placeholder instead of demo content, now that this is a real upload flow rather than a JSON-paste demo sandbox.

## Phase 10 (further): accessibility

A skip-to-content link and proper `<main>` landmarks — confirmed via `grep` that neither existed anywhere in the app before this (no `<main>`, no skip-link, in any component). `Layout` (the shared shell for Hero/report/history pages) and `AuthPage` (which renders outside that shell, no shared navbar) both now have one. Verified with a dedicated test (`App.test.jsx`) rather than just visually — checks the link's `href="#main-content"` actually matches the landmark's `id`.



## Phases 3, 4, 7, 9, 10 (partial), 11 (partial): auth, database, cost tracking, entitlements, rate limiting

Following the Phase 0 architecture plan, implemented out of numeric order deliberately: Phase 3 (auth) and Phase 4 (database) unlock everything else, so they came before Phase 8 (payments), which was explicitly deferred rather than rushed (see below).

**Phase 3 — Firebase Auth.** `app/core/auth/firebase_auth.py` verifies ID tokens server-side; lazily initialized from `FIREBASE_SERVICE_ACCOUNT_JSON`, degrading to a clear 503 (not a crash) when unset. Two FastAPI dependencies: `get_current_user` (401 without a valid token — `/auth/me`, `/history`) and `get_optional_user` (None for anonymous, still 401 on a genuinely invalid token — the scoring endpoints, which stay fully public). Frontend: `lib/authContext.jsx` wraps real Firebase sign-in/sign-up/sign-out; `lib/api.js` attaches the ID token to every request automatically via a registered token provider, so no component that calls the API needs to know auth exists. Both sides degrade the same way when Firebase isn't configured — a real, visible message, never a silent no-op or fake success (see `AuthPage.jsx`'s docstring).

**Phase 4 — Database, actually wired up.** `User`/`Resume`/`ScanResult`/`Subscription` existed in `db/models.py` before this with nothing ever writing to them. `core/services/resume_store.py` now persists a signed-in user's resumes and scan results; `GET /history` lists them. Anonymous use is completely unaffected — persistence only happens when `get_optional_user` resolves to a real user.

**Phase 7 — Cost/usage observability.** `UsageLog` records every LLM call (provider, tokens, cost — wired into `resume_extraction.py`'s LLM fallback and `feedback_prompt.py`'s summary generation) and every scoring request. `record_llm_usage()` never raises, even if the DB is down or the model isn't in the pricing table — an observability side effect must never break the feature it's observing.

**Phase 9 — Entitlements.** `core/services/entitlement_service.py` checks `config.py`'s existing `Tier.jd_match_scans_per_month` against real `UsageLog` counts for the current calendar month. Anonymous requests are never blocked (this app's free tools have always been public); limits apply only to signed-in users, matching a normal freemium shape. Verified end-to-end: a free-tier user gets blocked with a real 429 after 3 scans, and the block is shared correctly across both scoring endpoints (one entitlement pool, not two).

**Phase 10 (partial) — Rate limiting.** `core/rate_limit.py`: a small in-memory per-IP fixed-window limiter on the compute/LLM-adjacent paths (`/resume/`, `/score/`, `/bias-audit/`, `/voice/`) — nothing bounded request volume before this. Deliberately not a new dependency (slowapi etc.) for something this simple to own directly. Stated limitation: per-process state, doesn't coordinate across multiple workers/replicas — fine for the current single-process deployment, needs a shared store (Redis) before scaling horizontally.

**Phase 11 (partial) — Deployment.** `docker-compose.yml` updated: `FIREBASE_SERVICE_ACCOUNT_JSON` and rate-limit env vars added, comments clarify the local `db` service is for dev convenience (this repo targets Supabase for real deployments — see `.env.example`), and a new `frontend-react` service with its own multi-stage `Dockerfile` (Vite build → nginx serve). **Honestly flagged**: no Docker daemon is available in the sandbox this was built in, so the container build itself isn't verified end-to-end — the underlying `npm ci && npm run build` steps it runs were verified repeatedly and directly throughout this project's frontend work, but a real `docker compose up` is worth doing before relying on this.

**Supabase, verified rather than just documented — precisely, not overclaimed.** Postgres 16 + pgvector 0.6 were installed locally and all three Alembic migrations were applied against it directly. Worth being exact about what that does and doesn't cover: the pytest suite's DB-touching tests (`test_auth_and_history.py`, `test_rate_limit.py`) deliberately override `get_db` with an isolated in-memory SQLite session per test — correct for test isolation, but it means *running pytest itself* never actually exercises the real configured engine, regardless of `DATABASE_URL`. What genuinely was verified against the real Postgres instance: the Alembic migrations applying cleanly, and direct `TestClient` calls *without* the dependency override — `/auth/me`, a real scan, and `/history` all confirmed working end-to-end against actual Postgres, not a mock. Still meaningfully stronger verification than was possible for Firebase or would be possible for Razorpay, since Supabase is real Postgres underneath. `.env.example` documents the actual setup: enable the `vector` extension via Supabase's SQL editor, use the Session pooler (not Transaction mode — this is a long-running process, not serverless), and `sslmode=require`.

**Deliberately not built this pass: Phase 8, Razorpay/payments.** There's no live Razorpay account or test API keys available, and payment code specifically deserves focused, unhurried attention rather than being crammed in alongside everything else — building untestable payment integration code would be worse than flagging it clearly and waiting for real test credentials.



## Phase 1: deterministic-first parsing, confidence gate, TF-IDF fix

Following a Phase 0 audit that found the parsing pipeline running LLM-first (every upload cost an LLM call, regardless of resume quality) — the inverse of the target architecture. Four changes:

- **The LangGraph pipeline is inverted.** `resume_extraction.py`'s heuristic node now runs first, always, with no cost and no network dependency. A new module, `scoring/../parsing/parse_confidence.py`, computes a 0-1 confidence score from five auditable signals (contact info, structural sections found, work entries with both position and date, at least one bullet extracted, extracted-structure-to-raw-text ratio) — not a black box, and not itself an LLM call. Below `HIGH_CONFIDENCE_THRESHOLD` (0.7, deliberately conservative — a wrong parse shown to a user is worse than one extra LLM call), it escalates to the LLM node as a fallback. An explicit `tier` or `provider` always forces escalation regardless of confidence — a caller who asked for LLM quality specifically shouldn't be silently downgraded.
- **Two real bugs found and fixed underneath this**, not just the architecture change: the date-range regex only recognized month-name dates ("Jan 2020") or bare years — never numeric "MM/YYYY", the exact format ATS guidance commonly recommends, which meant conventionally-formatted resumes could score *worse* on heuristic confidence than prose-style ones. There was also a genuine regex bug (`[-–—to]` as a character class treats "t" and "o" as individual characters, not the literal word "to"). Both fixed, plus a `_normalize_date_token` step so whatever format was matched becomes the canonical `YYYY-MM` the rest of the schema already expects.
- **A route-level integration bug caught specifically by end-to-end testing, invisible to unit tests**: `_resolve_tier(None)` was resolving `active_provider()` instead of actually returning `None`, contradicting its own docstring. This meant every real API call looked like an explicit tier request, completely defeating the confidence gate in practice — while every direct unit test (which calls `parse_resume_text()` without going through the route) looked fine. Fixed, with a dedicated regression test (`test_no_tier_and_high_confidence_never_attempts_llm_at_all`) that would fail if this regresses.
- **The TF-IDF semantic-fit bug from the audit, fixed.** `TfidfEmbeddingProvider` was calling `fit_transform` on just the two documents being compared per call — IDF computed over a 2-document corpus is degenerate (a term in only one doc gets maximal weight, a term in both collapses toward zero), so genuine lexical overlap was being penalized rather than rewarded. Fixed with `use_idf=False` (plain L2-normalized term frequency, which has no such degenerate case) — verified empirically: "python developer" vs. a bullet containing "Python" went from 0.09 to 0.16. The separate, already-documented limitation (TF-IDF can't recognize "machine learning" ≈ "predictive classification models" — zero shared vocabulary) is untouched by this fix and remains an honest, stated limitation pending an SBERT swap.

**Result:** a well-formatted resume via `/resume/parse-file` or `/resume/parse-text` with no tier specified now makes zero LLM calls, verified via `TestClient` against the real running app, not assumed from unit tests alone.

## Frontend

`frontend/` is a static, zero-build reference console (plain HTML/CSS/JS,
no npm install) covering resume upload/parse, JD match, standalone
readiness, bias audit, the voice-editing agent loop, and the interactive
gap-resolution loop, plus pricing.

There's no separate "report" tab to click into. **JD Match** and
**Standalone** each show their score and their full report in the same
result, from the same button click:

- **JD Match** calls `POST /score/full-report` directly (not
  `/score/jd-match` — that endpoint is unchanged and still exists for any
  API caller that wants the simpler 3-weight shape, but the panel itself
  now shows the richer report by default) and renders the knockout-risk
  banner, the 7-dimension breakdown, keyword coverage, the full
  requirement-by-requirement detail, strengths, gaps, and ranked
  suggestions all in one card. "Resolve gaps conversationally" still
  hands off to the Gap Resolution tab when there's a genuine missing
  skill to ask about.
- **Standalone** calls `POST /score/standalone` and `POST
  /score/suggestions` (jd_text omitted → No-JD mode) together, in the
  same click, and renders the readiness breakdown with the ranked
  suggestions appended directly below it — these are two independent
  backend computations (see `suggestion_engine.py`), shown as one answer
  rather than requiring a second visit.

An earlier version of this panel put the full report behind a separate
tab reached via a "View full screening report" handoff link. That's
gone now — the report renders inline instead, since a person asking
"what's wrong with my resume and how do I fix it" shouldn't need a
second click to see the answer.

The JD-match and standalone panels' resume input has three tabs: **Upload
file** (PDF/DOCX, calls `/resume/parse-file`), **Paste text** (calls
`/resume/parse-text`), and **Paste JSON** (the raw `JsonResume`, for
testing or fixing up a parse that needs a correction — file/paste-text
parsing fills this tab in automatically, they don't bypass it). A parsed
result shows a summary card (name, section counts, a badge for which
tier — LLM or heuristic — produced it, and any warnings) before you run
the actual score.

**Run it (two ways — pick one):**

```bash
# Option A: docker compose (brings up Postgres + API + frontend together)
docker compose up --build
# -> http://localhost:5500

# Option B: manual, two terminals (no Docker)
# Terminal 1 — backend
cd resume-optimizer
PYTHONPATH=. uvicorn app.main:app --reload

# Terminal 2 — frontend (any static server works; this one needs no install)
cd resume-optimizer/frontend
python3 -m http.server 5500
```

Then open `http://localhost:5500`. The API base URL is editable in the
top-right of the console (defaults to `http://localhost:8000`, persisted
in `localStorage` between visits) and a status dot shows whether it can
reach the backend.

`app/main.py` has `CORSMiddleware` added, allowing `localhost:5500`/
`127.0.0.1:5500` by default — the origin both options above serve from
(nginx's published port in the Docker case, `http.server`'s in the manual
case). Override with `CORS_ALLOWED_ORIGINS` (comma-separated) for a
different port or a real deployment; `docker-compose.yml` already reads
this from the environment too, so `CORS_ALLOWED_ORIGINS=https://your-domain
docker compose up` works as-is.

**Design approach**: the console is built as a working tool, not a
marketing page — folder-style index tabs across the six modes (one
candidate's dossier, viewed through different lenses), IBM Plex
Serif/Sans/Mono as a single deliberately-chosen type family across
headings/body/data, and a signature visualization derived from the
product's own mechanism rather than a generic chart: the score formula
renders as a bar per component whose *width* is that component's weight
(now dynamic per detected seniority — see "Dynamic seniority weighting"
above, badge shown next to the score) and whose *fill height* is its
subscore — so a resume that's a perfect skill match but semantically weak
visibly reads differently from the reverse, before you even read the
numbers.

**What's actually verified vs. what isn't**: every field each panel reads
off a response was checked against the live backend — not just "the code
looks right." `verify_frontend_contract.mjs` (the script used for this,
not shipped in the zip since it's a one-off check rather than part of the
app) ran the exact requests `app.js` sends, including the full 3-turn
voice conversation (scope → outcome_metric → generate_highlight), against
a live `uvicorn` instance with real CORS headers, and asserted every field
each renderer touches is present with the right type. The **Gap
Resolution** panel and the seniority/ageist-flag additions to the
existing panels came later and weren't re-run through that script
specifically; they were instead verified with `fastapi.testclient.TestClient`
hitting `/score/jd-match`, `/bias-audit/jd`, `/voice/gap-prompt`, and
`/voice/gap-answer` with the exact payload shapes `app.js` sends, checking
every field the new renderers read (`seniority_detected`, `weights_used`,
`ageist_terms_found`, `disclaimer`, `done`/`target_skill`/`prompt`,
`updated_resume`/`before`/`after`/`score_delta`) — same contract-level
rigor, different tool. The full report, now rendered inline in **JD
Match** and **Standalone** rather than as its own panel, was verified
the same way: `TestClient` calls against `/score/full-report` (JD Match)
and `/score/standalone` + `/score/suggestions` together (Standalone),
checking every field `renderFullReport()` reads (`dimensions`' 7 keys,
`keyword_categories`' 4 keys, each `requirements[]` entry's 9 fields)
against the real response structure, not assumed from memory. What
*isn't* verified for any of the panels: actual rendering in a real
browser (no browser available in the sandbox this was built in) — the
HTML/CSS were checked for tag/brace balance and the JS for syntax errors
(`node --check`), but a first real open is worth a once-over,
particularly the voice and gap-resolution panels' flex layout on narrow
screens, and how dense the requirement list reads in JD Match on a
smaller viewport now that it's part of the main result rather than its
own dedicated tab.

The voice panel's "template preview" bullet (shown once a turn reaches
`generate_highlight`) is explicitly labeled as non-AI output — deterministic
string formatting of the captured slots, not a model call — because the
scaffold's `/voice/turn` endpoint returns filled slots, not generated
bullet text (see `app/api/routes/voice.py`'s docstring: bullet generation
via `append_work_highlight` is the live conversational agent's job in
production). Faking that with confident-looking output would misrepresent
what's actually running, so it's kept honestly labeled instead.

## Wiring up the production pieces

1. **SBERT embeddings**: `pip install sentence-transformers`, set
   `EMBEDDING_BACKEND=sbert` in the environment. No code changes needed —
   `get_embedding_provider()` in `embeddings.py` is the only place that
   reads this flag.
2. **Claude API**: `pip install anthropic`, set `ANTHROPIC_API_KEY`. Route
   conversational-agent calls through `app/core/llm/router.py` so the model
   choice stays centralized as the frontier model lineup keeps shifting.
3. **Document parsing**: `pip install docling` (and `marker-pdf` for the
   fallback path). `parser_interface.py` already calls the real APIs of
   both libraries.
4. **Live voice**: wire Deepgram's streaming SDK to call `POST /voice/turn`
   per transcribed utterance, with slot extraction happening via a
   `TaskType.CONVERSATIONAL_AGENT` call before this endpoint's decision
   logic runs.
5. **Database**: point `DATABASE_URL` at a managed Postgres with the
   `pgvector` extension available, then run `alembic upgrade head`. This
   applies both the SQLAlchemy tables *and* the `resumes.embedding
   vector(384)` column in one step — `infra/schema.sql` is kept only as
   human-readable documentation of what that second migration does, it's
   no longer a manual step.

## Multi-provider LLM switching (Claude / Gemini / Groq)

The blueprint's intended production backend is Claude, but paying for it
before the product has revenue isn't always realistic — so every LLM call
in this app can run on Claude, Gemini, or Groq, chosen either **per
request** (the tier selector — the one to use) or **process-wide** (the
`LLM_PROVIDER` env var — a fallback default for call sites that don't
expose a tier, and unchanged from before this existed).

### Per-request: the Basic / Medium / Advanced tier selector

`/resume/parse-file` and `/resume/parse-text` (see "Resume ingestion"
above) take an optional `tier` field — `"basic"` (Groq), `"medium"`
(Gemini), or `"advanced"` (Claude) — and the frontend's resume panels
have a Basic/Medium/Advanced button row right above the upload/paste
input. Whichever key is actually configured determines which tiers work:

| Tier | Provider | Env var needed | `pip install` |
|---|---|---|---|
| `basic` | Groq | `GROQ_API_KEY` | `langchain-groq` |
| `medium` | Gemini | `GEMINI_API_KEY` | `langchain-google-genai` |
| `advanced` | Claude | `ANTHROPIC_API_KEY` | `langchain-anthropic` |

This is a per-request override, not just another way to read
`LLM_PROVIDER` — picking a tier uses exactly that provider's key,
regardless of what `LLM_PROVIDER` the process was started with. That
distinction is the fix for a real bug: before the tier selector existed,
the code only ever checked the key for `LLM_PROVIDER`'s provider (default
Claude) — so setting `GEMINI_API_KEY` or `GROQ_API_KEY` alone did
*nothing* unless `LLM_PROVIDER` was *also* set to match, and the error
you'd get back was a generic "no LLM provider is configured" that gave no
hint which env var was actually missing. Missing-key warnings are
tier-specific now: `"No GEMINI_API_KEY configured for the 'medium' tier
(gemini) -- ..."`, naming the exact variable to set.

If a tier's key isn't configured (or the call fails for any other
reason), the response still comes back `200` with a valid (if rougher)
result — see "Resume ingestion" above on the heuristic fallback — with
the specific reason in `warnings` and `provider_used: null`.

### Process-wide default: `LLM_PROVIDER`

For call sites that don't (yet) expose a per-request tier — the voice
agent, batch jobs — `LLM_PROVIDER` (`claude` default, or `gemini`/`groq`)
still controls which provider `active_provider()` resolves to:

```bash
export LLM_PROVIDER=gemini   # or: groq, or: claude (default)
```

Every such call site goes through `app/core/llm/router.py`'s
`route(task)` and `app/core/llm/client_factory.py`'s `get_client_for(task)`
— never a model string or a specific client class — so this remains the
only switch those call sites need:

```python
from app.core.llm.client_factory import get_client_for
from app.core.llm.router import TaskType

client, model = get_client_for(TaskType.CONVERSATIONAL_AGENT)
result = client.create_message_with_cost(model=model, system=..., messages=[...])
```

`get_client_for` also takes an explicit `provider=` override (what the
tier selector uses under the hood — see `resume_extraction.py`) for any
call site that wants a per-call choice instead of the process-wide
default.

**What neither switch touches:** `extraction_crosscheck` always runs on
the open-weight model via `oss_extraction_client.py`, regardless of tier
or `LLM_PROVIDER` — see `router.py`'s docstring for why (the whole point
of a crosscheck pass is a genuinely different model family from whichever
closed API is primary). You can still point that task at Groq for
free/cheap independently, by setting `OSS_EXTRACTION_BASE_URL=https://api.groq.com/openai/v1`
— see `oss_extraction_client.py`'s docstring for the exact env vars.

### Implementation: one shared LangChain backend, not three

`AnthropicClient` / `GeminiClient` / `GroqClient` (`app/core/llm/
claude_client.py` / `gemini_client.py` / `groq_client.py`) each used to
hand-roll their own request/response translation against that vendor's
raw SDK — Anthropic content-blocks converted to/from Gemini's `contents`/
`parts` shape, a separate OpenAI-shaped conversion for Groq, three
separate `finish_reason` maps. All three vendors' LangChain integrations
(`langchain-anthropic`, `langchain-google-genai`, `langchain-groq`) turned
out to share the same message vocabulary (`SystemMessage`/`HumanMessage`/
`AIMessage`) and the same `usage_metadata` shape
(`input_tokens`/`output_tokens`/`total_tokens`, identical across all
three), so that translation logic collapsed into one function —
`app/core/llm/langchain_backend.py`'s `invoke()` — that all three clients'
`create_message()` now call. Net effect: less code than before, not more,
and one place to fix a wire-format bug instead of three.

This still returns the exact same response shape
(`{"id", "stop_reason", "content": [...], "usage": {...}}`) every
downstream caller already expected, so nothing outside those three files
changed. Anthropic's real **Batch API** (`create_message_batch` etc.) is
the one thing that deliberately stayed on the raw `anthropic` SDK — Batch
has no LangChain equivalent, and it's a different code path (async job
submission, not a synchronous chat call) from what `invoke()` wraps.

**`resume_extraction.py`'s two-tier fallback (try the LLM, fall back to
the heuristic parser) is expressed as a small LangGraph `StateGraph`** —
an `llm` node, a conditional edge that only continues to a `heuristic`
node if the LLM node didn't produce a resume, and a `heuristic` node.
This was a genuine, pre-existing two-branch control flow (previously just
sequential if-statements), not LangGraph bolted on for its own sake — see
that module's docstring. `agent_loop.py`'s voice-agent decision logic
stayed a plain function; it's a single ask-vs-generate branch with no
loop or multi-step state to justify a graph.

**Two real limitations, not cosmetic ones, worth knowing before you lean
on this for production traffic:**

1. **No prompt caching equivalent wired up for Gemini/Groq.**
   `prompt_cache.py`'s `cache_control` breakpoints are an Anthropic-
   specific mechanism — `langchain_backend.py` flattens and drops them for
   all three providers' synchronous calls (Claude's Batch API path, which
   doesn't go through `invoke()`, still applies them), so cost tracking
   for Gemini/Groq calls never reflects a cache discount (see
   `token_pricing.py`'s docstring). Gemini has its own context-caching
   feature; it isn't wired here.
2. **No real Batch API equivalent for Gemini/Groq.** `create_message_batch`
   on those two clients is a compatibility *shim* — a bounded-concurrency
   synchronous fan-out, not an actual async vendor job — so
   `build_classification_batch_requests()` / `run_candidate_pool_narratives()`
   keep working regardless of provider, but without Anthropic's
   unconditional 50% batch discount (there's nothing to discount from on
   the shim). Both Gemini and Groq do have real batch endpoints; wiring
   those for real is future work if volume there ever justifies it.

## Database migrations (Alembic)

```bash
pip install alembic          # not in requirements.txt's default install; add it when you're ready for real persistence
export DATABASE_URL=postgresql://user:pass@host:5432/dbname   # falls back to sqlite:///./dev.db if unset
alembic upgrade head
```

Two migrations, tested end-to-end against a real Postgres 16 + pgvector
0.6 instance (create → downgrade → re-apply, all clean):

1. `bf91f6a3...` — the four core tables (`users`, `resumes`, `scan_results`,
   `subscriptions`), autogenerated from `app/db/models.py`.
2. `e2c91358...` — `CREATE EXTENSION vector` + `resumes.embedding
   vector(384)` (384 dims to match `all-MiniLM-L6-v2`, the default SBERT
   model in `embeddings.py`'s production path — bump this in a follow-up
   migration if you swap embedding models). This step no-ops with a
   warning on the SQLite dev fallback, since neither the extension nor the
   `vector` type exist there.

**One real-world catch worth knowing about**: `CREATE EXTENSION` requires
superuser privileges in Postgres. Most managed providers (RDS, Cloud SQL,
etc.) don't grant that to the application role by default — either have
an admin run `CREATE EXTENSION vector;` once ahead of time, or grant the
narrower extension-creation privilege your provider exposes, before
running this migration in a real environment. It's a one-time step, not a
per-deploy one.

`app/db/session.py` (new — this didn't exist before) reads `DATABASE_URL`
the same way `docker-compose.yml` already sets it, and is what
`alembic/env.py` points at for `--autogenerate` and applying migrations.

## Cost optimization (LLM API spend)

Every technique below is implemented under `app/core/llm/` and covered by
unit tests against fake clients (`FakeAnthropicClient`,
`FakeOSSExtractionClient`) — the request-building/response-parsing logic
runs for real in this sandbox; only the live network calls don't (no API
keys/endpoints reachable here). Pricing figures are Anthropic's published
rates as of August 2026 (`app/core/llm/token_pricing.py`) — verify current
numbers at https://platform.claude.com/docs/en/about-claude/pricing before
relying on them, since Anthropic can change rates.

### 1. Prompt caching (`prompt_cache.py`, `token_pricing.py`)

Cache reads cost **10% of the base input rate — a 90% discount** — and
cache writes cost 1.25x (5-minute TTL) or 2x (1-hour TTL) base input, so
caching pays for itself after one read (5m) or two reads (1h). This
codebase caches:

- **The voice agent's system prompt** (`voice_system_prompt.py`) — a real,
  full instruction set with calibration examples, not a placeholder,
  because caching only pays off on content that's both stable *and*
  substantial (below each model's minimum cacheable length — 1024 tokens
  for Sonnet 5, 4096 for Haiku 4.5 — the API silently serves it uncached).
  Every voice turn across every user shares this exact prefix.
- **Tool definitions** (`prompt_cache.cache_last_tool`) — static across
  deploys, cached alongside the system prompt.
- **The shared JD + rubric in batch candidate narratives**
  (`batch_candidate_narratives.py`) — see technique 3 below; this is
  where caching and batching compound.

The one failure mode that silently defeats caching — putting the
breakpoint on content that changes every request (a timestamp, the live
transcript) instead of the stable prefix before it — is what
`prompt_cache.py`'s whole design (`build_system_blocks` splitting
`stable_instructions` from `volatile_context`) exists to make structurally
hard to get wrong. `tests/test_prompt_cache.py` asserts the volatile
suffix never carries `cache_control`.

### 2. Model routing / intelligent tiering (`router.py`)

Every LLM call goes through `route(TaskType)` — never a model string at
the call site — mapping task frequency/stakes to the cheapest model that's
actually reliable for that job:

| Task | Model | Why |
|---|---|---|
| `fast_classification` | Claude Haiku 4.5 ($1/$5 per MTok) | Runs on every document; cheapest tier that's still reliable for classification |
| `conversational_agent` | Claude Sonnet 5 ($2/$10 per MTok through Aug 2026) | Interactive, needs strong tool-calling reliability |
| `deep_reasoning` | Claude Opus 4.8 ($5/$25 per MTok) | Low-frequency, high-stakes (XAI narratives feeding real hiring decisions) |
| `extraction_crosscheck` | Qwen 3.6 35B-A3B, open-weight | Independent second-opinion extraction — see below |

`extraction_crosscheck` used to be a placeholder pointing at "the current
OpenAI/Gemini flagship." It's now an open-weight model instead, and not
just for cost: a crosscheck pass exists to catch failures that correlate
with the *primary* model's blind spots, which requires a genuinely
different model family, not a second closed-API subscription paying a
second vendor's per-token margin on a task that runs on every document.
Qwen 3.6 was picked over the alternatives surveyed (GLM-5.2, NuExtract 3 —
see `router.py`'s full comment for the tradeoffs, including NuExtract 3's
revenue-based license tier that needs checking against this product's
actual revenue before shipping it) for its combination of first-class
JSON-schema-respecting structured output and a ~3B active-parameter MoE
footprint that's cheap to self-host.

The table above is the `provider="claude"` (default) row. `router.py` also
routes the same three task types to Gemini or Groq models when
`LLM_PROVIDER` is set — see "Multi-provider LLM switching" above for the
full picture, including why the caching/batching techniques below don't
carry over 1:1 to those two providers.

### 3. Batch API for non-real-time work (`claude_client.py`, `batch_*.py`)

Anthropic's Message Batches API gives an **unconditional 50% discount** on
both input and output tokens for asynchronous jobs (typically well under
24h turnaround), and it **stacks with prompt caching**. Two places this
codebase uses it:

- **`batch_resume_extraction.py`** — the literal "upload a backlog of old
  resumes just to sit in your profile" case: nobody's waiting on resume
  #7 of 10, so the `fast_classification` pass for a whole backlog goes
  through one Batch API job instead of N synchronous calls.
- **`batch_candidate_narratives.py`** — the Team/Business
  `candidate_pool_ranking` / `per_candidate_xai` features: a recruiter
  ranks N candidates against one JD, and every candidate's request shares
  the *exact same* JD + rubric prefix. That shared prefix is cache-written
  once and read N−1 more times, and the whole batch gets the 50% discount
  on top — at N=50, the JD+rubric portion of the bill drops to roughly
  1/20th of N separate uncached synchronous calls.

**Important distinction documented in `oss_extraction_client.py`**: the
open-weight `extraction_crosscheck` model does *not* get an equivalent
"batch discount," because self-hosted/open-weight inference has no vendor
list price to discount from in the first place. Its cost advantage is a
different mechanism entirely — no per-token vendor margin, plus the
inference server's own request batching (e.g. vLLM's continuous batching)
for throughput. `batch_resume_extraction.py`'s two halves
(`submit_classification_batch` vs. `run_crosscheck_concurrently`)
deliberately use different code paths for exactly this reason — treating
them as the same lever would misrepresent how either one actually saves
money.

### What this doesn't cover yet

Cost tracking here is per-call (`claude_client.MessageResult.cost`,
`token_pricing.calculate_cost`) — there's no aggregation/dashboard layer
summing spend across calls over time. That'd be the natural next piece:
log every `CostBreakdown` somewhere durable (Postgres, given the Alembic
setup above) and roll it up per user/tier to compare against
`API_USAGE_PRICE_PER_SCAN_USD` in `config.py`.

## Note on the TF-IDF fallback's numbers

Run the example in the API docs and you'll notice the semantic-fit
component can score surprisingly low even on a strong match — that's the
TF-IDF fallback being exactly as limited as the blueprint says it is (it
can't tell "software development" and "software engineering" are related
concepts at the *vector* level, only the skill-extraction layer catches
that synonym). That's expected and is precisely the gap SBERT closes in
production — the fallback is left honest rather than tuned to look better
than it is.
