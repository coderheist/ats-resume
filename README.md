# Dual-Mode AI ATS & Conversational Resume Optimizer — reference architecture

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
      experience_match.py  # years-required vs. years-held
      seniority.py           # JD seniority detection -> dynamic weight profile
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
      batch_resume_extraction.py    # bulk classification/crosscheck batch jobs
      batch_candidate_narratives.py # bulk XAI narrative batch jobs
    parsing/
      file_extraction.py        # .pdf/.docx -> raw text (pypdf/python-docx)
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
pip install -r requirements.txt
PYTHONPATH=. pytest tests/ -v          # 153 tests, all passing, no external services needed
PYTHONPATH=. uvicorn app.main:app --reload
# -> http://localhost:8000/docs for interactive API docs
```

For local development, copy `.env.example` to `.env` and fill in the API key
for the provider you want to use. The app loads `.env` at startup without
overriding variables already supplied by the process environment.

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
| `POST /resume/parse-file` | Upload a resume (.pdf/.docx) → structured JsonResume |
| `POST /resume/parse-text` | Paste resume text directly → structured JsonResume |
| `POST /score/jd-match` | Mode 1 — resume vs. JD hybrid score + XAI breakdown |
| `POST /score/standalone` | Mode 2 — JD-less ATS readiness score |
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

## Frontend

`frontend/` is a static, zero-build reference console (plain HTML/CSS/JS,
no npm install) covering all nine endpoints above: resume upload/parse,
JD match, standalone readiness, bias audit, the voice-editing agent loop,
the interactive gap-resolution loop, and pricing.

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
rigor, different tool. What *isn't* verified for either: actual rendering
in a real browser (no browser available in the sandbox this was built
in) — the HTML/CSS were checked for tag/brace balance and the JS for
syntax errors (`node --check`), but a first real open is worth a
once-over, particularly the voice and gap-resolution panels' flex layout
on narrow screens.

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
