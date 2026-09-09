# Deployment Guide

Taking this from a local checkout to a running production service.

- [Deployment topology](#deployment-topology)
- [Pre-deployment checklist](#pre-deployment-checklist)
- [Database setup](#database-setup)
- [Backend deployment](#backend-deployment)
- [Frontend deployment](#frontend-deployment)
- [Post-deployment verification](#post-deployment-verification)
- [Scaling](#scaling)
- [Operations](#operations)
- [Rollback](#rollback)

---

## Deployment topology

The API is deliberately API-only. It does not serve either frontend — both are
static origins that call it cross-origin. That keeps one serving convention
instead of two.

```
                    ┌──────────────┐
     users ────────>│     CDN      │  frontend-react-dist/
                    │ static host  │  (Vercel, Netlify, S3+CloudFront…)
                    └──────┬───────┘
                           │  XHR + Bearer token
                           ▼
                    ┌──────────────┐
                    │ Load balancer│  TLS termination
                    └──────┬───────┘
                           ▼
                 ┌────────────────────┐
                 │  API container(s)  │  uvicorn, port 8000
                 │  app.main:app      │
                 └─────────┬──────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
      ┌─────────────┐ ┌─────────┐ ┌──────────┐
      │  Postgres   │ │ Firebase│ │ Razorpay │
      │  + pgvector │ │  Admin  │ │          │
      └─────────────┘ └─────────┘ └──────────┘
```

Razorpay must be able to reach `POST /payments/webhook` from the public internet.

---

## Pre-deployment checklist

### Security

- [ ] `CORS_ALLOWED_ORIGINS` set to your actual origins. **Never `*`** — the API
      accepts `Authorization` headers.
- [ ] Every secret supplied through a platform secret manager, not a committed file.
- [ ] `.env` confirmed absent from the image and from git.
- [ ] TLS terminated in front of the API. Firebase ID tokens must never cross
      plaintext HTTP.
- [ ] Razorpay **live** keys, and `RAZORPAY_WEBHOOK_SECRET` distinct from
      `RAZORPAY_KEY_SECRET`.
- [ ] Firebase authorized domains include the production frontend domain.
- [ ] Firebase Console → Authentication → Sign-in method: every provider you
      intend to offer is explicitly enabled, **including Email/Password**, which
      is off by default.

### Correctness

- [ ] `TRUSTED_PROXY_HOPS` set to the number of proxies in front of the API
      (`1` behind a single load balancer). Left at `0` behind a proxy, every
      caller shares one rate-limit bucket and unrelated users 429 each other —
      see [CONFIGURATION.md](CONFIGURATION.md#http).
- [ ] `alembic upgrade head` applied against the production database.
- [ ] `create extension if not exists vector;` run before migrating.
- [ ] Model identifiers in [router.py](../app/core/llm/router.py) verified against
      current provider documentation — Google and Groq retire ids regularly.
- [ ] `EMBEDDING_BACKEND` matches what staging was validated against. Scores
      differ materially between TF-IDF and SBERT; a mismatch makes staging
      results non-comparable.
- [ ] Pricing in `app/config.py` matches the currency your Razorpay account is
      actually enabled for. A new account is INR-only.

### Known issues to weigh before shipping

- [ ] **Email/password auth errors show raw Firebase codes.** Only Google popup
      errors are translated.
- [ ] **Rate limiting is per-process.** With N replicas the real ceiling is N ×
      the configured limit. (Distinct from the proxy problem above, which
      `TRUSTED_PROXY_HOPS` handles; this one needs a shared store to fix.)
- [ ] **Voice sessions are in-process.** They break under more than one replica.
- [ ] **Supabase has not been exercised against a live project** from this
      codebase. Verify the connection under load before trusting it.

---

## Database setup

### Supabase

1. Create the project.
2. SQL Editor:
   ```sql
   create extension if not exists vector;
   ```
3. Project Settings → Database → connection string. Use the **Session** pooler,
   not Transaction mode — this is a long-running process and SQLAlchemy expects
   session-level features that pgbouncer's transaction mode does not provide.
4. Ensure `?sslmode=require` is present.
5. Apply migrations from a machine that can reach the database:
   ```bash
   DATABASE_URL="postgresql://...?sslmode=require" alembic upgrade head
   ```
6. Confirm:
   ```bash
   DATABASE_URL="..." alembic current
   ```

### Self-managed Postgres

Postgres 16 with pgvector 0.6 is the verified combination. `infra/schema.sql`
holds the reference DDL, including the `vector(384)` column that is intentionally
declared outside `models.py`.

### Migrations in the deployment pipeline

Run `alembic upgrade head` as a **separate step before** rolling out new
application containers, not as part of container startup. Startup migrations race
each other when more than one replica boots at once.

```bash
alembic upgrade head && kubectl rollout restart deployment/resume-optimizer-api
```

---

## Backend deployment

### Docker

The provided [Dockerfile](../Dockerfile) is `python:3.11-slim` with no build
stage — `psycopg2-binary`, `scikit-learn`, and `numpy` all ship wheels for this
base image. Keep it that way; adding a compiler stage should be deliberate.

```bash
docker build -t resume-optimizer-api:$(git rev-parse --short HEAD) .
```

Optional extras at build time:

```bash
docker build --build-arg LLM_EXTRA_PACKAGE="sentence-transformers" -t resume-optimizer-api .
```

If you enable SBERT, bake the model weights into the image. Downloading them on
first request adds a large cold-start penalty to a user-facing call.

### Running

```bash
docker run -d \
  -p 8000:8000 \
  -e DATABASE_URL="postgresql://...?sslmode=require" \
  -e FIREBASE_SERVICE_ACCOUNT_JSON="$(cat serviceAccountKey.json)" \
  -e RAZORPAY_KEY_ID="rzp_live_..." \
  -e RAZORPAY_KEY_SECRET="..." \
  -e RAZORPAY_WEBHOOK_SECRET="..." \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -e LLM_PROVIDER="claude" \
  -e EMBEDDING_BACKEND="sbert" \
  -e CORS_ALLOWED_ORIGINS="https://app.yourdomain.com" \
  resume-optimizer-api:latest
```

### Workers

The default command runs a single uvicorn process. **Read
[Scaling](#scaling) before adding workers** — the rate limiter and voice session
store are both per-process, so `--workers 4` silently quadruples the effective
rate limit and breaks voice sessions.

### Health checks

`GET /health` returns `{"status": "ok"}`. It is unauthenticated and not rate
limited, so it is safe as a liveness and readiness probe.

Note that it does **not** check database connectivity — it returns `200` even
when Postgres is unreachable. If you need a dependency-aware readiness probe, add
one; do not assume `/health` covers it.

### Platform notes

| Platform | Notes |
| --- | --- |
| Railway / Render | Point at the Dockerfile, set env vars, run migrations as a release command |
| Fly.io | `fly launch` detects the Dockerfile; set secrets with `fly secrets set` |
| ECS / Cloud Run | Standard container deploy; ensure the webhook path is publicly reachable |
| Kubernetes | Migrations as an init Job, not an init container on every pod |

Serverless platforms are a poor fit as configured: the in-memory rate limiter and
voice session store both assume a long-lived process, and the Session pooler
guidance assumes persistent connections.

---

## Frontend deployment

```bash
cd frontend-react
npm ci
VITE_FIREBASE_API_KEY=... \
VITE_FIREBASE_AUTH_DOMAIN=... \
VITE_FIREBASE_PROJECT_ID=... \
VITE_FIREBASE_APP_ID=... \
VITE_API_BASE_URL=https://api.yourdomain.com \
VITE_SITE_URL=https://app.yourdomain.com \
npm run build
```

`npm run build` runs three steps: the client build, an SSR build, and a
prerender pass that writes real static HTML for each public route plus
`sitemap.xml` and `robots.txt`. Output lands in `frontend-react-dist/`.
Deploy it to any static host.

**`VITE_SITE_URL` must be the real deployed origin.** Canonical URLs,
`og:url`, `og:image`, and the sitemap all derive from it. Unset, the build
succeeds but stamps every page with a placeholder domain — worse than
omitting canonicals entirely, since it points search engines at a host you
do not control. The build warns loudly; treat that warning as a failure.
See [SEO.md](SEO.md).

Because each route is prerendered to its own `index.html`
(`pricing/index.html` and so on), every URL resolves on a static host
without custom rewrite rules. Keep the catch-all rewrite to `index.html`
anyway, for client-side routes that are not prerendered.

`VITE_*` values are **compiled into the bundle at build time**. Changing one
requires a rebuild, and every one of them is publicly visible. Never place a
server secret in a `VITE_` variable.

`VITE_API_BASE_URL` is required in production. The Vite dev proxy does not exist
in a built bundle.

Configure your host to serve `index.html` for unmatched routes — the app uses
client-side routing.

### Static console

`frontend/` is a developer tool, not a product surface. Do not deploy it publicly.

### Docker frontend service

`docker-compose.yml` includes a `frontend-react` service with a multi-stage
build. Its `npm ci && npm run build` steps are verified; the container
build-and-serve step has not been run end to end in this environment. Test it
before relying on it.

---

## Post-deployment verification

```bash
# 1 — liveness
curl https://api.yourdomain.com/health

# 2 — public scoring works without auth
curl -X POST https://api.yourdomain.com/score/standalone \
  -H "Content-Type: application/json" \
  -d '{"resume":{"basics":{"name":"Test","email":"t@example.com"}}}'

# 3 — pricing config loads
curl https://api.yourdomain.com/billing/tiers

# 4 — auth is wired, not 503
curl -i https://api.yourdomain.com/auth/me
# expect 401 "Sign in required". A 503 means FIREBASE_SERVICE_ACCOUNT_JSON is missing.

# 5 — CORS preflight from the real origin
curl -i -X OPTIONS https://api.yourdomain.com/score/full-report \
  -H "Origin: https://app.yourdomain.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type"
# Access-Control-Allow-Headers must include "authorization"
```

Step 5 matters more than it looks. If `Authorization` is missing from the
allowed headers, browsers silently strip it and every authenticated request
looks anonymous to the backend — a failure invisible to `curl` without the
preflight and invisible to same-origin testing.

Then, manually:

- [ ] Sign up with email/password, then sign in.
- [ ] Sign in with Google.
- [ ] Upload a PDF resume and confirm it parses.
- [ ] Run a full report and confirm history records it.
- [ ] Complete a test-mode checkout and confirm the tier upgrades.
- [ ] Confirm the Razorpay webhook fires — Dashboard → Webhooks → recent
      deliveries.

---

## Scaling

Two components hold per-process state and must be addressed before running more
than one worker or replica.

### Rate limiter

[app/core/rate_limit.py](../app/core/rate_limit.py) is an in-memory fixed-window
counter. Each process enforces its own limit independently, so N processes
multiply the effective ceiling by N. It also resets on restart.

Move the counter to Redis before scaling horizontally. The module is roughly
forty lines and the interface is small.

### Voice sessions

`_SESSIONS` in [app/api/routes/voice.py](../app/api/routes/voice.py) is a
process-local dict. With more than one replica, a user's second turn may land on
a process that has never seen their session. Move it to Redis keyed by
`session_id` with a TTL matching session length.

### Database connections

SQLAlchemy pools per process. Total connections ≈ replicas × workers × pool size.
Check that against your Postgres `max_connections` and Supabase's pooler limits
before scaling out.

### Cost

LLM spend scales with traffic. The controls that already exist:

- Deterministic-first parsing — the free path targets **zero** LLM calls.
- Per-task model tiering in `router.py`.
- Prompt caching in `prompt_cache.py`.
- Batch API for non-real-time work, roughly 50% cheaper.

`usage_logs` records provider, tokens, and cost per call, including for anonymous
requests. Query it before adjusting tiers or pricing.

---

## Operations

### Monitoring

At minimum:

| Signal | Why |
| --- | --- |
| `5xx` rate on `/resume/*` | Catches the known `provider_used` crash |
| `429` rate | Distinguish rate limiting from exhausted allowances via `detail` |
| `503` on `/auth/*` or `/payments/*` | An integration lost its configuration |
| p95 latency on `/score/full-report` | The heaviest endpoint |
| Webhook delivery failures | Razorpay dashboard — missed payments |
| Daily `usage_logs` cost sum | LLM spend |

### Useful queries

```sql
-- LLM spend by provider, last 30 days
SELECT provider, count(*), round(sum(cost_usd)::numeric, 2) AS usd
FROM usage_logs
WHERE action = 'llm_call' AND created_at > now() - interval '30 days'
GROUP BY provider ORDER BY usd DESC;

-- Scans per day
SELECT date_trunc('day', created_at) AS day, action, count(*)
FROM usage_logs
WHERE action LIKE '%_scan'
GROUP BY 1, 2 ORDER BY 1 DESC;

-- Abandoned checkouts
SELECT tier, billing_cycle, count(*)
FROM payments WHERE status = 'created'
GROUP BY 1, 2;

-- Active paid subscriptions
SELECT tier, count(*) FROM subscriptions
WHERE active AND tier != 'free' GROUP BY tier;
```

### Backups

`resumes.data` and `scan_results.breakdown` hold user content that cannot be
regenerated. Supabase provides automated backups on paid plans; verify the
retention window matches your requirements and test a restore before you need one.

### Secret rotation

- Razorpay key secret and webhook secret rotate **independently**.
- Rotating `FIREBASE_SERVICE_ACCOUNT_JSON` requires generating a new key in the
  console and revoking the old one there. Changing the env var alone does not
  invalidate the old key.
- LLM API keys can be rotated with no code change.

---

## Rollback

### Application

Redeploy the previous image tag. The API is stateless apart from the two
in-process stores noted above, so rollback is a container swap.

### Database

```bash
alembic downgrade -1
```

Check the migration's `downgrade()` before running it. A migration that drops a
column loses that data permanently; downgrading is not always reversible in
practice even when it succeeds.

Safer sequence for a schema change:

1. Deploy code that tolerates both old and new schema.
2. Migrate.
3. Deploy code that requires the new schema.

That way an application rollback never requires a database rollback.

---

## Related documents

- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable
- [ARCHITECTURE.md](ARCHITECTURE.md) — including architectural limits in detail
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup and testing
