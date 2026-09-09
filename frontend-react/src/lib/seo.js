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
    "Check how your resume scores against any job description. Get an evidence-based ATS match report showing missing keywords, skill gaps, and exactly what to fix. Free with an account.",
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
    title: "Pricing — Free ATS Scans & Unlimited Plans",
    description:
      "Start free with 3 job-match scans a month. Upgrade for unlimited scans, full explainable breakdowns, and the voice-editing agent. Plans from $15/month.",
    keywords:
      "resume checker pricing, ats scanner cost, resume tool plans",
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
    // what the page actually shows.
    offers: [
      { "@type": "Offer", name: "Free", price: "0", priceCurrency: "USD" },
      { "@type": "Offer", name: "Starter", price: "15", priceCurrency: "USD" },
      { "@type": "Offer", name: "Pro", price: "29", priceCurrency: "USD" },
      { "@type": "Offer", name: "Pro+", price: "45", priceCurrency: "USD" },
    ],
    featureList: [
      "ATS resume scoring against a job description",
      "JD-less resume readiness analysis",
      "Missing keyword and skill gap detection",
      "Requirement-by-requirement evidence matching",
      "Job description bias auditing",
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
    a: "Yes. Scoring a resume against a job description and checking general ATS readiness are both free on the starter plan — you just need a free account, which is what saves your scan history to you. Paid plans add unlimited monthly scans and the voice-editing agent.",
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
    a: "Resumes are only stored when you're signed in, so they can appear in your scan history. Anonymous scans aren't persisted at all.",
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
