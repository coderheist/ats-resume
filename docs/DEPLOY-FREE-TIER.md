# Free-Tier Deployment Runbook

A step-by-step path to a live deployment that stays free at roughly 500
users, without the cold-start delays that make free hosting feel broken.

For general production guidance (scaling, secrets rotation, rollback) see
[DEPLOYMENT.md](DEPLOYMENT.md). This document is the narrower "get it
online for free, properly" path.

- [Free-Tier Deployment Runbook](#free-tier-deployment-runbook)
  - [What the app actually needs](#what-the-app-actually-needs)
  - [The recommended stack](#the-recommended-stack)
  - [Why not the other free options](#why-not-the-other-free-options)
  - [Step 1 — Database (Supabase)](#step-1--database-supabase)
  - [Step 2 — Backend (Google Cloud Run)](#step-2--backend-google-cloud-run)
    - [2.1 One-time setup](#21-one-time-setup)
    - [2.2 Store the secrets](#22-store-the-secrets)
    - [2.3 Deploy](#23-deploy)
  - [Step 3 — Frontend (Cloudflare Pages)](#step-3--frontend-cloudflare-pages)
    - [Deploying the frontend to Vercel instead](#deploying-the-frontend-to-vercel-instead)
  - [Step 4 — Connect the pieces](#step-4--connect-the-pieces)
  - [Step 5 — Verify](#step-5--verify)
  - [Keeping it free](#keeping-it-free)
  - [Cold starts](#cold-starts)
  - [When you outgrow this](#when-you-outgrow-this)
  - [Related documents](#related-documents)

---

## What the app actually needs

Measured on this codebase, not estimated:

| Metric | Value | Why it matters |
| --- | --- | --- |
| Resident memory | **172 MB** | Fits a 512 MB free tier with real headroom |
| Process boot | **~2 s** | Cold-start floor |
| First scan after boot | **~1.5 s** | Lazy imports (scikit-learn) on the first request |
| Warm scan | **~9 ms** | The app is genuinely fast once running |
| Installed dependencies | **410 MB** | scipy 109 MB + scikit-learn 40 MB + numpy 31 MB dominate |

Two conclusions follow:

1. **Memory is not the constraint.** 172 MB fits comfortably almost anywhere.
2. **Cold start is the only real UX risk.** A warm request is 9 ms; a cold
   one is ~3.5 s. Any platform that sleeps aggressively will be the thing
   users notice, not the app itself.

At 500 users the traffic is genuinely small — perhaps 5,000–15,000
requests a month. Throughput is a non-issue. Everything below optimises
for *not sleeping* and *not costing money*, in that order.

---

## The recommended stack

| Layer | Platform | Free allowance | Cold start |
| --- | --- | --- | --- |
| Frontend | **Cloudflare Pages** | Unlimited bandwidth, 500 builds/month | None — static CDN |
| Backend | **Google Cloud Run** | 2M requests + 360k GB-s/month | ~2–4 s, mitigable |
| Database | **Supabase** | 500 MB Postgres, pgvector included | None |

Your projected usage against those limits:

```
Requests:  ~15,000/month  vs  2,000,000 free      →  0.75% of the allowance
Compute:   ~750 GB-s      vs  360,000 free        →  0.2%
Database:  ~50 MB         vs  500 MB free         →  10%
Bandwidth: a few GB       vs  unlimited (CF)      →  n/a
```

This is not "free until you grow" — at this scale you are two orders of
magnitude inside the free tier. It stays free well past 500 users.

---

## Why not the other free options

Worth stating, because the obvious choices are the wrong ones here.

| Platform | Verdict |
| --- | --- |
| **Render (free)** | Sleeps after 15 minutes idle and takes **50+ seconds** to wake. That is precisely the experience you said you want to avoid — a user clicking your link at 9am waits nearly a minute for a blank page. Rules itself out. |
| **Fly.io** | Technically excellent — Firecracker VMs wake in 1–3 s. But the free allowance now needs a card and the 256 MB machines are too small for a 172 MB working set. A 512 MB machine is ~$3/month: cheap, not free. |
| **Railway** | $5 trial credit, then billed. Not a free tier. |
| **Vercel (backend)** | Python serverless functions can host FastAPI, but the in-memory rate limiter and voice session store both assume a long-lived process. They break silently across invocations. |
| **Oracle Cloud Always Free** | The only genuinely always-on free option: 4 ARM cores, 24 GB RAM, free forever, **zero cold starts**. Best possible UX. The catch is you manage the VM yourself — nginx, TLS, systemd, updates — and Oracle's signup and regional capacity are notoriously unreliable. Worth it if you want zero cold start and don't mind ops. See the note at the end. |

---

## Step 1 — Database (Supabase)

1. Create a project at [supabase.com](https://supabase.com). Choose a
   region physically near your users and **near your Cloud Run region** —
   cross-region database latency is added to every single request.
2. Enable pgvector. SQL Editor → run:
   ```sql
   create extension if not exists vector;
   ```
3. Project Settings → Database → Connection string → **Session pooler**.
   Not the Transaction pooler: this app is a long-running process and
   SQLAlchemy expects session-level features that pgbouncer's transaction
   mode does not provide.
4. Ensure the string ends with `?sslmode=require`.
5. Apply the migrations from your machine:
   ```bash
   DATABASE_URL="postgresql://postgres:...@...supabase.co:5432/postgres?sslmode=require" \
     alembic upgrade head

   DATABASE_URL="..." alembic current    # confirm
   ```

> Free Supabase projects pause after **7 days with no activity**. With
> real users this never triggers. If you deploy and then leave it idle for
> a week before launching, expect to un-pause it from the dashboard.

---

## Step 2 — Backend (Google Cloud Run)

### 2.1 One-time setup

```bash
# Install the gcloud CLI, then:
gcloud auth login
gcloud projects create resume-optimizer-prod        # or use an existing project
gcloud config set project resume-optimizer-prod
gcloud services enable run.googleapis.com cloudbuild.googleapis.com
```

A billing account must be attached even for free-tier use. You are not
charged inside the free allowance, but Cloud Run will not deploy without
one. Set a budget alert (Step 5) so this can never surprise you.

### 2.2 Store the secrets

Do not pass secrets as plain environment variables on the command line —
they end up in your shell history and in the deploy logs.

```bash
gcloud services enable secretmanager.googleapis.com

printf '%s' 'postgresql://postgres:...@...supabase.co:5432/postgres?sslmode=require' \
  | gcloud secrets create DATABASE_URL --data-file=-

gcloud secrets create FIREBASE_SERVICE_ACCOUNT_JSON --data-file=serviceAccountKey.json

printf '%s' 'sk-ant-...' | gcloud secrets create ANTHROPIC_API_KEY --data-file=-
```
Skip any you are not using. Every integration is optional — see
[CONFIGURATION.md](CONFIGURATION.md).

### 2.3 Deploy

From the repository root:

```bash
gcloud run deploy resume-optimizer-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 3 \
  --concurrency 40 \
  --timeout 60 \
  --set-secrets \
DATABASE_URL=DATABASE_URL:latest,FIREBASE_SERVICE_ACCOUNT_JSON=FIREBASE_SERVICE_ACCOUNT_JSON:latest \
  --set-env-vars \
LLM_PROVIDER=claude,EMBEDDING_BACKEND=tfidf,RATE_LIMIT_REQUESTS=60
```

Cloud Run builds the [Dockerfile](../Dockerfile) for you. It prints a
URL like `https://resume-optimizer-api-xxxxx-uc.a.run.app` — keep it for
Step 3.

**Flag reasoning, since the defaults are wrong for this app:**

| Flag | Value | Why |
| --- | --- | --- |
| `--memory 512Mi` | 512 MB | 172 MB measured + headroom. 256Mi would OOM under load. |
| `--max-instances 3` | 3 | A hard ceiling on spend. Even a traffic spike or a scraping bot cannot run up a bill. |
| `--concurrency 40` | 40 | One instance handles 40 simultaneous requests. At 9 ms per scan, three instances is far more than 500 users need. |
| `--min-instances 0` | 0 | Scale to zero. This is what keeps it free — see [Cold starts](#cold-starts). |
| `--timeout 60` | 60 s | Scans take milliseconds; LLM-backed parsing can take seconds. 60 s is generous and bounds a hung request. |

> **The Dockerfile change this required.** The container previously
> hard-coded `--port 8000`. Cloud Run assigns a port at runtime and
> injects it as `$PORT` (8080 by default), so the container never
> answered where the platform probed and the deploy failed its health
> check with an unhelpful "container failed to start and listen" error.
> The `CMD` now binds `${PORT:-8000}`, which works on Cloud Run, Railway,
> Koyeb and Render, and still falls back to 8000 for docker-compose.

---

## Step 3 — Frontend (Cloudflare Pages)

1. Push the repository to GitHub.
2. Cloudflare dashboard → Workers & Pages → Create → Pages → connect the repo.
3. Build settings:

   | Setting | Value |
   | --- | --- |
   | Framework preset | None |
   | Build command | `cd frontend-react && npm ci && npm run build` |
   | Build output directory | `frontend-react-dist` |
   | Root directory | *(leave blank)* |

4. Environment variables — **all are build-time**, so a change needs a
   redeploy:

   ```
   VITE_SITE_URL          = https://yourdomain.com
   VITE_API_BASE_URL      = https://resume-optimizer-api-xxxxx-uc.a.run.app
   VITE_FIREBASE_API_KEY      = ...
   VITE_FIREBASE_AUTH_DOMAIN  = ...
   VITE_FIREBASE_PROJECT_ID   = ...
   VITE_FIREBASE_APP_ID       = ...
   ```

   `VITE_SITE_URL` is not optional. Canonical URLs, `og:url` and
   `sitemap.xml` all derive from it, and leaving it unset stamps every
   page with a placeholder domain. See [SEO.md](SEO.md).

5. Deploy. Cloudflare serves the prerendered HTML from its CDN — no cold
   start, and the landing page is fast worldwide regardless of where your
   backend lives.

Cloudflare Pages is a good fit here specifically because `npm run build`
already prerenders each route to its own `index.html`, so deep links to
the *public* routes resolve with no rewrite rules. The authenticated
routes (`/dashboard`, `/settings`, `/history`, `/login`, `/signup`) are
deliberately not prerendered — they are `noindex` and render differently
per user — so they have no file on disk and a direct hit or a refresh on
one 404s unless the platform is told to serve the SPA shell for them.
On Cloudflare that is a `_redirects` file; on Vercel it is the `rewrites`
block described below.

### Deploying the frontend to Vercel instead

Vercel works equally well, with one trap worth stating plainly: its
**Root Directory** setting is also the ceiling for build output. Point it
at `frontend-react` and the build succeeds but the deploy fails with

```
Error: No Output Directory named "dist" found after the Build completed.
```

because `vite.config.js` writes to `../frontend-react-dist`, one level
*above* that root, where Vercel cannot see it.

The repository root therefore carries a [`vercel.json`](../vercel.json)
that pins the whole arrangement, so it is reproducible rather than a
dashboard setting nobody can review:

| Setting | Value |
| --- | --- |
| Framework preset | Other |
| Root directory | *(leave blank — the repository root)* |
| Build command | from `vercel.json` |
| Output directory | from `vercel.json` |

Vercel reads `vercel.json` from the Root Directory, so that field must be
blank for any of this to apply. Environment variables are the same
build-time set as Cloudflare above — `VITE_SITE_URL` and
`VITE_API_BASE_URL` especially, since without the latter the deployed
frontend issues its API calls at its own origin and every request 404s
against the static CDN instead of reaching Cloud Run.

The `rewrites` entries map the five client-only routes onto the SPA
shell. They are listed explicitly rather than as a catch-all so a
mistyped URL still returns a real 404 instead of a soft 404 that renders
an empty page with a 200 — a genuine SEO liability at scale. The cost is
that **a new client-only route must be added to that list**, or it will
404 on refresh in production while working perfectly in `npm run dev`.

---

## Step 4 — Connect the pieces

Three settings have to agree, and each is a silent failure if wrong.

**1. Backend CORS must name the frontend origin.**

```bash
gcloud run services update resume-optimizer-api --region us-central1 \
  --set-env-vars CORS_ALLOWED_ORIGINS=https://yourdomain.com
```

Never `*`. The API accepts `Authorization` headers, and a wildcard origin
with credentials is both insecure and rejected by browsers.

**2. Firebase must trust the frontend domain.**

Firebase Console → Authentication → Settings → **Authorized domains** →
add `yourdomain.com` and the `*.pages.dev` preview domain. Google sign-in
fails on any unlisted domain even when everything else is correct.

**3. Enable the sign-in methods you offer.**

Firebase Console → Authentication → **Sign-in method**. Enable
**Email/Password** — it is off by default, and without it every email
sign-up fails with `auth/operation-not-allowed`. Enable **Google** too if
you offer that button.

---

## Step 5 — Verify

```bash
API=https://resume-optimizer-api-xxxxx-uc.a.run.app

# Backend alive
curl $API/health

# Public scoring works with no auth
curl -X POST $API/score/standalone -H "Content-Type: application/json" \
  -d '{"resume":{"basics":{"name":"Test","email":"t@example.com"}}}'

# Auth wired, not misconfigured: expect 401, NOT 503.
# A 503 means FIREBASE_SERVICE_ACCOUNT_JSON did not reach the container.
curl -i $API/auth/me

# CORS preflight from the real origin -- the check most often skipped.
curl -i -X OPTIONS $API/score/full-report \
  -H "Origin: https://yourdomain.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type"
```

The last one matters more than it looks. If `Access-Control-Allow-Headers`
does not include `authorization`, browsers silently strip the header and
every signed-in request looks anonymous to the backend — a failure that
`curl` without the preflight will not reveal.

Then in a browser: sign up, upload a PDF, run a scan, confirm it appears
in history.

**Set a budget alert before you walk away:**

Google Cloud Console → Billing → Budgets & alerts → create a budget of
$1 with alerts at 50% and 100%. At your volume it should never fire. If
it does, something is wrong and you will know within a day.

---

## Keeping it free

| Guard | Setting |
| --- | --- |
| Bounded spend | `--max-instances 3` — a bot cannot scale you into a bill |
| No idle cost | `--min-instances 0` — you pay only during requests |
| Request abuse | `RATE_LIMIT_REQUESTS=60` per IP per minute, already built in |
| Early warning | $1 budget alert |
| Database growth | Supabase dashboard shows usage against the 500 MB limit |

The one thing that could cost money is leaving `--min-instances 1` set.
An always-warm instance is roughly 432,000 GB-seconds a month against a
360,000 free allowance — so it tips just over the edge, to a few dollars.
Deliberate, but know that is the trade.

---

## Cold starts

This is the only place free hosting is visibly worse than paid, so it is
worth being precise rather than reassuring.

With `--min-instances 0`, a request arriving when no instance is running
pays roughly:

```
container start   ~1 s
app boot          ~2 s   (measured)
first scan        ~1.5 s (measured — lazy scikit-learn import)
                  ------
                  ~4.5 s worst case
```

Every subsequent request is 9 ms until the instance is recycled (Cloud Run
keeps instances ~15 minutes after the last request).

In practice, with 500 users spread over a day, most requests hit a warm
instance. The people who feel it are the first visitor of the morning and
anyone arriving after a quiet stretch.

Three ways to reduce it, cheapest first:

1. **Warm the lazy imports at startup.** Roughly 1.5 s of the cold path is
   scikit-learn importing on the *first scan*, not at boot. A FastAPI
   startup hook that runs one throwaway scoring pass moves that cost off
   the first user's request and into container start, where Cloud Run
   overlaps it with readiness. Costs nothing. **This is not implemented
   yet** — see the offer at the end of this document.
2. **Ping it on a schedule.** Cloud Scheduler's free tier includes 3 jobs.
   A `GET /health` every 10 minutes during your users' waking hours keeps
   an instance alive. Roughly 4,300 extra requests a month — still a
   rounding error against 2M. This is the pragmatic 90% fix.
3. **Set `--min-instances 1`.** Eliminates cold starts entirely, costs a
   few dollars a month. The honest paid option if the first two are not
   enough.

If cold starts are unacceptable and you want it genuinely free, that is
the case for **Oracle Cloud Always Free** instead: an always-on ARM VM,
free forever, no cold start ever. The cost is that you own the VM — nginx,
TLS certificates, systemd units, security updates — and Oracle frequently
has no capacity in popular regions.

---

## When you outgrow this

The architecture has two hard limits that appear well before you run out
of free tier. Both are documented in
[ARCHITECTURE.md](ARCHITECTURE.md#known-architectural-limits):

| Limit | Symptom | Fix |
| --- | --- | --- |
| Rate limiter is per-process | With `--max-instances 3`, the real ceiling is 3 × 60 requests/minute per IP, not 60 | Move the counter to Redis |
| Voice sessions are per-process | A user's second voice turn may land on a different instance and lose the session | Redis keyed by `session_id` |

Neither bites at 500 users with `--max-instances 3`. Both bite hard if you
raise that number. Fix them before you scale out, not after.

Database growth is the other axis: 500 MB is roughly 50,000–100,000 stored
scans. Supabase's next tier is $25/month.

---

## Related documents

- [DEPLOYMENT.md](DEPLOYMENT.md) — full production guidance
- [CONFIGURATION.md](CONFIGURATION.md) — every environment variable
- [SEO.md](SEO.md) — `VITE_SITE_URL` and the post-launch SEO checklist
- [ARCHITECTURE.md](ARCHITECTURE.md) — scaling limits in detail
