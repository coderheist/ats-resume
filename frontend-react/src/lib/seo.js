/**
 * SEO metadata: one source of truth for every public route.
 *
 * Two consumers read PAGE_SEO below, which is why it's plain data in its
 * own module rather than JSX scattered across page components:
 *
 *   1. useSeo() -- the runtime hook. Updates <title>, the meta
 *      description, canonical, and the Open Graph / Twitter tags on
 *      client-side navigation, so a route change actually changes what a
 *      JS-executing crawler (Googlebot) and the browser tab both see.
 *   2. scripts/prerender.mjs -- the build step. Bakes the same values
 *      into real static HTML per route, because the crawlers that matter
 *      most for link previews (Facebook, LinkedIn, Slack, Twitter/X) and
 *      for Bing do NOT execute JavaScript. A meta tag that only exists
 *      after React mounts is invisible to them.
 *
 * Keeping both paths on one object is what stops them drifting -- a
 * route whose runtime title says one thing and whose prerendered HTML
 * says another is worse than having neither, because it looks correct in
 * the browser while being wrong everywhere it's actually indexed.
 *
 * No react-helmet dependency: this app needs to set roughly eight tags on
 * six routes, which is a small enough job to own outright, consistent
 * with how the rate limiter and embeddings fallback are handled on the
 * backend.
 */

// The deployed origin. MUST be set for a real deployment -- canonical
// URLs, og:url, and the sitemap all derive from it, and pointing them at
// the wrong host is worse than omitting them (it tells Google the
// canonical version of every page lives somewhere else). Set VITE_SITE_URL
// at build time; the fallback below is a placeholder, not a real domain.
export const SITE_URL = (
  import.meta.env?.VITE_SITE_URL || "https://resume-optimizer.example.com"
).replace(/\/$/, "");

export const SITE_NAME = "Resume Optimizer";

// Social preview image. 1200x630 is the size Facebook/LinkedIn/X all
// crop predictably; anything else gets cropped differently per platform.
export const OG_IMAGE = `${SITE_URL}/og-image.png`;

export const DEFAULT_SEO = {
  title: "Resume Optimizer — Free ATS Resume Checker & Job Match Score",
  description:
    "Check how your resume scores against any job description, then rewrite weak bullet points with AI that never invents a number. Evidence-based ATS analysis: missing keywords, skill gaps, and exactly what to fix. Free to try.",
};

/**
 * Per-route metadata.
 *
 * Titles are written to sit under ~60 characters before the site-name
 * suffix, and descriptions under ~155, because Google truncates past
 * roughly those widths in results. Each targets the phrasing a person
 * actually types into a search box ("ats resume checker", "resume job
 * description match") rather than internal product vocabulary -- nobody
 * searches for "standalone readiness scoring".
 *
 * `noindex` marks routes that must never be indexed: authenticated
 * surfaces with no public content, and the auth pages themselves, which
 * are thin duplicate-content pages that dilute crawl budget and can
 * outrank the pages you actually want found.
 */
export const PAGE_SEO = {
  "/": {
    title: "Free ATS Resume Checker & Job Match Score",
    description:
      "See how your resume scores against any job description. Evidence-based ATS analysis: missing keywords, skill gaps, and what to fix first. Free with an account.",
    keywords:
      "ats resume checker, resume scanner, resume job description match, free resume checker, applicant tracking system, resume keyword scanner",
  },
  "/with-jd": {
    title: "Match Your Resume to a Job Description",
    description:
      "Paste a job description for a requirement-by-requirement match report: knockout requirements, missing keywords, evidence strength, ranked fixes. Free.",
    keywords:
      "resume job description match, resume keyword matcher, tailor resume to job, ats keyword scanner, job description analyzer",
  },
  "/without-jd": {
    title: "Free ATS Resume Score — No Job Description Needed",
    description:
      "Check how ATS-ready your resume is without a job posting. Scores structure, quantified achievements, action verbs, and skill coverage, with specific fixes.",
    keywords:
      "ats resume score, resume readiness check, free resume grader, resume checker no job description, resume analysis tool",
  },
  "/pricing": {
    title: "Pricing — Resume Scans & AI Rewrites from ₹149",
    description:
      "Start free with 5 scans and 3 AI rewrites a month. One-time passes from ₹149 - no subscription, nothing to cancel. Pro: ₹399 for 100 scans, 100 rewrites.",
    keywords:
      "resume checker pricing india, ats scanner cost, ai resume rewrite price, resume tool plans",
  },
  "/login": {
    title: "Sign In",
    description: "Sign in to your Resume Optimizer account to view saved scans and history.",
    noindex: true,
  },
  "/signup": {
    title: "Create an Account",
    description: "Create a Resume Optimizer account to save your scans and track improvements over time.",
    noindex: true,
  },
  "/dashboard": { title: "Dashboard", description: "Your resume dashboard.", noindex: true },
  "/history": { title: "Scan History", description: "Your past resume scans.", noindex: true },
  "/settings": { title: "Settings", description: "Your account settings.", noindex: true },
};

