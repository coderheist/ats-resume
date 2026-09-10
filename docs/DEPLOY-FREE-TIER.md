# Free-Tier Deployment Runbook

A practical deployment path for the resume optimizer using Vercel for the
frontend, a container host for the FastAPI backend, and Supabase for Postgres.

## Recommended stack

| Layer | Platform | Notes |
| --- | --- | --- |
| Frontend | Vercel | Static CDN deployment |
| Backend | Google Cloud Run, Render, or Railway | Runs the Docker image |
| Database | Supabase | Postgres with pgvector |

The backend should not run as Vercel serverless functions. The in-memory rate
limiter and voice session store assume a long-lived process.

## Step 1: Database

1. Create a Supabase project near the backend region.
2. Enable pgvector in the SQL editor:

   ```sql
   create extension if not exists vector;
   ```

3. Dashboard -> **Connect** -> **Session pooler** (not Transaction: this is a
   long-running process, and SQLAlchemy expects session-level features that
   pgbouncer's transaction mode does not provide). The string looks like:

   ```text
   postgres://postgres.[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:5432/postgres
   ```

   Two things Supabase does **not** do for you:

   - **`?sslmode=require` is not included** -- append it yourself. Supabase
     requires SSL and psycopg2 would negotiate it anyway under its default
     `sslmode=prefer`, so this is about making the requirement explicit rather
     than leaving it to a default that could silently downgrade.
   - **The password is not URL-encoded.** If it contains `@`, `:`, `/`, `#` or
     `?`, percent-encode it or the URL parses into the wrong host and the
     failure looks like a DNS or auth error rather than a quoting one.

   The scheme Supabase hands you is `postgres://`, which SQLAlchemy 2.x no
   longer accepts. `app/db/session.py` rewrites it to `postgresql://` on
   startup, so either form works here -- paste it as given.
4. Apply migrations from the repository root:

   ```bash
   DATABASE_URL="postgresql://...?sslmode=require" alembic upgrade head
   DATABASE_URL="..." alembic current
   ```

## Step 2: Backend

Deploy the root `Dockerfile` to Cloud Run, Render, Railway, or another
long-running container platform.

For Render specifically, [`render.yaml`](../render.yaml) is a blueprint that
declares the service and every variable below: **New -> Blueprint**, point it at
this repository, then fill in the secrets it deliberately leaves blank. It
already sets `TRUSTED_PROXY_HOPS=1`, which matters on any platform that
terminates TLS at its own proxy -- left at `0` the per-IP rate limiter sees only
that proxy, collapses to one bucket, and unrelated users start 429ing each
other.

Set these server-side variables as needed:

- `DATABASE_URL`
- `FIREBASE_SERVICE_ACCOUNT_JSON`
- `CORS_ALLOWED_ORIGINS`
- `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, and/or `GROQ_API_KEY`
- `LLM_PROVIDER`
- `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET`

The Docker container binds `${PORT:-8000}`. Run `alembic upgrade head` as a
release or pre-deploy step, not during application startup.

Verify the backend:

```bash
curl https://api.example.com/health
```

## Step 3: Frontend on Vercel

1. Import the repository into Vercel.
2. Leave **Root Directory** blank. The root [`vercel.json`](../vercel.json)
   controls installation, building, output, and client-only route rewrites.
3. Use framework preset **Other**.
4. Configure these Vercel build-time variables:

   ```text
   VITE_SITE_URL=https://your-project.vercel.app
   VITE_API_BASE_URL=https://api.example.com
   VITE_FIREBASE_API_KEY=...
   VITE_FIREBASE_AUTH_DOMAIN=...
   VITE_FIREBASE_PROJECT_ID=...
   VITE_FIREBASE_APP_ID=...
   ```

5. Deploy and test the production domain. `VITE_*` values are public and are
   compiled into the frontend bundle, so never put server secrets in them.

`VITE_SITE_URL` must be the real frontend origin. It controls canonical URLs,
social metadata, `sitemap.xml`, and `robots.txt`.

## Step 4: Connect the services

Set the backend's `CORS_ALLOWED_ORIGINS` to the production Vercel origin:

```text
CORS_ALLOWED_ORIGINS=https://your-project.vercel.app
```

Add the production Vercel domain and any custom domain to Firebase Authorized
domains. Enable every Firebase sign-in method exposed by the UI, including
Email/Password and Google.

Disable Vercel Deployment Protection for production, or configure it so public
users are not redirected to a Vercel login wall.

## Step 5: Verify

```bash
API=https://api.example.com

curl "$API/health"
curl -X POST "$API/score/standalone" \
  -H "Content-Type: application/json" \
  -d '{"resume":{"basics":{"name":"Test","email":"t@example.com"}}}'

curl -i -X OPTIONS "$API/score/full-report" \
  -H "Origin: https://your-project.vercel.app" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization,content-type"
```

Then test sign-up, sign-in, resume upload, scoring, and scan history in the
browser. Keep a budget alert enabled on any paid backend or database account.
