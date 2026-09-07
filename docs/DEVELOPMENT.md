# Development Guide

Setting up, running, testing, and extending the project locally.

- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Running the stack](#running-the-stack)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Code conventions](#code-conventions)
- [Common tasks](#common-tasks)
- [Database work](#database-work)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Tool | Version | Required for |
| --- | --- | --- |
| Python | 3.11+ | Backend |
| Node.js | 18+ | React frontend |
| Docker | any recent | Optional — local Postgres, full-stack run |

Postgres is optional locally. The app falls back to a SQLite file.

---

## Setup

### Backend

```bash
git clone <repository-url>
cd resume-optimizer

python -m venv venv
source venv/bin/activate           # Windows: venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # optional
```

### Frontend

```bash
cd frontend-react
npm install
cp .env.example .env               # optional
```

### Verify

```bash
venv/Scripts/python -m pytest -q   # Windows
python -m pytest -q                # macOS/Linux
```

**Always use the virtualenv's interpreter, not a bare `python`.** A different
`starlette` version outside the venv causes eight unrelated failures in
`tests/test_payment_routes.py` that pass cleanly inside it. If you see payment
route failures, check which interpreter ran first.

---

## Running the stack

### Backend

```bash
uvicorn app.main:app --reload
```

- API — <http://localhost:8000>
- Swagger UI — <http://localhost:8000/docs>
- ReDoc — <http://localhost:8000/redoc>
- OpenAPI JSON — <http://localhost:8000/openapi.json>

### React frontend

```bash
cd frontend-react
npm run dev        # http://localhost:5174 — dev server, HMR
npm run build      # outputs to ../frontend-react-dist
npm run preview    # http://localhost:5175 — serves the production build
```

`npm run dev` proxies every API prefix to `localhost:8000`
(see [vite.config.js](../frontend-react/vite.config.js)), so `VITE_API_BASE_URL`
can stay unset and CORS never comes into play. `npm run preview` calls the API
directly and **does** need the origin in `CORS_ALLOWED_ORIGINS` — `:5175` is in
the default list.

### Static console

`frontend/` is a dependency-free JS console for poking at the API. Any static
server works:

```bash
cd frontend && python -m http.server 5500
```

### Full stack via Docker

```bash
docker compose up
```

| Service | Port |
| --- | --- |
| Postgres + pgvector | 5432 |
| API | 8000 |
| Static console | 5500 |
| React app | 5174 |

Just the database:

```bash
docker compose up db
```

---

## Testing

### Backend — 335 tests

```bash
venv/Scripts/python -m pytest                       # all
venv/Scripts/python -m pytest tests/test_hybrid_score.py
venv/Scripts/python -m pytest -k "knockout"
venv/Scripts/python -m pytest -q --tb=short
```

There is no `pytest.ini` or `pyproject.toml`; pytest runs on defaults.

DB-touching tests override `get_db` with an isolated in-memory SQLite session per
test. This is correct for isolation, but means **running pytest never exercises
the real configured engine**, whatever `DATABASE_URL` says. Verifying Postgres
behavior is a separate exercise from running the suite.

### Frontend — 100 tests

```bash
cd frontend-react
npm test                              # vitest run
npx vitest                            # watch mode
npx vitest run src/pages/AuthPage.test.jsx
```

Vitest config lives in `vite.config.js` under `test`: jsdom environment, globals
enabled, `src/test-setup.js` as the setup file. That setup polyfills
`window.matchMedia`, which jsdom lacks and framer-motion's `useReducedMotion()`
calls internally.

### Currently failing tests

Six tests fail when real credentials are present in `.env`:

| Test | Expects |
| --- | --- |
| `test_auth_and_history.py::test_me_returns_503_when_firebase_not_configured` | `503`, gets `401` |
| `authContext.test.jsx` — "resolves loading=false immediately when Firebase isn't configured" | `configured=false` |
| `AuthPage.test.jsx` — preview badge | `configured=false` |
| `AuthPage.test.jsx` — sign-in honest message | `configured=false` |
| `AuthPage.test.jsx` — sign-up honest message | `configured=false` |
| `AuthPage.test.jsx` — Google sign-in honest message | `configured=false` |

All six assert the *unconfigured* code path and read ambient environment
variables to get there. Once `FIREBASE_SERVICE_ACCOUNT_JSON` and
`VITE_FIREBASE_*` are set — as they are in a working local setup — the premise
no longer holds and the assertions fail.

These are not logic bugs. The fix is to make the tests stub the configuration
check (`monkeypatch.delenv` on the backend; mocking `isFirebaseConfigured` on the
frontend) rather than depending on the developer's environment being empty.

To confirm the suite is otherwise green:

```bash
FIREBASE_SERVICE_ACCOUNT_JSON= venv/bin/python -m pytest tests/test_auth_and_history.py
```

### Writing tests

- Backend tests live in `tests/`, one file per module under test.
- Use `TestClient` for route tests, direct function calls for scoring logic.
- Fixtures for file-parsing tests are in `tests/fixtures/`.
- Frontend tests sit beside their component as `<Component>.test.jsx`.
- Prefer Testing Library queries by role and text over implementation details.
- Do not depend on ambient environment variables — that is exactly what caused
  the six failures above.

---

## Project layout

```
app/
├── main.py               FastAPI app, middleware order, routers
├── config.py             Pricing tiers — single source of truth
├── api/routes/           HTTP layer only. No business logic.
│   ├── auth.py           GET /auth/me
│   ├── bias_audit.py     POST /bias-audit/jd
│   ├── billing.py        GET /billing/tiers
│   ├── history.py        GET /history
│   ├── payments.py       Razorpay order/verify/webhook
│   ├── resume.py         Parse file/text
│   ├── scan.py           All /score/* endpoints
│   └── voice.py          Voice agent turns and gap loop
├── core/                 Domain logic. Framework-agnostic.
│   ├── auth/             Token verification + FastAPI dependencies
│   ├── billing/          Razorpay client, signature verification
│   ├── bias_audit/       JD wordlist scanner
│   ├── llm/              Router, clients, prompts, caching, cost
│   ├── parsing/          Extraction, format analysis, confidence gate
│   ├── scoring/          The scoring engine
│   ├── services/         Entitlements, resume store, users
│   ├── voice_agent/      Slot filling, gap resolution, tool schema
│   └── rate_limit.py     Per-IP middleware
├── db/                   Models, engine, session
└── schemas/              Pydantic contracts + JSON Resume

frontend-react/src/
├── components/           Presentational, reusable
├── features/             Feature-scoped views and hooks
│   ├── report/           FullReportView, StandaloneReportView
│   └── upload/           FileDropzone, useResumeUpload
├── lib/                  api.js, authContext.jsx, firebase.js, razorpay.js
├── pages/                Route-level screens
└── styles/               tokens.css, global.css, report.css
```

---

## Code conventions

### Python

- `from __future__ import annotations` at the top of every module.
- Modern type hints — `str | None`, not `Optional[str]`.
- Dataclasses for domain results; Pydantic only at the API boundary.
- **Docstrings explain *why*, not *what*.** This codebase's docstrings document
  reasoning, rejected alternatives, and known limits. Match that when adding code.
- Routes stay thin: validate, delegate, shape the response. Logic goes in `core/`.
- `core/` never imports FastAPI. Domain errors are custom exception classes; the
  route layer translates them into status codes.

### JavaScript / React

- Function components with hooks. No class components.
- Data fetching lives in feature hooks (`useFullReport`, `useResumeUpload`), not
  in components.
- Plain CSS with custom properties in `styles/tokens.css`. No CSS-in-JS, no
  Tailwind, no Radix — a labeled input and a real `<button>` are already
  accessible without three extra dependencies.
- All API calls go through `lib/api.js`, which attaches the Firebase ID token
  automatically. No component should know auth exists.

### Adding a dependency

The project's standing preference is to own things simple enough to own. The
rate limiter is roughly forty lines instead of `slowapi`; the embedding fallback
was fixed rather than swapped for a library. Add a dependency when it does
something genuinely hard, and say why in a comment.

---

## Common tasks

### Adding an endpoint

1. Add request/response models to `app/schemas/api_models.py`.
2. Write the logic in the right `app/core/` module, with tests.
3. Add the route handler in `app/api/routes/`, thin.
4. Register the router in `app/main.py` if the module is new.
5. Decide auth: none, `get_optional_user`, or `get_current_user`.
6. Decide whether the prefix belongs in `RATE_LIMITED_PREFIXES`.
7. Document it in [API.md](API.md).

### Adding a scoring dimension

1. Implement it in `app/core/scoring/`, returning a 0–1 float.
2. Add its weight to `WEIGHTS` in `screening_report.py` — **all weights must sum
   to 1.0**.
3. Add a `_REASON_LABELS` entry so it can appear in `top_reasons_for_score`.
4. Append a `DimensionScore` in `screen_resume_against_jd()`.
5. Update the weights table in [ARCHITECTURE.md](ARCHITECTURE.md) and [API.md](API.md).

### Adding a canonical skill

Edit `CANONICAL_SKILLS` in `app/core/scoring/skill_extraction.py`, mapping every
surface form to one canonical id. To add it to a role in `readiness.py`'s
`ROLE_ONTOLOGY`, add the canonical skill **first** — an ontology id with no
corresponding canonical skill can never match anything, silently.

### Adding an LLM provider

1. Add a client in `app/core/llm/` following `langchain_backend.py`.
2. Add the provider to `router.py`'s enum and per-task model map.
3. Add the package to `requirements.txt`.
4. Document the key in `.env.example` and [CONFIGURATION.md](CONFIGURATION.md).

Never reference a model string outside `router.py`.

---

## Database work

### Migrations

```bash
alembic upgrade head                                  # apply
alembic revision --autogenerate -m "add x to y"       # generate
alembic downgrade -1                                  # roll back one
alembic current                                       # show revision
alembic history --verbose                             # list
```

Always read a generated migration before applying it. Autogenerate misses server
defaults, enum changes, and index renames.

### The SQLite dev database

`dev.db` is a throwaway convenience file. `app/db/session.py` auto-creates tables
and detects schema drift: if `models.py` declares a column that the existing
table lacks, it prints an explanation and **recreates the file from scratch**.

This exists because `create_all()` never adds a column to an existing table. A
stale `dev.db` would otherwise produce `OperationalError: no such column:
users.firebase_uid` on the next signed-in request. Deleting `dev.db` is always
safe.

This healing applies to SQLite only. Postgres schema changes go through Alembic,
and nothing in `session.py` touches them.

### pgvector

The `resumes.embedding` column is declared in
[infra/schema.sql](../infra/schema.sql), not in `models.py`, so the SQLAlchemy
models carry no hard dependency on the `pgvector` Python package. Enable the
extension before migrating:

```sql
create extension if not exists vector;
```

---

## Troubleshooting

### Payment tests fail

You ran system Python instead of the venv. Use `venv/Scripts/python -m pytest`.

### Six auth tests fail

Expected when `.env` has real Firebase credentials. See
[Currently failing tests](#currently-failing-tests).

### `no such column` on a signed-in request

A stale `dev.db`. Delete it — the app recreates it on next start.

### `AttributeError: 'NoneType' object has no attribute 'value'` on parse

A known bug in `POST /resume/parse-text` and `/resume/parse-file`
([resume.py:144](../app/api/routes/resume.py#L144),
[resume.py:161](../app/api/routes/resume.py#L161)). Triggered when no `tier` is
passed *and* an LLM key is configured *and* the confidence gate escalates. The
route computes `provider_used` from the requested tier, which is `None` on the
default path even though the LLM ran. Workaround: pass an explicit `tier`.

### Email/password sign-in fails with `auth/operation-not-allowed`

Email/Password is not enabled in the Firebase Console. Authentication →
Sign-in method → enable it. It is off by default.

### Google sign-in popup fails

Check that Google is enabled as a provider **and** that Authentication →
Settings → Authorized domains includes the domain you are serving from.

### CORS errors from `npm run preview`

`:5175` must be in `CORS_ALLOWED_ORIGINS`. It is in the default list; check
whether your `.env` overrides it. `npm run dev` avoids CORS entirely via the
Vite proxy.

### Scores look lexical rather than semantic

Expected with the default TF-IDF backend. Install `sentence-transformers` and
set `EMBEDDING_BACKEND=sbert`.

### `inferred_role` is always null

The role ontology covers technical roles only. Non-technical resumes are scored
neutrally rather than penalized. Extend `CANONICAL_SKILLS` and `ROLE_ONTOLOGY`
together.

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [API.md](API.md) — endpoint reference
- [CONFIGURATION.md](CONFIGURATION.md) — environment variables
- [DEPLOYMENT.md](DEPLOYMENT.md) — production deployment
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — contribution workflow