/** Routes that belong in sitemap.xml -- public and indexable only. */
export const INDEXABLE_ROUTES = Object.keys(PAGE_SEO).filter((p) => !PAGE_SEO[p].noindex);

/**
 * Full <title> for a route. The site name is appended rather than baked
 * into each title so the per-page part stays first -- search results and
 * browser tabs both truncate from the right, so the distinguishing words
 * have to lead.
 */
export function titleFor(path) {
  const page = PAGE_SEO[path];
  if (!page) return DEFAULT_SEO.title;
  return page.title.includes(SITE_NAME) ? page.title : `${page.title} | ${SITE_NAME}`;
}

export function seoFor(path) {
  const page = PAGE_SEO[path] || {};
  return {
    title: titleFor(path),
    description: page.description || DEFAULT_SEO.description,
    keywords: page.keywords || null,
    canonical: `${SITE_URL}${path === "/" ? "/" : path}`,
    noindex: Boolean(page.noindex),
  };
}

// ---------------------------------------------------------------------
// Structured data (JSON-LD)
// ---------------------------------------------------------------------
// Emitted into the static HTML by the prerender step rather than at
// runtime: Google's rich-results parsing is far more reliable against
// markup present in the initial response, and these values never depend
// on client state.

/**
 * The plan ladder, as the marketing surfaces need it.
 *
 * app/config.py is the real source of truth -- it is what checkout
 * charges. This is a build-time mirror, needed because three things have
 * to state prices in static HTML that exists before any API call: the
 * SoftwareApplication offers, llms.txt, and the prerendered pricing
 * summary. A crawler or an assistant reading the page gets whatever is
 * in the served markup, so "fetch it at runtime" is not available to
 * them.
 *
 * A mirror can drift, and a pricing page that contradicts checkout is
 * worse than one that says nothing -- so it is not left to discipline:
 * tests/test_pricing_copy_matches_config.py parses this array and fails
 * the backend suite if any number here disagrees with B2C_TIERS.
 */
export const PLANS = [
  { id: "free", name: "Free", inr: 0, usd: 0, days: 30, scans: 5, rewrites: 3 },
  { id: "boost", name: "Boost", inr: 149, usd: 4.99, days: 7, scans: 30, rewrites: 30 },
  { id: "pro", name: "Pro", inr: 399, usd: 12.99, days: 30, scans: 100, rewrites: 100 },
  { id: "pro_season", name: "Pro Season", inr: 999, usd: 29.99, days: 90, scans: 300, rewrites: 300 },
];

/** "for 7 days" / "for 30 days" -- the buyer's words, from one place. */
export function planDurationLabel(days) {
  if (days % 30 === 0 && days > 30) return `for ${days / 30} months`;
  return `for ${days} days`;
}

