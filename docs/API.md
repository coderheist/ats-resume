# API Reference

Base URL (local): `http://localhost:8000`
Interactive docs: `http://localhost:8000/docs` · OpenAPI JSON: `/openapi.json`

Every example response in this document was captured from a running instance,
not written by hand.

- [Conventions](#conventions)
- [Authentication](#authentication)
- [Errors](#errors)
- [Rate limiting](#rate-limiting)
- [The JsonResume object](#the-jsonresume-object)
- [Endpoints](#endpoints)
  - [Health](#health)
  - [Resume parsing](#resume-parsing)
  - [Scoring](#scoring)
  - [Bias audit](#bias-audit)
  - [Voice agent](#voice-agent)
  - [Account](#account)
  - [Billing and payments](#billing-and-payments)

---

## Conventions

- All request and response bodies are JSON, except `POST /resume/parse-file`,
  which is `multipart/form-data`.
- Scores are returned on a **0–100** scale, rounded to one decimal, even though
  they are computed internally on 0–1.
- Weights are returned on a **0–1** scale.
- One exception to the scale rule: `score_delta` on `POST /voice/gap-answer` is
  on the 0–1 scale and may be negative. Treat it as a raw difference, not a
  percentage.
- Money is in the **smallest currency unit** (cents for USD, paise for INR).
- Timestamps are ISO 8601.

---

## Authentication

Authenticated routes take a Firebase ID token:

```http
Authorization: Bearer <firebase_id_token>
```

The backend verifies the token's signature server-side. A uid or email in a
request body is never trusted.

Three levels of protection:

| Level | Endpoints | Behavior |
| --- | --- | --- |
| **None** | `/health`, `/resume/*`, `/score/jd-match`, `/score/suggestions`, `/bias-audit/*`, `/voice/*`, `/billing/tiers` | No token used |
| **Optional** | `/score/full-report`, `/score/standalone` | Public. A valid token additionally saves the scan to history and counts it against the caller's monthly allowance. A *present but invalid* token is a `401`. |
| **Required** | `/auth/me`, `/history`, `/payments/create-order`, `/payments/verify` | `401` without a valid token |

`POST /payments/webhook` is authenticated by its Razorpay signature header
instead of a bearer token.

When `FIREBASE_SERVICE_ACCOUNT_JSON` is not configured, required-auth routes
return `503`; optional-auth routes treat every caller as anonymous.

---

## Errors

Errors use FastAPI's standard shape:

```json
{ "detail": "Invalid tier 'nope' -- must be one of: basic, medium, advanced." }
```

| Status | Meaning |
| --- | --- |
| `400` | Malformed request — unknown tier, empty text, free-plan checkout |
| `401` | Missing, invalid, or expired token |
| `413` | Upload exceeds the 10 MB cap |
| `422` | Pydantic validation failure, or an unsupported file type |
| `429` | Rate limit exceeded, or monthly scan allowance exhausted |
| `503` | A required optional integration (Firebase, Razorpay) is not configured |

Note that `429` covers two distinct conditions — read `detail` to distinguish a
per-IP rate limit (a string) from an exhausted plan allowance (an object):

```json
{
  "detail": {
    "error": "scan_limit_reached",
    "message": "You've used all 10 scans included in the Free plan this month. Your allowance resets on 01 October 2026 at 00:00 UTC.",
    "used": 10,
    "limit": 10,
    "tier": "free",
    "resets_at": "2026-10-01T00:00:00Z"
  }
}
```

`message` is a complete sentence, reset date included, for clients that only
want something to display. `resets_at` is explicitly UTC so a UI can render it
in the viewer's own timezone; the web client uses it to show a "you're out of
scans, resets in N days" dialog.

Parse endpoints deliberately do **not** return `5xx` for a difficult document.
An unreadable or image-only file returns `200` with an empty resume and a
plain-language entry in `warnings`.

---

## Rate limiting

Applied per client IP to `/resume/`, `/score/`, `/bias-audit/`, and `/voice/`.

| Setting | Default | Env var |
| --- | --- | --- |
| Requests per window | 60 | `RATE_LIMIT_REQUESTS` |
| Window length | 60s | `RATE_LIMIT_WINDOW_SECONDS` |

`/health`, `/billing/tiers`, `/auth/me`, and `/history` are not rate limited.

The limiter is in-memory and per-process — see
[ARCHITECTURE.md](ARCHITECTURE.md#known-architectural-limits).

---

## The JsonResume object

The canonical resume representation, based on the [JSON Resume](https://jsonresume.org/)
schema. Produced by the parse endpoints and accepted by every scoring endpoint.

```json
{
  "schema_version": "v1.0.0",
  "basics": {
    "name": "Jordan Alvarez",
    "label": "Backend Engineer",
    "email": "jordan@example.com",
    "phone": "+1-555-0100",
    "summary": "Backend engineer with 4 years building Python APIs.",
    "location": "Austin, TX"
  },
  "work": [
    {
      "name": "Acme",
      "position": "Backend Engineer",
      "start_date": "2021-03",
      "end_date": null,
      "highlights": [
        { "text": "Reduced p99 latency 40% by adding Redis caching to the checkout API." }
      ]
    }
  ],
  "education": [
    {
      "institution": "State University",
      "area": "Computer Science",
      "study_type": "Bachelor",
      "end_date": "2020-05"
    }
  ],
  "skills": [
    { "name": "Backend", "level": null, "keywords": ["Python", "FastAPI", "PostgreSQL", "Docker"] }
  ],
  "projects": [
    { "name": "Ledger", "description": "Double-entry bookkeeping library", "highlights": ["10k+ downloads"] }
  ]
}
```

Only `basics` is effectively required; every array defaults to empty. `end_date: null`
on a work entry means the role is current.

---

# Endpoints

## Health

### `GET /health`

Liveness probe. No auth, no rate limit.

```json
{ "status": "ok" }
```

---

## Resume parsing

Both endpoints run the deterministic-first pipeline described in
[ARCHITECTURE.md](ARCHITECTURE.md#parsing-pipeline): a heuristic parse, a
confidence gate, and an LLM escalation only when the gate demands it or a tier
is explicitly requested.

### `POST /resume/parse-file`

`multipart/form-data`. Accepts `.pdf` and `.docx`, up to **10 MB**.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `file` | file | yes | PDF or DOCX |
| `tier` | string | no | `basic` (Groq) · `medium` (Gemini) · `advanced` (Claude) |

```bash
curl -X POST http://localhost:8000/resume/parse-file \
  -F "file=@resume.pdf" \
  -F "tier=medium"
```

**Response `200`**

```json
{
  "resume": { "...": "JsonResume" },
  "parse_method": "llm",
  "warnings": [],
  "provider_used": "groq",
  "format_analysis": {
    "file_type": "pdf_text",
    "likely_multi_column": false,
    "embedded_image_count": 0,
    "has_tables": false,
    "contact_info_only_in_header_footer": false,
    "flags": []
  }
}
```

| Field | Meaning |
| --- | --- |
| `parse_method` | `"heuristic"` (no LLM call was made) or `"llm"` |
| `provider_used` | Which provider answered, or `null` for a heuristic parse |
| `warnings` | Plain-language notes — a failed LLM escalation, an image-only PDF, extraction caveats |
| `format_analysis` | Real layout/table/image risk analysis. Feeds the ATS-readability dimension of `/score/full-report` via `format_risk_count`. |

**Status codes:** `400` empty file · `413` over 10 MB · `422` unsupported type ·
`400` invalid `tier`

An unreadable document returns `200` with `resume: {}` and an explanatory
`warnings` entry — not an error status.

### `POST /resume/parse-text`

For pasted text, when there is no original file.

```json
{
  "text": "Jordan Alvarez\njordan@example.com\n\nEXPERIENCE\n...",
  "tier": "basic"
}
```

Same response shape as `parse-file`, minus `format_analysis` (there is no file
to analyze). `400` if `text` is empty.

> **Known issue.** On the default path — no `tier` given — a request that
> escalates to the LLM currently raises `AttributeError` and returns `500`
> ([resume.py:144](../app/api/routes/resume.py#L144),
> [resume.py:161](../app/api/routes/resume.py#L161)). This only occurs when an
> LLM API key is configured *and* the confidence gate escalates. Passing an
> explicit `tier` avoids it. See [Known issues](#known-issues).

---

## Scoring

### `POST /score/full-report`

**The primary scoring endpoint.** Seven-dimension JD screening report with
per-requirement evidence. Optional auth.

```json
{
  "resume": { "...": "JsonResume" },
  "jd_text": "Senior Backend Engineer. Required: 5+ years Python, PostgreSQL. Must have AWS experience. Kubernetes preferred.",
  "format_risk_count": 2
}
```

`format_risk_count` is optional and comes from a prior `parse-file` call's
`format_analysis`. The scoring layer only ever sees a `JsonResume`, never raw
file bytes, so real layout risks must be computed at upload time and threaded
through here. Omit it and ATS readability falls back to structural completeness alone.

**Response `200`** (abridged — captured from a live call)

```json
{
  "overall_score": 25.9,
  "classification": "Poor Match / High Risk",
  "knockout_risk": "HIGH",
  "dimensions": {
    "knockout_requirements": { "score": 0.0,   "weight": 0.30 },
    "technical_skills":      { "score": 0.0,   "weight": 0.20 },
    "semantic_fit":          { "score": 29.3,  "weight": 0.20 },
    "experience_match":      { "score": 100.0, "weight": 0.10 },
    "project_relevance":     { "score": 0.0,   "weight": 0.10 },
    "education_match":       { "score": 100.0, "weight": 0.05 },
    "ats_readability":       { "score": 100.0, "weight": 0.05 }
  },
  "requirements": [
    {
      "label": "aws",
      "kind": "skill",
      "tier": "knockout",
      "status": "knockout_risk",
      "evidence_strength": "no_evidence",
      "match_type": "none",
      "confidence": "high",
      "evidence_location": null,
      "detail": "No mention found anywhere in the resume."
    },
    {
      "label": "python",
      "kind": "skill",
      "tier": "knockout",
      "status": "knockout_risk",
      "evidence_strength": "weak",
      "match_type": "exact",
      "confidence": "high",
      "evidence_location": "Skills section (no supporting experience found)",
      "detail": "Listed as a keyword only -- not demonstrated through experience or a project."
    }
  ],
  "keyword_categories": {
    "exact_matches": [],
    "semantic_matches": [],
    "missing_keywords": ["aws", "kubernetes"],
    "weak_keywords": []
  },
  "strengths": [],
  "where_you_lack": [
    "Missing mandatory requirement: aws (No mention found anywhere in the resume.)"
  ],
  "relevance_gaps": [
    "Backend Engineer: \"Reduced p99 latency 40% by adding Redis caching to the checkout API.\""
  ],
  "suggestions": [
    "If you genuinely have experience with \"postgresql\", add a project or work-experience bullet describing the task, the technology, and a factual result -- never add a skill you don't have."
  ],
  "top_reasons_for_score": ["..."],
  "top_improvements_needed": ["..."],
  "keyword_stuffing_flags": []
}
```

**Requirement field values**

| Field | Values |
| --- | --- |
| `kind` | `skill` · `experience` · `education` |
| `tier` | `knockout` · `critical` · `important` · `preferred` · `optional` |
| `status` | `matched` · `partial` · `missing` · `knockout_risk` |
| `evidence_strength` | `strong` · `moderate` · `weak` · `no_evidence` |
| `match_type` | `exact` · `semantic` · `none` |
| `confidence` | `high` · `medium` · `low` |

A `knockout`-tier requirement that is fully satisfied has status `matched`, not
`knockout_risk`. Only a mandatory requirement that *fails* becomes a knockout
risk — presence and mandatoriness are independent axes.

Note in the example above that `python` and `postgresql` are present in the
skills list but still score as `knockout_risk` with `evidence_strength: "weak"`.
That is the design working: a keyword with no supporting experience is treated
as unproven, which is what a recruiter would conclude.

### `POST /score/standalone`

JD-less ATS readiness. Optional auth.

```json
{ "resume": { "...": "JsonResume" } }
```

**Response `200`**

```json
{
  "score": 87.5,
  "inferred_role": "data_engineer",
  "structural_completeness": 100.0,
  "action_verb_density": 100.0,
  "quantified_metric_density": 100.0,
  "active_voice_score": 100.0,
  "skill_coverage_score": 50.0,
  "weights_used": {
    "structural": 0.30,
    "quantified_metric": 0.20,
    "action_verb": 0.15,
    "active_voice": 0.10,
    "skill_coverage": 0.25
  },
  "missing_sections": [],
  "missing_ontology_skills": ["aws", "mongodb", "sql"],
  "format_issues": ["missing_phone"],
  "passive_voice_count": 0
}
```

`inferred_role` is `null` when the resume overlaps no role in the ontology. In
that case `skill_coverage_score` is neutral, not penalized — see
[ARCHITECTURE.md](ARCHITECTURE.md#mode-2--standalone-readiness-readinesspy).

### `POST /score/jd-match`

The simpler three-weight JD score, kept unchanged for existing callers. No auth,
no persistence, no entitlement checks. Prefer `/score/full-report` for new work.

```json
{ "resume": { "...": "JsonResume" }, "jd_text": "..." }
```

**Response `200`**

```json
{
  "score": 55.7,
  "breakdown": {
    "semantic_fit": 29.3,
    "skill_match": 50.0,
    "experience_match": 100.0
  },
  "matched_skills": ["postgresql", "python"],
  "skill_gaps": ["aws", "kubernetes"],
  "experience": {
    "required_years": null,
    "required_years_max": null,
    "candidate_years": 5.5,
    "unparseable_roles": []
  },
  "seniority_detected": "senior",
  "weights_used": { "semantic": 0.45, "skill": 0.25, "experience": 0.30 },
  "content_quality": {
    "unquantified_bullets": 0,
    "weak_verb_bullets": 0,
    "passive_voice_bullets": 0,
    "note": "Informational -- not part of the JD match score above."
  }
}
```

`weights_used` varies with `seniority_detected` — the response above shows the
senior profile, not the mid-level default. `content_quality` is informational
and deliberately excluded from `score`.

### `POST /score/suggestions`

Ranked Top-5 improvements. Mode is inferred from whether `jd_text` is present.

```json
{
  "resume": { "...": "JsonResume" },
  "jd_text": "Required: 5+ years Python and AWS.",
  "use_llm": false
}
```

`use_llm: false` (default) returns deterministic template phrasing and needs no
API key. `use_llm: true` calls the configured model and **falls back to the
template on any failure** — a missing key, a network error, or a provider error
never surfaces as an exception. Check `summary_source` to see which path ran.

**Response `200`**

```json
{
  "mode": "with_jd",
  "score": { "...": "the full breakdown for the inferred mode" },
  "suggestions": [
    {
      "category": "unquantified_bullet",
      "message": "Add a measurable result to your Backend Engineer role: \"Built and shipped the billing service.\"",
      "target": "Backend Engineer",
      "estimated_impact": 0.3,
      "score_context": "readability"
    },
    {
      "category": "format_issue",
      "message": "Add an Education section.",
      "target": null,
      "estimated_impact": 0.2,
      "score_context": "readability"
    }
  ],
  "summary": "1. Add a measurable result to your Backend Engineer role...\n2. Add an Education section.",
  "summary_source": "template"
}
```

`mode` is `"with_jd"` or `"no_jd"`. `summary_source` is `"template"` or `"llm"`.

---

## Bias audit

### `POST /bias-audit/jd`

Screens a job description for gendered and age-coded language.

```json
{ "jd_text": "Seeking an aggressive, competitive self-starter. Digital native preferred. Recent graduate welcome." }
```

**Response `200`**

```json
{
  "flagged": true,
  "agentic_count": 2,
  "communal_count": 0,
  "skew": 2,
  "agentic_terms_found": ["aggressive", "competitive"],
  "communal_terms_found": [],
  "ageist_terms_found": ["digital native", "recent graduate"],
  "suggested_rewrites": {
    "digital native": "comfortable with modern tools",
    "recent graduate": "early-career"
  },
  "disclaimer": "Heuristic wordlist screen, not legal or compliance advice."
}
```

`skew` is `agentic_count - communal_count`; a large positive skew correlates with
language research associates with lower application rates from women.

This is a **fixed wordlist screen**, not a semantic classifier. It matches only
the terms in its vocabulary — "rockstar" and "ninja", for instance, are not
currently in the list. The `disclaimer` field is returned on every response and
should be surfaced in any UI that displays these results.

---

## Voice agent

### `POST /voice/turn`

One turn of the slot-filling voice-editing dialogue.

The agent fills three slots before it can generate a resume highlight:

| Slot | Meaning |
| --- | --- |
| `scope` | Which system, team, or product |
| `scale` | How big — users, data volume, team size |
| `outcome_metric` | The measurable result |

```json
{
  "session_id": "abc-123",
  "transcript": "I led the payments migration",
  "extracted_slots": { "scope": "the payments platform" }
}
```

**Response** — while slots are still missing:

```json
{
  "action": "ask_clarifying_question",
  "question": "What changed as a result — a number, a percentage, or a time saved?",
  "missing_slot": "outcome_metric"
}
```

Slots accumulate across turns for a given `session_id`. Once all three are
filled:

```json
{
  "action": "generate_highlight",
  "ready_to_generate": true,
  "filled_slots": {
    "scope": "the payments platform",
    "scale": "2M users",
    "outcome_metric": "40% lower p99 latency"
  }
}
```

`action` is `ask_clarifying_question` or `generate_highlight`.

`extracted_slots` is accepted directly so the decision logic stays testable
without a live model call. In production these are extracted server-side via
tool calling before this endpoint's logic runs. Sessions are held in a
process-local dict — see [ARCHITECTURE.md](ARCHITECTURE.md#known-architectural-limits).

### `POST /voice/gap-prompt`

Step 1 of the gap-resolution loop: scores the resume and returns a targeted
question about the highest-priority missing skill.

```json
{ "resume": { "...": "JsonResume" }, "jd_text": "..." }
```

```json
{
  "done": false,
  "target_skill": "aws",
  "prompt": "I don't see \"aws\" backed by a project or role in your resume. Have you used it hands-on anywhere? If so, tell me what you built or did, and what happened.",
  "current_score": { "...": "jd-match breakdown" }
}
```

When nothing is left to ask about: `{ "done": true, "score": { ... } }`.

### `POST /voice/gap-answer`

Step 2: patches the candidate's answer into the resume and re-scores.

```json
{
  "resume": { "...": "JsonResume" },
  "jd_text": "...",
  "answer_text": "I ran our EKS cluster and moved the batch pipeline to Lambda.",
  "job_index": 0
}
```

```json
{
  "updated_resume": { "...": "JsonResume" },
  "before": { "...": "jd-match breakdown" },
  "after":  { "...": "jd-match breakdown" },
  "score_delta": -0.0083
}
```

`job_index` defaults to `0`, the most recent role. Call `gap-prompt` again with
`updated_resume` to continue the loop.

Two things to note about `score_delta`. It is on the **0–1 scale**, unlike the
`score` fields inside `before` and `after`, which are 0–100. And it **can be
negative** — adding a bullet lengthens the resume, which can dilute semantic
similarity more than the new evidence gains. Do not present it to users as a
guaranteed improvement.

---

## Account

### `GET /auth/me`

**Requires auth.** Creates the local user row and a free-tier subscription on
first call for a given Firebase uid — there is no separate registration endpoint.

```json
{
  "uid": "firebase-uid-123",
  "email": "jordan@example.com",
  "name": "Jordan Alvarez",
  "tier": "free",
  "tier_name": "Free",
  "jd_match_scans_per_month": 10,
  "jd_match_scans_used_this_month": 1,
  "jd_match_scans_reset_at": "2026-10-01T00:00:00Z",
  "jd_match_scans_exhausted": false
}
```

`jd_match_scans_per_month: null` means unlimited.

`jd_match_scans_reset_at` is midnight UTC on the 1st of next month — the instant
the used-this-month counter returns to zero. It is always present, including on
unlimited tiers, so a client rendering "resets on…" never has to special-case the
tier. `jd_match_scans_exhausted` is a convenience flag: true only when the tier
has a limit and the caller has reached it.

**Status codes:** `401` no or invalid token · `503` Firebase not configured

### `GET /history`

**Requires auth.** Every saved scan for the caller's resumes, newest first.

```json
{
  "history": [
    {
      "scan_id": "uuid",
      "resume_id": "uuid",
      "resume_name": "Jordan Alvarez",
      "mode": "jd_match",
      "jd_text": "Senior Backend Engineer. Required: 5+ years Python...",
      "final_score": 72.5,
      "created_at": "2026-09-07T10:14:03"
    }
  ]
}
```

`mode` is `"jd_match"` or `"standalone"`; `jd_text` is `null` for standalone
scans. `resume_name` is read from the stored resume's `basics.name` and may be
`null`.

This is a **summary list**. The stored per-scan `breakdown` is not included in
the response, so a client cannot re-render a full report from this endpoint
alone — it carries enough to build a history list and nothing more.

Only scans made **while signed in** appear here. Anonymous scans are never
persisted.

---

## Billing and payments

### `GET /billing/tiers`

Public. Pricing and entitlements, read straight from `app/config.py`.

```json
{
  "consumer": {
    "free": {
      "id": "free",
      "name": "Free",
      "monthly_price_usd": 0,
      "annual_price_usd": null,
      "jd_match_scans_per_month": 10,
      "voice_minutes_per_month": 0,
      "features": ["basic_ats_readiness_score", "json_resume_export"]
    },
    "starter": { "...": "$15/mo, $108/yr, unlimited scans" },
    "pro":     { "...": "$29/mo, $216/yr, 60 voice minutes" },
    "pro_plus":{ "...": "$45/mo, uncapped voice" }
  },
  "business": {
    "team":     { "...": "$79/mo" },
    "business": { "...": "$149/mo, SSO" }
  }
}
```

`null` for `jd_match_scans_per_month` or `voice_minutes_per_month` means
unlimited; `0` for voice minutes means not included.

### `POST /payments/create-order`

**Requires auth.** Opens a Razorpay order and records a `Payment` row in
`created` status before the user has paid.

```json
{ "tier": "pro", "billing_cycle": "monthly", "currency": "USD" }
```

```json
{
  "order_id": "order_XXXXXXXXXXXX",
  "amount": 2900,
  "currency": "USD",
  "key_id": "rzp_test_XXXXXXXX",
  "tier": "pro",
  "tier_name": "Pro"
}
```

`amount` is in the smallest currency unit. `key_id` is the **public** key for
opening Razorpay's Checkout widget — the secret is never returned.

**Status codes:** `400` unknown tier, invalid `billing_cycle`, a plan with no
annual price, or a free plan · `401` · `503` Razorpay not configured

### `POST /payments/verify`

**Requires auth.** The client-side confirmation path, called by Razorpay's
Checkout widget after payment completes in the browser.

```json
{
  "razorpay_order_id": "order_XXXX",
  "razorpay_payment_id": "pay_XXXX",
  "razorpay_signature": "hex-signature"
}
```

```json
{ "status": "paid", "tier": "pro" }
```

Idempotent — if the webhook already activated the subscription, this is a no-op.
A signature mismatch marks the payment `failed` and returns `400`.

**Status codes:** `400` verification failed · `404` no matching order for this
account · `401` · `503`

### `POST /payments/webhook`

Called by Razorpay's servers. **No bearer token** — authenticated solely by the
`X-Razorpay-Signature` header, verified against `RAZORPAY_WEBHOOK_SECRET` (a
different secret from `RAZORPAY_KEY_SECRET`).

Handles `payment.captured` and `payment.failed`. Idempotent with `/verify` in
both directions.

This is the authoritative path. `/verify` depends on the customer's browser
staying open; a closed tab must not mean a real payment goes unrecorded.

**Status codes:** `400` invalid signature · `503` Razorpay not configured

---

## Known issues

| Issue | Impact | Location |
| --- | --- | --- |
| `provider_used` crash | `POST /resume/parse-text` and `/resume/parse-file` return `500` when no `tier` is passed *and* the confidence gate escalates to the LLM. Requires a configured LLM key to trigger. Workaround: pass an explicit `tier`. | [resume.py:144](../app/api/routes/resume.py#L144), [resume.py:161](../app/api/routes/resume.py#L161) |
| `429` is overloaded | Rate limiting and exhausted plan allowance share a status code. Clients must read `detail` to tell them apart — a string for the former, an object with `error: "scan_limit_reached"` for the latter. | [scan.py:36](../app/api/routes/scan.py#L36), [rate_limit.py](../app/core/rate_limit.py) |
| Bias wordlist is fixed | Common coded terms outside the vocabulary are not detected. | [jd_bias_scanner.py:21](../app/core/bias_audit/jd_bias_scanner.py#L21) |

---

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — how scoring and parsing work internally
- [CONFIGURATION.md](CONFIGURATION.md) — environment variables
- [DEVELOPMENT.md](DEVELOPMENT.md) — running and testing locally
