# Architecture

How the system is put together, why it is put together that way, and where the
boundaries are.

- [Design principles](#design-principles)
- [System overview](#system-overview)
- [Request lifecycle](#request-lifecycle)
- [Parsing pipeline](#parsing-pipeline)
- [Scoring engine](#scoring-engine)
- [LLM provider routing](#llm-provider-routing)
- [Data model](#data-model)
- [Authentication and authorization](#authentication-and-authorization)
- [Billing and entitlements](#billing-and-entitlements)
- [Cross-cutting concerns](#cross-cutting-concerns)
- [Known architectural limits](#known-architectural-limits)

---

## Design principles

Four rules explain most of the structural decisions in this codebase.

### 1. Model identifiers live in exactly one file

No call site anywhere names a model. Every LLM call asks
`app/core/llm/router.py` for "the model for this *task type*", and the router
maps task → provider → model. Model lineups change every few weeks; this keeps
that churn contained to a single file instead of spread across every call site.

### 2. A score is never returned without its explanation

Scoring functions return breakdown dataclasses — per-dimension values, the
weights actually used, matched and missing items, and where evidence was found —
and serialize them with `to_xai_dict()` / `to_dict()`. A candidate-facing score
that cannot be traced back to specific, fixable gaps is not useful, so the
architecture makes the opaque version harder to produce than the explained one.

### 3. Optional dependencies degrade; they never block startup

Every external integration is genuinely optional:

| Missing | Result |
| --- | --- |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` | Heuristic parse, template-phrased suggestions |
| `EMBEDDING_BACKEND=sbert` not set | TF-IDF lexical fallback |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | `503` on `/auth/me` and `/history` only |
| `RAZORPAY_*` | `503` on `/payments/*` only |
| `DATABASE_URL` | Local SQLite file with auto-created tables |

The app always starts. Public scoring and analysis endpoints work with zero
configuration.

### 4. Interfaces are written for the production swap

Several components are deliberately simpler than their production counterparts —
a keyword matcher instead of a tuned NER pipeline, a regex seniority classifier
instead of an LLM call, TF-IDF instead of LoRA-tuned SBERT. In each case the
*contract* is the production contract, so the swap is an implementation change
behind an unchanged signature. Where a simplification affects result quality, the
module docstring says so directly rather than implying more precision than exists.

---

## System overview

```
┌──────────────────────────┐   ┌──────────────────────────┐
│  frontend-react/         │   │  frontend/               │
│  React 18 + Vite SPA     │   │  Static JS console       │
│  Router, Firebase Auth,  │   │  No build step           │
│  Razorpay Checkout       │   │  Dev/debug surface       │
└────────────┬─────────────┘   └────────────┬─────────────┘
             │                              │
             │   HTTP + Authorization: Bearer <Firebase ID token>
             └───────────────┬──────────────┘
                             ▼
         ┌───────────────────────────────────────────┐
         │            FastAPI application            │
         │                                           │
         │   RateLimitMiddleware  (per-IP window)    │
         │   CORSMiddleware       (outermost)        │
         │                                           │
         │   Routers: scan · resume · bias_audit ·   │
         │            voice · billing · auth ·       │
         │            history · payments             │
         └───────────────────┬───────────────────────┘
                             ▼
    ┌────────────┬────────────┬────────────┬─────────────┐
    │  parsing   │  scoring   │    llm     │  services   │
    │            │            │            │             │
    │ file       │ hybrid     │ router     │ entitlement │
    │ extraction │ readiness  │ client     │ resume_store│
    │ format     │ screening  │ factory    │ user        │
    │ analysis   │ report     │ prompt     │             │
    │ resume     │ suggestion │ cache      │             │
    │ extraction │ engine     │ token cost │             │
    └──────┬─────┴──────┬─────┴──────┬─────┴──────┬──────┘
           │            │            │            │
           ▼            ▼            ▼            ▼
    ┌──────────────────────┐   ┌──────────────────────────┐
    │  Postgres + pgvector │   │  Claude · Gemini · Groq   │
    │  SQLAlchemy 2.0      │   │  open-weight crosscheck   │
    │  Alembic migrations  │   │  via LangChain backend    │
    └──────────────────────┘   └──────────────────────────┘
```

### Layer responsibilities

| Layer | Directory | Responsibility |
| --- | --- | --- |
| HTTP | `app/api/routes/` | Request validation, status codes, auth dependencies, persistence orchestration. No business logic. |
| Domain | `app/core/` | All scoring, parsing, routing, and billing logic. Framework-agnostic — knows nothing about FastAPI. |
| Data | `app/db/` | SQLAlchemy models, engine, session lifecycle. |
| Contracts | `app/schemas/` | Pydantic request/response models and the JSON Resume schema. |

The domain layer's independence from FastAPI is enforced by convention and
visible in imports: `app/core/auth/firebase_auth.py` raises
`AuthNotConfiguredError` and `InvalidTokenError`, and only
`app/core/auth/dependencies.py` — the HTTP adapter — translates those into `503`
and `401`.

---

## Request lifecycle

Tracing `POST /score/full-report` from a signed-in user:

```
1.  CORSMiddleware        Preflight handled and short-circuited here
                          ↓
2.  RateLimitMiddleware   Per-IP fixed window; /score/ is a limited prefix
                          ↓
3.  Pydantic              FullReportRequest validated → 422 on malformed input
                          ↓
4.  get_optional_user     Bearer token → Firebase verify → AuthenticatedUser
                          (None when absent; 401 when present but invalid)
                          ↓
5.  _resolve_user         AuthenticatedUser → local User row (created on demand)
                          ↓
6.  _enforce_entitlement  Monthly scan allowance → 429 when exceeded
                          (body names the reset instant; UI pops a dialog)
                          ↓
7.  screen_resume_against_jd()
                          Requirement extraction → matching → 7 dimensions
                          ↓
8.  save_resume + save_scan_result + record_scan
                          Persisted only for signed-in callers
                          ↓
9.  report.to_dict()      Full explainable payload
```

### Middleware ordering is deliberate

`RateLimitMiddleware` is registered **before** `CORSMiddleware` in
[app/main.py](../app/main.py). Starlette executes the last-registered middleware
outermost, so registering CORS second makes it wrap the rate limiter. That is the
correct order: a CORS preflight `OPTIONS` request is handled and short-circuited
by `CORSMiddleware` before it ever reaches the rate limiter. Reversing this would
count preflight requests against the limit for no benefit.

`allow_headers` must include `Authorization`. Without it, a browser's preflight
silently strips the header on cross-origin requests and every authenticated call
looks anonymous to the backend — a bug invisible to `curl` and `TestClient`,
which is precisely why it is called out in the source.

---

## Parsing pipeline

`POST /resume/parse-file` and `/resume/parse-text` turn a document into a
`JsonResume`. The pipeline is **deterministic-first**, orchestrated as a small
LangGraph graph in `app/core/parsing/resume_extraction.py`.

```
        PDF/DOCX bytes  or  pasted text
                    │
                    ▼
    ┌───────────────────────────────┐
    │  file_extraction.extract_text │  pypdf / python-docx
    │  (uploads only)               │  10 MB cap, 413 over
    └───────────────┬───────────────┘
                    │
                    ├──────────────────┐
                    ▼                  ▼
    ┌───────────────────────┐   ┌──────────────────────┐
    │ _heuristic_extract    │   │ format_analysis      │
    │ regex + section       │   │ layout/table/image   │
    │ headers + bullets     │   │ risk flags           │
    └───────────┬───────────┘   └──────────┬───────────┘
                ▼                          │  informational only,
    ┌───────────────────────┐              │  never fails the request
    │ compute_confidence()  │              │
    │ 5 auditable signals   │              │
    └───────────┬───────────┘              │
                │                          │
       ┌────────┴────────┐                 │
       │                 │                 │
  above threshold   below threshold        │
  and no explicit   OR explicit tier       │
  tier requested    requested              │
       │                 │                 │
       │                 ▼                 │
       │   ┌──────────────────────────┐    │
       │   │ LLM extraction           │    │
       │   │ TaskType.RESUME_EXTRACTION│   │
       │   │ failure → keep heuristic │    │
       │   │ reason → warnings[]      │    │
       │   └──────────┬───────────────┘    │
       │              │                    │
       └──────┬───────┘                    │
              ▼                            ▼
        ResumeParseResponse { resume, parse_method,
                              provider_used, warnings,
                              format_analysis }
```

### The confidence gate

`app/core/parsing/parse_confidence.py` scores the heuristic parse on five
signals, each worth a fixed share:

| Signal | Weight |
| --- | --- |
| Contact info found (email or phone) | 0.15 |
| At least one structural section found | 0.20 |
| Most work entries have position **and** start date | 0.25 |
| At least one work highlight extracted | 0.20 |
| Extracted structure isn't tiny relative to raw text | 0.20 |

Nothing here is ML-based — a gate that decides whether an LLM call is warranted
must not itself cost an LLM call. The threshold is deliberately conservative:
one extra LLM call is cheaper than silently showing a user a wrong parse.

This ordering matters commercially. An earlier design ran the LLM first and fell
back to the heuristic on failure, meaning every upload cost an LLM call
regardless of how clean the resume was. The target is **zero** LLM calls on the
default free path.

An explicitly requested tier always escalates to the LLM regardless of
confidence — an explicit request for higher quality should not be silently
downgraded.

### Error handling contract

Both parse routes are structurally incapable of returning a 500 for a bad
document. Extraction failure, analysis failure, and an unparseable-but-valid file
(a scanned image-only PDF, say) all return a `200` with an empty resume and a
plain-language `warnings` entry. Only genuinely unsupported file types produce an
error status (`422`), oversized uploads a `413`, and empty ones a `400`.

---

## Scoring engine

`app/core/scoring/` holds the whole engine. Two entry points, sharing components.

### Mode 1 — Screening report (`screening_report.py`)

The primary product surface. Three layers:

```
Layer 1  jd_requirement_extractor.py
         Read the JD like a recruiter, before touching the resume.
         Extracts skills, years-required, education-level.
         Tiers each by the JD's own wording:

           knockout   "required", "must have", "mandatory", "at least X years"
           critical   reserved for a finer-grained pass
           important  mentioned plainly, no strong cue  ← default
           preferred  "preferred", "nice to have", "bonus", "plus"
           optional   reserved

         The same skill can be a knockout in one JD and preferred in
         another. Tier comes from the sentence, not the skill.
                              │
                              ▼
Layer 2  requirement_matching.py
         Not just "is it present" but "how strongly is it demonstrated,
         and where". A skills-list mention and a work bullet with real
         implementation detail score very differently.

         Presence and mandatoriness are independent axes. A knockout-tier
         requirement that is fully matched is simply MATCHED. Only a
         mandatory requirement that *fails* becomes KNOCKOUT_RISK.
                              │
                              ▼
Layer 3  screening_report.py
         Seven weighted dimensions → overall score + classification
```

| Dimension | Weight | Source |
| --- | --- | --- |
| Knockout requirements | 0.30 | Layer 2 statuses |
| Technical skills | 0.20 | Tier-weighted match coverage |
| Semantic fit | 0.20 | `embeddings.py` |
| Experience match | 0.10 | `experience_match.py` |
| Project relevance | 0.10 | `project_relevance.py` |
| Education match | 0.05 | `education_match.py` |
| ATS readability | 0.05 | `format_analysis` risk count + structure |

Requirement-tier weights inside the technical-skills dimension: critical 1.0,
important 0.75, preferred 0.4, optional 0.2.

The response carries `strengths`, `where_you_lack`, `relevance_gaps`,
`suggestions`, `top_reasons_for_score`, `top_improvements_needed`, and
`keyword_stuffing_flags` alongside the numbers.

### Mode 1b — Hybrid score (`hybrid_score.py`)

The simpler three-weight formula, kept unchanged for existing callers:

```
FinalScore = W_semantic · semantic_similarity
           + W_skill    · skill_match
           + W_experience · experience_match
```

Weights are **not** constant. They shift with the JD's detected seniority
(`seniority.py`), because a "5+ years required" line matters far less for an
entry-level posting than a staff-level one, and scoring a fresher on a
senior-calibrated experience weight penalizes them unfairly:

| Seniority | Semantic | Skill | Experience |
| --- | --- | --- | --- |
| Entry | 0.55 | 0.35 | 0.10 |
| Mid *(default)* | 0.50 | 0.30 | 0.20 |
| Senior | 0.45 | 0.25 | 0.30 |
| Staff | 0.40 | 0.20 | 0.40 |

Content-quality signals (unquantified bullets, weak verbs, passive voice) are
computed and exposed on the breakdown but deliberately **do not** feed
`final_score` — there is no weight for them in the formula, and quietly baking
them in would misrepresent what a JD-match score means. They exist so the
suggestion engine has bullet-level detail available in either mode.

### Mode 2 — Standalone readiness (`readiness.py`)

No JD. Five weighted checks:

| Check | Weight |
| --- | --- |
| Structural completeness vs. JSON Resume schema | 0.30 |
| Ontology skill coverage for the inferred role | 0.25 |
| Quantified-metric density in work highlights | 0.20 |
| Action-verb density in work highlights | 0.15 |
| Active-voice ratio | 0.10 |

The role ontology is built strictly from ids that exist in
`skill_extraction.py`'s `CANONICAL_SKILLS` map, so an ontology entry can never
silently fail to match. It is tech-role-scoped, because no equivalent canonical
vocabulary exists in this codebase for marketing, sales, finance, or HR. A resume
that overlaps no known role gets `inferred_role: null` and a **neutral,
un-penalized** coverage score. An incomplete ontology is not the same thing as a
real skill gap, and scoring it as if it were would be exactly the false precision
this project avoids elsewhere.

### Shared components

| Module | Role |
| --- | --- |
| `embeddings.py` | Provider abstraction. TF-IDF default; `EMBEDDING_BACKEND=sbert` swaps in Sentence-BERT. `scaled_similarity()` clamps to `[0,1]`. |
| `skill_extraction.py` | Synonym-collapsing canonical matcher ("software development" and "software engineering" → one id). Production swap: a domain-tuned spaCy NER pipeline behind the same contract. |
| `experience_match.py` | Years-required parsing including explicit ranges; flags unparseable date roles rather than guessing. |
| `seniority.py` | Transparent regex/keyword classifier. Swappable for an LLM call behind the same signature. |
| `content_quality.py` | Metric density, action verbs, passive voice. |
| `suggestion_engine.py` | Ranks improvements by estimated score impact across both modes. |

---

## LLM provider routing

`app/core/llm/router.py` is the single point where task types map to models.

### Task types

| Task | Frequency | Rationale |
| --- | --- | --- |
| `CONVERSATIONAL_AGENT` | High | Voice dialogue; needs tool-calling reliability |
| `RESUME_EXTRACTION` | Every escalated upload | Needs instruction-following, not raw speed |
| `FAST_CLASSIFICATION` | Every document | Cheapest reliable model |
| `DEEP_REASONING` | Low | XAI narratives, bias reasoning — high stakes |
| `EXTRACTION_CROSSCHECK` | Selective | Open-weight, deliberately outside the provider switch |

### Provider switching

`LLM_PROVIDER` (`claude` | `gemini` | `groq`) sets the process-wide default. The
parse routes additionally accept a per-request `tier` that always wins:

| Tier | Provider | Required key |
| --- | --- | --- |
| `basic` | Groq | `GROQ_API_KEY` |
| `medium` | Gemini | `GEMINI_API_KEY` |
| `advanced` | Claude | `ANTHROPIC_API_KEY` |

An invalid tier is a `400`, never a silent fallback to heuristic — a caller who
asked for a specific quality level should be told their request was malformed,
not quietly given something else.

`EXTRACTION_CROSSCHECK` is intentionally excluded from this switch. The entire
point of a crosscheck is running the same extraction through a genuinely
different model family so the two do not share correlated failure modes; routing
it to whichever provider is already primary would defeat that. It goes through
`oss_extraction_client.py` to any OpenAI-compatible endpoint via
`OSS_EXTRACTION_BASE_URL`.

### One shared backend

All three providers route through `langchain_backend.py` rather than three
hand-rolled request/response translation layers. `client_factory.get_client_for(task)`
returns a `(client, model)` pair; callers never construct a provider-specific client.

### Cost controls

| Mechanism | Module |
| --- | --- |
| Deterministic-first parsing (target: 0 LLM calls on the free path) | `parsing/resume_extraction.py` |
| Prompt caching | `llm/prompt_cache.py` |
| Per-task model tiering | `llm/router.py` |
| Batch API for non-real-time work (≈50% discount) | `llm/claude_client.py`, `llm/batch_*.py` |
| Token/cost accounting into `usage_logs` | `llm/token_pricing.py` |

---

## Data model

```
users
  id             uuid pk
  firebase_uid   unique, nullable, indexed   ← external identity
  email          unique, not null, indexed   ← display + fallback lookup
  name, created_at
    │
    ├──1:N──> resumes
    │           id uuid pk, user_id fk
    │           data      JSON   ← canonical JsonResume content
    │           embedding vector(384)  ← declared in infra/schema.sql
    │           updated_at
    │             │
    │             └──1:N──> scan_results
    │                         mode "jd_match" | "standalone"
    │                         jd_text, final_score
    │                         breakdown JSON  ← full XAI payload
    │                         created_at
    │
    ├──1:1──> subscriptions
    │           tier, active, renews_at  ← renews_at is a PASS's expiry
    │                                      instant (purchase time + the
    │                                      tier's duration_days), not a
    │                                      recurring-billing anchor
    │
    ├──1:N──> payments
    │           tier, billing_cycle  ← despite the name, holds the pass
    │                                   length sold ("7d"/"30d"/"90d"),
    │                                   kept for reconciliation only
    │           amount (smallest currency unit), currency
    │           razorpay_order_id   unique, indexed
    │           razorpay_payment_id unique, nullable, indexed
    │           status "created" | "paid" | "failed"
    │
    └──1:N──> usage_logs
                user_id nullable  ← anonymous requests still recorded
                action "jd_match_scan" | "standalone_scan" | "ai_rewrite" | "llm_call"
                provider, input_tokens, output_tokens, cost_usd
                created_at indexed
```

Several choices here are load-bearing:

- **Resume content is JSON, not normalized tables.** The canonical form is the
  JSON Resume schema. Normalizing it would mean reassembling it on every read for
  no query benefit the app actually needs.
- **`embedding` is declared in `infra/schema.sql`, not in `models.py`.** This
  keeps the SQLAlchemy models free of a hard dependency on the `pgvector` Python
  package, so the app runs on SQLite without it.
- **Entitlements are computed by counting `usage_logs`, not from a counter
  column.** A separate counter can drift out of sync with what actually happened;
  a count of real rows cannot.
- **`usage_logs.user_id` is nullable.** An anonymous scoring request is still
  worth recording for aggregate cost visibility — it simply never counts against
  anyone's monthly allowance.
- **Money is stored in the smallest currency unit** (cents, paise), matching what
  Razorpay's API expects and returns. A float dollar amount would reintroduce the
  rounding questions this convention exists to avoid.
- **`payments` rows survive abandoned checkouts.** A row is created the moment an
  order is, before payment. Rows stuck at `created` are real signal, not noise.

### Development vs. production database

`app/db/session.py` branches on SQLite vs. Postgres, not on whether
`DATABASE_URL` was set:

- **SQLite** — tables auto-created, and `_heal_sqlite_schema_drift()` detects a
  stale local file (a table missing columns that `models.py` now declares) and
  recreates it. This exists because `create_all()` never adds a column to an
  existing table, so a leftover `dev.db` would otherwise cause
  `OperationalError: no such column` on the next signed-in request.
- **Postgres** — Alembic migrations are the only source of truth. Nothing in this
  module ever touches the schema.

---

## Authentication and authorization

Firebase handles account creation client-side. The backend never trusts a uid or
email from a request body — only claims from a verified signed token.

```
React                     FastAPI                    Firebase
  │                          │                          │
  ├─ signIn ─────────────────┼─────────────────────────>│
  │<──────────── ID token ───┼──────────────────────────┤
  │                          │                          │
  ├─ Authorization: Bearer ─>│                          │
  │                          ├─ verify_id_token ───────>│
  │                          │<──── decoded claims ─────┤
  │                          │                          │
  │                          ├─ get_or_create_user()    │
  │<───────── response ──────┤                          │
```

Two dependencies with deliberately different failure behavior:

| Dependency | No token | Invalid token | Not configured |
| --- | --- | --- | --- |
| `get_current_user` | `401` | `401` | `503` |
| `get_optional_user` | `None` | `401` | `None` |

`get_optional_user` returning `401` for a *present but invalid* token is
intentional. Silently treating a garbled or expired token as "anonymous" would
hide a real client-side bug instead of surfacing it.

The Firebase Admin SDK is initialized lazily from
`FIREBASE_SERVICE_ACCOUNT_JSON` — the JSON key's *content*, not a file path,
consistent with this app's "everything via env vars, nothing baked into the
image" pattern.

There is no `/register` endpoint. `GET /auth/me` materializes the local `User`
row and a free-tier `Subscription` on first call for a given `firebase_uid`,
because Firebase already handled account creation by the time it is reached.

---

## Billing and entitlements

`app/config.py` is the single source of truth for pricing, as plain frozen
dataclasses, so billing logic, upgrade prompts, and the pricing page all read the
same numbers.

Every consumer tier is a fixed-length **pass**, bought outright — there is no
auto-renewing subscription and no `billing_cycle` choice, because
`razorpay_client.py` only implements one-time orders (no Razorpay
Subscriptions/auto-debit integration). The tier itself carries a
`duration_days`, which is also what the allowance window is anchored to
(`entitlement_service.period_bounds`) rather than the calendar month — a
7-day Boost pass bought on the 28th keeps its own 7-day window instead of
resetting on the 1st.

**Consumer tiers (INR / USD):** Free (Rs 0, 5 scans + 3 rewrites/mo) · Boost
(Rs 149 / $4.99, 7-day pass, 30 scans + 30 rewrites) · Pro (Rs 399 / $12.99,
30-day pass, 100 scans + 100 rewrites) · Pro Season (Rs 999 / $29.99, 90-day
pass, 300 scans + 300 rewrites).

Two allowances are metered independently: `jd_match_scans` and `ai_rewrites`.
Scanning always runs on the same ("fast") model regardless of tier, because
the score itself is computed locally (see Scoring above) and paying more
cannot buy a different number. Rewriting is the one operation where tiers
differ in output: Free routes to the cheaper model, paid tiers to the better
one (`app/core/llm/tier_routing.py`), since the rewrite is the feature people
are actually paying for.

**Business tiers:** Team, Business — speculative placeholders from an
unshipped bias-audit product, not part of the launch ladder. Do not surface
them on a real pricing page without repricing.

### Payment flow

Razorpay is verified along **two independent paths**, either of which may
complete first:

```
Browser ──create-order──> API ──> Razorpay      Razorpay ──webhook──> API
   │                       │                        (payment.captured)
   │                       └─> Payment(status="created")      │
   │                                                          │
   └─ Checkout widget ──verify──> API                         │
        (order_id, payment_id, signature)                     │
                    │                                         │
                    └──────────┬──────────────────────────────┘
                               ▼
                    status="paid" + activate subscription
                    (idempotent — whichever arrives second is a no-op)
```

The webhook is authoritative, and is authenticated **only** by its signature —
no bearer token, since Razorpay's server is not a signed-in user. It uses
`RAZORPAY_WEBHOOK_SECRET`, a *different* secret from `RAZORPAY_KEY_SECRET`; the
two protect against different things. The webhook exists precisely because
`/verify` depends on the customer's browser staying open, and a closed tab must
not mean a real payment goes unrecorded.

---

## Cross-cutting concerns

### Rate limiting

`app/core/rate_limit.py` — an in-memory fixed-window per-IP counter, applied only
to compute/LLM-adjacent prefixes: `/resume/`, `/score/`, `/bias-audit/`,
`/voice/`. Cheap, mostly-DB reads (`/health`, `/billing/tiers`, `/auth/me`,
`/history`) are not throttled. Defaults: 60 requests / 60 seconds, both
configurable.

Written directly rather than pulled in as a dependency, consistent with this
project's general preference for owning things simple enough to own outright.

### CORS

Origins come from `CORS_ALLOWED_ORIGINS`, defaulting to the local dev ports
(`:5500`, `:5174`, `:5175`). Methods are limited to `GET` and `POST`; headers to
`Content-Type` and `Authorization`.

### Voice agent

`app/core/voice_agent/` implements slot filling (`agent_loop.py`), the
missing-skill gap-resolution loop (`gap_resolution.py`), and tool-calling schemas
(`tool_schema.py`). The `/voice/turn` endpoint currently accepts
`extracted_slots` directly so the decision logic is testable independently of a
live model call; production extracts them server-side via
`TaskType.CONVERSATIONAL_AGENT` tool calling.

---

## Known architectural limits

Stated plainly, because each is a real constraint on deployment.

| Limit | Impact | Fix |
| --- | --- | --- |
| Rate limiter is per-process, in-memory | Multiple workers/replicas each enforce their own limit, multiplying the real ceiling by worker count. Resets on restart. | Move the counter to Redis before scaling horizontally. |
| Voice sessions in a process-local dict | Sessions do not survive restart and are not shared across workers. | Redis keyed by `session_id`, TTL matched to session length. |
| TF-IDF embedding default | "Semantic" similarity is purely lexical. Numbers are directionally useful but not true semantic fit. | `EMBEDDING_BACKEND=sbert` plus `pip install sentence-transformers`. |
| Skill extraction is a keyword matcher | Misses skills phrased outside the canonical vocabulary. | Domain-tuned spaCy NER behind the same contract. |
| Role ontology covers technical roles only | Non-technical resumes get no role inference. Scored neutrally, not wrongly. | Extend `CANONICAL_SKILLS` and `ROLE_ONTOLOGY` together — an ontology id with no canonical skill can never match. |
| Pricing config is code, not data | Price changes require a deploy. | Database-backed, dashboard-editable config. |
| Supabase connection untested against a live project | Pooler mode, SSL, and connection string are documented but unexercised. Migrations and queries verified against local Postgres 16 + pgvector 0.6. | Run `alembic upgrade head` against a real project and confirm session-pooler behavior under load. |

---

## Related documents

- [API.md](API.md) — endpoint reference
- [CONFIGURATION.md](CONFIGURATION.md) — environment variables
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup and conventions
- [DEPLOYMENT.md](DEPLOYMENT.md) — production deployment
- [DEVELOPMENT-HISTORY.md](DEVELOPMENT-HISTORY.md) — how this was built, chronologically