export function softwareApplicationLd() {
  return {
    "@context": "https://schema.org",
    "@type": "SoftwareApplication",
    name: SITE_NAME,
    applicationCategory: "BusinessApplication",
    applicationSubCategory: "Resume Analysis",
    operatingSystem: "Any (web-based)",
    url: SITE_URL,
    description: DEFAULT_SEO.description,
    // Reflects app/config.py's B2C_TIERS. Keep these in step with the
    // real prices -- Google penalises structured data that contradicts
    // what the page actually shows, and the pricing page reads its
    // numbers from the backend, so a stale copy here is visible.
    //
    // Both currencies are listed because they are separate listed prices
    // set at local price points, not conversions of one another (see
    // config.py) -- INR is the primary market.
    offers: PLANS.flatMap((p) => [
      { "@type": "Offer", name: p.name, price: String(p.inr), priceCurrency: "INR" },
      ...(p.inr === 0 ? [] : [{ "@type": "Offer", name: p.name, price: String(p.usd), priceCurrency: "USD" }]),
    ]),
    featureList: [
      "ATS resume scoring against a job description",
      "AI rewriting of resume bullet points",
      "JD-less resume readiness analysis",
      "Missing keyword and skill gap detection",
      "Requirement-by-requirement evidence matching",
    ],
  };
}

export function organizationLd() {
  return {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: SITE_NAME,
    url: SITE_URL,
    logo: `${SITE_URL}/icon-512.png`,
  };
}

/**
 * The FAQ shown on the landing page, and the source of its FAQPage
 * structured data. Both render from this one array so the markup can
 * never claim an answer the page doesn't actually display -- Google
 * treats that as a structured-data violation, and it's also just
 * dishonest.
 */
export const FAQ = [
  {
    q: "Is this resume checker free?",
    a: "Yes. Scoring a resume against a job description and checking general ATS readiness are both free, and you can run a scan without an account at all. A free account adds saved scan history, 5 scans a month, and 3 AI bullet rewrites a month. Paid plans raise those allowances.",
  },
  {
    q: "How much does it cost?",
    a: "Plans are one-time passes, not subscriptions — nothing renews on its own and there is nothing to cancel. Boost is ₹149 for 7 days (30 scans, 30 rewrites), Pro is ₹399 for 30 days (100 scans, 100 rewrites), and Pro Season is ₹999 for 90 days (300 scans, 300 rewrites). In US dollars those are $4.99, $12.99 and $29.99.",
  },
  {
    q: "What does the AI resume rewrite actually do?",
    a: "It rewrites the bullet points under one role into stronger lines: an action verb, the specific scope of what you did, and the outcome it produced. When a job description is supplied it prefers that posting's vocabulary, but only where your stated experience genuinely matches it.",
  },
  {
    q: "Will the AI invent achievements or numbers on my resume?",
    a: "No. The rewriter is explicitly prohibited from inventing or estimating any figure that is not in your original bullet, because a fabricated metric is a claim you would have to defend in an interview and could not. When a bullet has no measurable outcome, it improves the verb, scope and phrasing, then flags the bullet and asks you for the specific number that is missing.",
  },
  {
    q: "What is an ATS and why does my resume score matter?",
    a: "An applicant tracking system is the software employers use to store and filter applications. Many recruiters search and rank within it by keyword and requirement, so a resume that doesn't clearly evidence a job's stated requirements can be filtered out before a person reads it.",
  },
  {
    q: "How does the match score work?",
    a: "The job description is parsed into individual requirements, each tiered by how the posting words it — 'must have' is treated differently from 'nice to have'. Each requirement is then matched against evidence in your resume, and seven weighted dimensions combine into the overall score. Every number comes with the reasoning behind it.",
  },
  {
    q: "Why did a skill I listed still count as missing?",
    a: "A skill listed only in a skills section, with no supporting project or work experience, is scored as weak evidence rather than a full match. That mirrors how a recruiter reads a resume: a keyword with nothing behind it doesn't demonstrate the skill. Adding a bullet describing what you built with it resolves this.",
  },
  {
    q: "What file formats can I upload?",
    a: "PDF and DOCX, up to 10 MB. You can also paste your resume as plain text. Scanned or image-only PDFs can't be read reliably — if that happens you'll be told so directly rather than shown a low score based on nothing.",
  },
  {
    q: "Is my resume data kept private?",
    a: "Resumes are only stored when you're signed in, so they can appear in your scan history. Anonymous scans aren't persisted at all, and your resume is never sold or used to train a model.",
  },
];

export function faqPageLd() {
  return {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: FAQ.map(({ q, a }) => ({
      "@type": "Question",
      name: q,
      acceptedAnswer: { "@type": "Answer", text: a },
    })),
  };
}

