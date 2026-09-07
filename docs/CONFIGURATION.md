# Configuration

Every environment variable, what it does, and how to set up each integration.

**Nothing here is required.** The application starts and serves its public
scoring and analysis endpoints with an empty `.env`. Each variable unlocks a
capability; leaving it unset selects a documented fallback.

- [How configuration is loaded](#how-configuration-is-loaded)
- [Backend variables](#backend-variables)
- [Frontend variables](#frontend-variables)
- [Integration setup](#integration-setup)
  - [Database (Supabase / Postgres)](#database-supabase--postgres)
  - [Firebase Auth](#firebase-auth)
  - [Razorpay](#razorpay)
  - [LLM providers](#llm-providers)
  - [Embeddings](#embeddings)
- [Configuration by deployment stage](#configuration-by-deployment-stage)
- [Secret handling](#secret-handling)

---

## How configuration is loaded

`app/__init__.py` calls `load_dotenv()`. It lives in the package `__init__`
rather than in `main.py` deliberately: Python guarantees a parent package's
`__init__.py` runs before any submodule, so `.env` is loaded no matter which
entry point is used — the uvicorn server, a one-off script, a REPL, or a test
file that never imports `app.main`. Putting the call in `main.py` would cover
only the API server.

You do not need to `export` anything. Copy `.env.example` to `.env` and edit.

```bash
cp .env.example .env
cp frontend-react/.env.example frontend-react/.env
```

`.env` is git-ignored. `.env.example` is the committed template.

Vite variables are different: they are inlined into the JavaScript bundle **at
build time**, not read at runtime. Changing one requires a rebuild, and anything
placed in a `VITE_*` variable is publicly visible in the shipped bundle.

---

## Backend variables

### LLM providers

| Variable | Default | Effect |
| --- | --- | --- |
| `LLM_PROVIDER` | `claude` | Process-wide default: `claude` · `gemini` · `groq` |
| `ANTHROPIC_API_KEY` | — | Enables the `advanced` tier (Claude) |
| `GEMINI_API_KEY` | — | Enables the `medium` tier (Gemini) |
| `GROQ_API_KEY` | — | Enables the `basic` tier (Groq) |

Two independent mechanisms decide which provider answers a call:

1. **Per-request `tier`** on `/resume/parse-*` (`basic` → Groq, `medium` →
   Gemini, `advanced` → Claude). This always wins.
2. **`LLM_PROVIDER`** for every call site that exposes no tier — for example
   `/score/suggestions` with `use_llm: true`.

With no key set, parsing uses the heuristic path and suggestions use template
phrasing. Nothing fails.

### Open-weight extraction crosscheck

| Variable | Default | Effect |
| --- | --- | --- |
| `OSS_EXTRACTION_BASE_URL` | — | Any OpenAI-compatible endpoint |
| `OSS_EXTRACTION_API_KEY` | `not-needed` | Auth for that endpoint |
| `OSS_EXTRACTION_MODEL` | — | Model identifier at that endpoint |

Used only for `TaskType.EXTRACTION_CROSSCHECK`, and deliberately outside the
`LLM_PROVIDER` switch: a crosscheck is only meaningful against a genuinely
different model family. Points at a self-hosted vLLM/SGLang server, a hosted
open-weight provider, or Groq's OpenAI-compatible endpoint.

### Embeddings

| Variable | Default | Effect |
| --- | --- | --- |
| `EMBEDDING_BACKEND` | TF-IDF | Set to `sbert` for Sentence-BERT |

### Database

| Variable | Default | Effect |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./dev.db` | SQLAlchemy connection URL |

### Authentication

| Variable | Default | Effect |
| --- | --- | --- |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | — | Service account key **content** (not a path) |

Unset means `/auth/me` and `/history` return `503`; every other endpoint is
unaffected.

### Payments

| Variable | Default | Effect |
| --- | --- | --- |
| `RAZORPAY_KEY_ID` | — | Public key, returned to the frontend |
| `RAZORPAY_KEY_SECRET` | — | Signs and verifies payment callbacks |
| `RAZORPAY_WEBHOOK_SECRET` | — | Verifies webhook payloads — a **different** secret |

Unset means `/payments/*` returns `503`.

### HTTP

| Variable | Default | Effect |
| --- | --- | --- |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500,http://localhost:5174,http://localhost:5175` | Comma-separated allowed origins |
| `RATE_LIMIT_REQUESTS` | `60` | Requests per window per IP |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Window length |

Do not set `CORS_ALLOWED_ORIGINS` to `*` in production. The API accepts
credentials-bearing `Authorization` headers.

---

## Frontend variables

In `frontend-react/.env`:

| Variable | Required for | Notes |
| --- | --- | --- |
| `VITE_FIREBASE_API_KEY` | Auth | Firebase Console → Project Settings → General → Your apps |
| `VITE_FIREBASE_AUTH_DOMAIN` | Auth | Same screen |
| `VITE_FIREBASE_PROJECT_ID` | Auth | Same screen |
| `VITE_FIREBASE_APP_ID` | Auth | Same screen |
| `VITE_API_BASE_URL` | Non-proxied backends | Only needed when Vite's dev proxy does not apply — e.g. a production build pointed at a deployed API |
| `VITE_SITE_URL` | **Every production build** | The deployed origin, e.g. `https://yourdomain.com`. Canonical URLs, `og:url`, `og:image`, `sitemap.xml` and `robots.txt` all derive from it. |

> `VITE_SITE_URL` is the one frontend variable a production build must not
> omit. Unset, the build succeeds but stamps every page with the
> placeholder origin `resume-optimizer.example.com` — which tells Google
> the canonical version of your content lives on a domain you do not own,
> and can suppress your own pages from search results. The build prints a
> warning when this happens. See [SEO.md](SEO.md).

`isFirebaseConfigured()` in [firebase.js](../frontend-react/src/lib/firebase.js)
requires **all four** Firebase values. With any missing, the UI shows a visible
"PREVIEW — no Firebase project configured" badge and every auth action reports an
honest message rather than failing silently or faking success.

A Firebase web API key is not a secret — it identifies the project, and access is
governed by Firebase security rules and authorized domains. It is safe in a
client bundle. The **service account key** (`FIREBASE_SERVICE_ACCOUNT_JSON`) is a
real secret and must stay server-side.

---

## Integration setup

### Database (Supabase / Postgres)

The app targets Postgres with the pgvector extension. SQLite is a local
convenience only.

1. Create a project at [supabase.com](https://supabase.com).
2. In the SQL Editor, enable pgvector:
   ```sql
   create extension if not exists vector;
   ```
3. Copy the connection string from **Project Settings → Database**. Use the
   **Session** pooler, **not** the Transaction pooler. This app is a
   long-running FastAPI process, not serverless functions, and SQLAlchemy's
   pooling expects session-level features (prepared statements among them) that
   pgbouncer's transaction mode does not support. Using transaction mode causes
   intermittent errors under load that are painful to diagnose.
4. Append `?sslmode=require` if it is not already present. Supabase requires SSL
   and some connection-string variants omit the parameter.
5. Run the migrations:
   ```bash
   alembic upgrade head
   ```

```env
DATABASE_URL=postgresql://postgres:[password]@db.[project-ref].supabase.co:5432/postgres?sslmode=require
```

> **Verification status.** Alembic migrations and application queries are
> verified against a local Postgres 16 + pgvector 0.6 instance, which is the same
> engine. They have **not** been exercised against a live Supabase project, so the
> pooler mode, SSL behavior, and connection string above are documented from
> Supabase's requirements rather than confirmed by a test run here.
>
> Note also that the pytest suite overrides `get_db` with an isolated in-memory
> SQLite session per test. Running pytest therefore never exercises the real
> configured engine, regardless of `DATABASE_URL`. Migration verification is a
> separate step from running the tests.

**Local Postgres alternative** — `docker compose up db` starts
`pgvector/pgvector:pg16`:

```env
DATABASE_URL=postgresql://resume_optimizer:dev_only_change_me@localhost:5432/resume_optimizer
```

### Firebase Auth

**Server side**

1. Firebase Console → Project Settings → **Service Accounts** → Generate new
   private key. A JSON file downloads.
2. Set `FIREBASE_SERVICE_ACCOUNT_JSON` to that file's **entire content**, not its
   path:
   ```bash
   FIREBASE_SERVICE_ACCOUNT_JSON=$(cat serviceAccountKey.json)
   ```
   This matches the app's "everything via env vars, nothing baked into the image"
   pattern used for every other credential.

**Client side**

3. Firebase Console → Project Settings → General → Your apps → Web app. Copy the
   four values into `frontend-react/.env`.

**Enable the sign-in methods you intend to use**

4. Firebase Console → **Authentication → Sign-in method**. Enable each provider
   explicitly:
   - **Email/Password** — enable it. It is **not** on by default. Without this,
     every email/password sign-in fails with `auth/operation-not-allowed`.
   - **Google** — add it as a provider and save.
5. Firebase Console → Authentication → **Settings → Authorized domains**. Add
   the domain the app is actually served from. Firebase only permits OAuth
   redirects back to domains listed here, so Google sign-in fails on an
   unlisted domain even when everything else is correct.

> Only the three Google popup error codes are translated into readable messages
> today. An email/password failure surfaces Firebase's raw code — for example
> `Error (auth/operation-not-allowed).` — so step 4 above is the first thing to
> check when email sign-in fails. See
> [authContext.jsx:82](../frontend-react/src/lib/authContext.jsx#L82).

### Razorpay

1. Create an account at [razorpay.com](https://razorpay.com). Test mode works
   without KYC; live payments require it.
2. Dashboard → Settings → **API Keys** → Generate. This gives
   `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`.
3. Dashboard → Settings → **Webhooks** → Add New Webhook:
   - URL: `https://your-domain/payments/webhook`
   - Events: at minimum `payment.captured` and `payment.failed`

   This generates `RAZORPAY_WEBHOOK_SECRET` — a **different** secret from
   `RAZORPAY_KEY_SECRET`. The SDK verifies webhook payloads and payment
   callbacks with two separate signatures on purpose; they protect against
   different things.
4. **Currency.** `app/config.py` prices in USD, but a new Razorpay account is
   INR-only by default. Enabling international processing is a separate
   dashboard and KYC step (Settings → Payment Methods → International).
   Alternatively, convert the prices in `config.py` and send `currency: "INR"`
   from the frontend checkout call.

### LLM providers

| Provider | Key | Console |
| --- | --- | --- |
| Claude | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| Gemini | `GEMINI_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| Groq | `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) |

All three provider packages are in `requirements.txt` and are required, not
optional — the tier selector offers all three at request time, so all three must
be importable even if only one key is set.

Model identifiers live only in [router.py](../app/core/llm/router.py). Both
Google and Groq retire model ids regularly; verify the ids in that file against
current provider documentation before a production deployment rather than
assuming they are still current.

### Embeddings

The default TF-IDF backend is **lexical, not semantic**. It compares word
overlap. Scores are directionally useful and require no downloads, but
"semantic fit" is not measuring semantics until you switch backends.

```bash
pip install sentence-transformers
```

```env
EMBEDDING_BACKEND=sbert
```

This also activates the semantic-match code path in
`requirement_matching.py`, which otherwise exists but rarely fires in practice.
Expect a first-run model download and higher memory use.

---

## Configuration by deployment stage

### Minimal — trying it out

Empty `.env`. SQLite, TF-IDF, heuristic parsing, template suggestions. Public
scoring endpoints fully functional.

### Development

```env
DATABASE_URL=postgresql://resume_optimizer:dev_only_change_me@localhost:5432/resume_optimizer
GROQ_API_KEY=gsk_...
LLM_PROVIDER=groq
CORS_ALLOWED_ORIGINS=http://localhost:5174,http://localhost:5175
```

Groq is the cheapest way to exercise the real LLM path.

### Staging

Add Firebase and Razorpay **test** keys. Point `DATABASE_URL` at a Supabase
project. Use `EMBEDDING_BACKEND=sbert` if the production plan includes it —
scoring numbers differ meaningfully between backends, so staging should match
production here or its scores will not be comparable.

### Production

```env
DATABASE_URL=postgresql://...supabase.co:5432/postgres?sslmode=require
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account",...}
RAZORPAY_KEY_ID=rzp_live_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
ANTHROPIC_API_KEY=sk-ant-...
LLM_PROVIDER=claude
EMBEDDING_BACKEND=sbert
CORS_ALLOWED_ORIGINS=https://app.yourdomain.com
RATE_LIMIT_REQUESTS=120
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for the full production checklist.

---

## Secret handling

- `.env` is git-ignored. Keep it that way; commit only `.env.example`.
- Never commit a real service account key, API key, or Razorpay secret.
- `VITE_*` variables are compiled into the public JavaScript bundle. Never put a
  server secret in one.
- In production, prefer your platform's secret manager over a `.env` file.
- Rotate `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` independently —
  they are separate secrets protecting separate paths.
- If a service account key is exposed, revoke it in the Firebase Console
  immediately and generate a new one. Rotating the env var alone does not
  invalidate the old key.

---

## Related documents

- [DEPLOYMENT.md](DEPLOYMENT.md) — production deployment and migrations
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup
- [ARCHITECTURE.md](ARCHITECTURE.md) — why these integrations are structured this way
