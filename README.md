# Resume Optimizer

**Dual-mode AI ATS analysis and conversational resume optimization.**

A FastAPI backend and React frontend that score a resume two ways — against a
specific job description, or on its own for general ATS readiness — and explain
every number they produce. Built around an explainable scoring engine that never
returns a bare score without the breakdown behind it.

```
Python 3.11+  ·  FastAPI  ·  SQLAlchemy + Alembic  ·  Postgres/pgvector
React 18  ·  Vite  ·  Vitest  ·  Firebase Auth  ·  Razorpay
```

---

## Table of contents

- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Architecture at a glance](#architecture-at-a-glance)
- [API surface](#api-surface)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Documentation](#documentation)
- [Project status](#project-status)

---

## What it does

### Mode 1 — JD match (`POST /score/full-report`)

Extracts requirements from a job description, tiers them
(knockout / critical / important / preferred / optional), matches each one
against evidence in the resume, and produces a weighted seven-dimension score:

| Dimension | Weight |
| --- | --- |
| Knockout requirements | 30% |
| Technical skills | 20% |
| Semantic fit | 20% |
| Experience match | 10% |
| Project relevance | 10% |
| Education match | 5% |
| ATS readability | 5% |

Every requirement comes back with its match status, evidence strength, and where
in the resume the evidence was found — so a low score is always traceable to
specific, fixable gaps.

### Mode 2 — Standalone readiness (`POST /score/standalone`)

No job description required. Scores structural completeness, quantified-metric
density, action-verb density, active-voice ratio, and skill coverage against an
inferred role, weighted into a single readiness score.

### Supporting capabilities

- **Resume ingestion** — PDF/DOCX upload or pasted text, normalized into the
  [JSON Resume](https://jsonresume.org/) schema, with layout/table/image risk
  analysis on uploads.
- **Top-5 suggestions** — ranked, impact-estimated improvements in either mode,
  with deterministic template phrasing by default and an optional LLM pass.
- **JD bias audit** — flags biased or exclusionary language in job descriptions.
- **Voice agent loop** — slot-filling dialogue scaffold plus an interactive
  gap-resolution loop that asks about missing skills and re-scores after each answer.
- **Accounts, history, billing** — Firebase Auth, saved scan history, tiered
  entitlements, and Razorpay checkout.

---

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the React frontend)

### Backend

```bash
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # optional — every value has a working default

uvicorn app.main:app --reload
```

The API is now on <http://localhost:8000>, with interactive docs at
<http://localhost:8000/docs>.

**Nothing in `.env` is required to start.** With no configuration at all the app
runs against a local SQLite file, uses the built-in TF-IDF embedding fallback,
and returns deterministic template text wherever an LLM would otherwise be
called. Optional integrations degrade to a clear `503` on their own routes
rather than preventing startup.

### Frontend

```bash
cd frontend-react
npm install
npm run dev                       # http://localhost:5174
```

Vite proxies API calls to `:8000` in dev mode, so no CORS configuration is needed
until you run `npm run preview` against a production build.

For a production build, set your real domain — canonical URLs, social preview
tags, and the sitemap all derive from it:

```bash
VITE_SITE_URL=https://yourdomain.com npm run build
```

This builds the client, then prerenders every public route to static HTML so
search engines and social crawlers receive real content rather than an empty
`<div id="root">`. See [docs/SEO.md](docs/SEO.md).

### Docker

```bash
docker compose up
```

Brings up Postgres + pgvector, the API on `:8000`, the static console on `:5500`,
and the React app on `:5174`.

### Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for the full local setup, and
[docs/CONFIGURATION.md](docs/CONFIGURATION.md) for every environment variable.

---

## Architecture at a glance

```
┌─────────────────────┐     ┌─────────────────────┐
│  frontend-react/    │     │  frontend/          │
│  React + Vite SPA   │     │  Static JS console  │
└──────────┬──────────┘     └──────────┬──────────┘
           │        HTTP + Bearer JWT  │
           └─────────────┬─────────────┘
                         ▼
        ┌────────────────────────────────┐
        │  FastAPI  (app/main.py)        │
        │  rate limit → CORS → routers   │
        └────────────────┬───────────────┘
                         ▼
   ┌──────────┬──────────┬──────────┬──────────┐
   │ parsing  │ scoring  │ llm      │ services │
   │ PDF/DOCX │ 7-dim    │ provider │ entitle- │
   │ → JSON   │ engine   │ routing  │ ments,   │
   │ Resume   │ + XAI    │          │ history  │
   └──────────┴─────┬────┴──────────┴─────┬────┘
                    ▼                     ▼
        ┌───────────────────┐   ┌──────────────────┐
        │ Postgres/pgvector │   │ Claude · Gemini  │
        │ SQLAlchemy+Alembic│   │ Groq · open-wt   │
        └───────────────────┘   └──────────────────┘
```

Three design rules run through the codebase:

1. **No model string is ever hard-coded at a call site.** Every LLM call goes
   through `app/core/llm/router.py`, which maps a *task type* to a model. Swapping
   providers or model versions touches one file.
2. **Every score ships with its explanation.** Scoring functions return breakdown
   objects with per-dimension values and the weights used, not a single number.
3. **Optional dependencies degrade, they don't crash.** A missing API key means a
   heuristic fallback or a clear `503` on the affected route — never a failed startup.

Full detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## API surface

| Method | Endpoint | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | — | Liveness check |
| `POST` | `/resume/parse-file` | — | Upload PDF/DOCX → JSON Resume |
| `POST` | `/resume/parse-text` | — | Paste text → JSON Resume |
| `POST` | `/score/full-report` | optional | Seven-dimension JD screening report |
| `POST` | `/score/jd-match` | — | Simpler three-weight JD score |
| `POST` | `/score/standalone` | optional | JD-less ATS readiness score |
| `POST` | `/score/suggestions` | — | Ranked Top-5 improvements |
| `POST` | `/bias-audit/jd` | — | Job-description bias scan |
| `POST` | `/voice/turn` | — | One voice-agent dialogue turn |
| `POST` | `/voice/gap-prompt` | — | Next missing-skill question |
| `POST` | `/voice/gap-answer` | — | Apply an answer, re-score |
| `GET` | `/auth/me` | required | Profile, tier, usage this month |
| `GET` | `/history` | required | Saved scans, newest first |
| `GET` | `/billing/tiers` | — | Pricing and entitlements |
| `POST` | `/payments/create-order` | required | Open a Razorpay checkout |
| `POST` | `/payments/verify` | required | Confirm a client-side payment |
| `POST` | `/payments/webhook` | signature | Razorpay server callback |

"optional" auth means the route is fully public, but a signed-in caller gets the
scan saved to history and counted against their monthly entitlement.

Full request/response schemas in [docs/API.md](docs/API.md).

---

## Project layout

```
resume-optimizer/
├── app/
│   ├── main.py               FastAPI app, middleware order, router registration
│   ├── config.py             Pricing tiers and entitlements (single source of truth)
│   ├── api/routes/           HTTP layer — one module per domain
│   ├── core/
│   │   ├── auth/             Firebase ID token verification + FastAPI dependencies
│   │   ├── billing/          Razorpay client and signature verification
│   │   ├── bias_audit/       JD bias scanner
│   │   ├── llm/              Provider routing, clients, prompts, cost tracking
│   │   ├── parsing/          File extraction, format analysis, resume extraction
│   │   ├── scoring/          The scoring engine (see ARCHITECTURE.md)
│   │   ├── services/         Entitlements, resume store, user service
│   │   ├── voice_agent/      Slot filling, gap resolution, tool schema
│   │   └── rate_limit.py     Per-IP fixed-window limiter
│   ├── db/                   SQLAlchemy models, engine, session
│   └── schemas/              Pydantic request/response and JSON Resume models
├── frontend-react/           React SPA (Vite, Vitest, React Router, Firebase)
├── frontend/                 Static-JS developer console, no build step
├── alembic/                  Database migrations
├── infra/schema.sql          Reference DDL including the pgvector column
├── tests/                    Backend test suite
└── docs/                     Documentation (see below)
```

---

## Testing

```bash
# Backend — 335 tests
venv/Scripts/python -m pytest            # Windows
python -m pytest                         # macOS/Linux

# Frontend — 100 tests
cd frontend-react && npm test
```

Use the project virtualenv's interpreter rather than a system Python — a
different `starlette` version outside the venv causes unrelated failures in the
payment route tests.

Six tests currently fail when real credentials are present in `.env`; see
[Project status](#project-status) below.

---

## Documentation

| Document | Contents |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, scoring engine, data model, request lifecycle |
| [docs/API.md](docs/API.md) | Complete endpoint reference with schemas and examples |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every environment variable and integration setup |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local setup, testing, conventions, troubleshooting |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Docker, migrations, production checklist |
| [docs/SEO.md](docs/SEO.md) | Prerendering, metadata, structured data, post-launch checklist |
| [docs/DEVELOPMENT-HISTORY.md](docs/DEVELOPMENT-HISTORY.md) | Chronological engineering log of how the system was built |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution workflow and code standards |

---

## Project status

This is a working reference implementation. What follows is stated precisely,
because a resume tool that overstates its own accuracy would be self-defeating.

**Verified working:**

- 335 backend tests and 100 frontend tests, minus the six noted below.
- Alembic migrations applied cleanly against Postgres 16 + pgvector 0.6.
- The full scoring, parsing, suggestion, and bias-audit paths, end to end.

**Known limitations:**

| Area | Status |
| --- | --- |
| Six failing tests | `test_me_returns_503_when_firebase_not_configured` and five frontend `not configured` tests assert the *unconfigured* path. They fail once real credentials exist in `.env`. The tests need to stub the config check instead of depending on ambient environment variables. |
| Email/password auth errors | Only Google popup errors are translated to readable messages. Email/password errors surface the raw Firebase code (`auth/operation-not-allowed`). See [authContext.jsx:82](frontend-react/src/lib/authContext.jsx#L82). |
| Supabase connection | The pooler mode, SSL settings, and connection string have not been exercised against a live Supabase project. Migrations and queries are verified against local Postgres, which is the same engine. |
| Rate limiter | In-memory and per-process. Running multiple workers or replicas multiplies the effective limit. Needs Redis before horizontal scaling. |
| Voice sessions | Stored in a process-local dict. Needs Redis with a TTL for production. |
| TF-IDF embeddings | The default embedding backend is lexical, not semantic. Set `EMBEDDING_BACKEND=sbert` and install `sentence-transformers` for real semantic similarity. |
| Role ontology | Standalone-mode role inference covers technical roles only. Non-technical resumes get a neutral, un-penalized score rather than a misleading one. |

---

## License

No license file is currently present in this repository. Add one before
publishing or distributing.