// ---------------------------------------------------------------------
// Runtime hook
// ---------------------------------------------------------------------

function setTag(selector, attrs) {
  if (typeof document === "undefined") return;
  let el = document.head.querySelector(selector);
  if (!el) {
    el = document.createElement(attrs.tag || "meta");
    document.head.appendChild(el);
  }
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "tag") continue;
    if (v === null || v === undefined) el.removeAttribute(k);
    else el.setAttribute(k, v);
  }
}

/**
 * Applies a route's metadata to the live document.
 *
 * Deliberately not wrapped in useEffect by the caller: it's called from
 * page components during render via useEffect internally, so the tags
 * update on every client-side navigation. Without this, a SPA keeps the
 * index.html title and description on every route -- which is how a
 * six-page site ends up with one page indexed.
 */
export function applySeo(path) {
  if (typeof document === "undefined") return;
  const seo = seoFor(path);

  document.title = seo.title;
  setTag('meta[name="description"]', { name: "description", content: seo.description });
  setTag('link[rel="canonical"]', { tag: "link", rel: "canonical", href: seo.canonical });
  setTag('meta[name="robots"]', {
    name: "robots",
    content: seo.noindex ? "noindex, nofollow" : "index, follow, max-image-preview:large",
  });

  setTag('meta[property="og:title"]', { property: "og:title", content: seo.title });
  setTag('meta[property="og:description"]', { property: "og:description", content: seo.description });
  setTag('meta[property="og:url"]', { property: "og:url", content: seo.canonical });

  setTag('meta[name="twitter:title"]', { name: "twitter:title", content: seo.title });
  setTag('meta[name="twitter:description"]', { name: "twitter:description", content: seo.description });

  if (seo.keywords) {
    setTag('meta[name="keywords"]', { name: "keywords", content: seo.keywords });
  }
}


// ---------------------------------------------------------------------
// AI crawlers: robots.txt and llms.txt (GEO / AEO)
// ---------------------------------------------------------------------

/**
 * AI crawlers this site takes an explicit position on.
 *
 * Stating a position matters because silence is not neutral. Several of
 * these -- Google-Extended most notably -- are allowed by default, so a
 * robots.txt that never mentions them makes "we never thought about it"
 * and "we opted in deliberately" look identical from the outside.
 *
 * `purpose` records WHY each is allowed, because the trade-off differs:
 *
 *   "search"   -- fetches a page to answer a question a user is asking
 *                 now, and cites the source. That is a referral channel,
 *                 and for a tool people find by asking "how do I check my
 *                 resume against a job description" it is the whole
 *                 opportunity.
 *   "training" -- takes content to train future models, with no citation
 *                 and no traffic back. Allowed here anyway: the reachable
 *                 pages are public marketing and explanatory copy, and
 *                 presence in model weights is itself how a tool gets
 *                 recommended when someone asks an assistant for one.
 *
 * None of this exposes user data. Every authenticated surface is
 * noindex'd and disallowed, so no resume, scan or account page is
 * reachable by any crawler whatever its purpose.
 *
 * To opt out of training while keeping AI-search referrals, flip the
 * "training" entries to allow: false. Nothing else needs to change.
 */
export const AI_CRAWLERS = [
  { name: "OAI-SearchBot", purpose: "search", allow: true },
  { name: "PerplexityBot", purpose: "search", allow: true },
  { name: "ClaudeBot", purpose: "search", allow: true },
  { name: "GPTBot", purpose: "training", allow: true },
  { name: "Google-Extended", purpose: "training", allow: true },
  { name: "CCBot", purpose: "training", allow: true },
];

/**
 * The full robots.txt body.
 *
 * Lives here rather than in scripts/prerender.mjs because the build
 * OVERWRITES public/robots.txt in the output -- so a rule added only to
 * the static file silently disappears from every real deployment. One
 * generator, used by the build and mirrored by the static fallback, is
 * the only arrangement where that cannot happen.
 */
export function robotsTxt(siteUrl = SITE_URL) {
  const noindexRoutes = Object.keys(PAGE_SEO).filter((p) => PAGE_SEO[p].noindex);
  const aiBlocks = AI_CRAWLERS.map(
    ({ name, purpose, allow }) =>
      `# ${purpose === "search" ? "AI search / answer engine -- cites and refers traffic" : "Model training -- no citation, no referral"}\n` +
      `User-agent: ${name}\n${allow ? "Allow" : "Disallow"}: /`
  ).join("\n\n");

  return `User-agent: *
Allow: /

# Authenticated surfaces and auth pages. These have no public content:
# indexing them wastes crawl budget and can surface a thin sign-in page
# above the tool pages people are actually searching for.
${noindexRoutes.map((r) => `Disallow: ${r}`).join("\n")}

${aiBlocks}

Sitemap: ${siteUrl}/sitemap.xml
`;
}

/**
 * /llms.txt -- a plain-text brief for language models reading this site.
 *
 * The convention (llmstxt.org) exists because an assistant answering
 * "what's a good ATS resume checker?" is working from whatever prose it
 * can extract, and a React app's rendered HTML is a poor summary of what
 * the product does. This states it directly.
 *
 * Written as facts a model can quote, not marketing. Two things here are
 * deliberate and both are about not being misrepresented: the pricing is
 * stated with its real currency and pass length, because an assistant
 * that says "it's a $29/month subscription" costs a sale from someone
 * who would have paid Rs 399 once; and the limits section is included at
 * all, because a model that oversells the tool produces users who arrive
 * expecting something it does not do.
 */
export function llmsTxt(siteUrl = SITE_URL) {
  return `# ${SITE_NAME}

> ${DEFAULT_SEO.description}

${SITE_NAME} is a free web tool that scores a resume against a specific job
description and rewrites weak bullet points with AI. It is aimed at job
seekers, and priced for the Indian market.

## What it does

- **Job-description match report.** Parses a posting into individual
  requirements, tiers each by how the posting words it ("must have" is
  weighted differently from "nice to have"), and matches each against
  evidence in the resume. Seven weighted dimensions combine into an
  overall score, and every number is reported with its reasoning.
- **ATS readiness check.** Scores a resume with no job posting at all:
  structural completeness, quantified achievements, action-verb density,
  active vs. passive voice, and skill coverage.
- **AI bullet rewriting.** Rewrites the bullets under one role into
  stronger lines -- action verb, specific scope, measurable outcome --
  optionally tailored to a job description.
- **Parser-safety checks.** Flags multi-column layouts, tables, embedded
  images and header/footer contact details, which are the common ways a
  visually polished resume becomes unreadable to the software that
  processes it first.

## What it will not do

- **It never invents a metric.** The rewriter is prohibited from adding
  any figure not present in the original bullet. A fabricated number is a
  claim the candidate must defend in an interview and cannot. Where a
  bullet has no measurable outcome, the tool improves the verb, scope and
  phrasing, then asks the user for the missing number rather than
  guessing it.
- **It does not predict whether you will get an interview.** It measures
  how well a resume evidences one posting's stated requirements. It has
  no visibility into other applicants or the hiring manager's priorities.
- **It does not read scanned or image-only PDFs reliably.** When that
  happens the user is told directly rather than shown a low score based
  on nothing.

## Pricing

All plans are one-time passes, not auto-renewing subscriptions. Nothing
renews on its own and there is nothing to cancel. Buying while a pass is
running adds to the remaining days.

| Plan | Price | Valid | Scans | AI rewrites |
| --- | --- | --- | --- | --- |
${PLANS.map((p) => `| ${p.name} | ${p.inr === 0 ? "Free" : `Rs ${p.inr} / $${p.usd}`} | ${p.inr === 0 ? "monthly reset" : `${p.days} days`} | ${p.scans} | ${p.rewrites} |`).join("\n")}

Scanning works without an account. A free account adds saved history and
AI rewrites. Rupee and dollar prices are separate listed prices set for
their own markets, not conversions of one another.

## Privacy

Resumes are stored only for signed-in users, so they can appear in scan
history. Anonymous scans are not persisted. Resume content is not sold
and is not used to train models.

## Key pages

${INDEXABLE_ROUTES.map((r) => `- [${PAGE_SEO[r].title}](${siteUrl}${r === "/" ? "/" : r}): ${PAGE_SEO[r].description}`).join("\n")}
`;
}
