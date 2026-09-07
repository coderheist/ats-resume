# SEO Guide

How search visibility is implemented in this project, what it covers, and
what still has to be done by hand after deploying.

- [The core problem](#the-core-problem)
- [What was built](#what-was-built)
- [Required deployment step](#required-deployment-step)
- [How the build works](#how-the-build-works)
- [Adding or changing a route](#adding-or-changing-a-route)
- [Verifying it works](#verifying-it-works)
- [Post-launch checklist](#post-launch-checklist)
- [What this does not do](#what-this-does-not-do)

---

## The core problem

A Vite single-page app serves every URL as the same near-empty shell:

```html
<div id="root"></div>
<script type="module" src="/assets/index-abc123.js"></script>
```

There is no heading, no copy, no per-page title. That matters differently
depending on who is fetching it:

| Crawler | Executes JavaScript | Consequence before this work |
| --- | --- | --- |
| Googlebot | Yes, on a deferred second pass | Indexable, but slowly and at the cost of crawl budget — every page shared one title and one description |
| Bingbot | Partially, inconsistently | Frequently indexed as an empty page |
| Facebook, LinkedIn, Slack, X | **No** | Shared links produced a blank preview card |

Adding static meta tags fixes the preview card but not the "this page has
no content" problem. Fixing both needs the HTML to contain the actual page
when it is served — which is what the prerender step does.

---

## What was built

| Area | Implementation |
| --- | --- |
| Route metadata | [src/lib/seo.js](../frontend-react/src/lib/seo.js) — one `PAGE_SEO` map read by both the runtime hook and the build script |
| Runtime tag updates | [src/lib/useSeo.js](../frontend-react/src/lib/useSeo.js) — one call at the app root updates title/description/canonical/OG on every client-side navigation |
| Static prerendering | [scripts/prerender.mjs](../frontend-react/scripts/prerender.mjs) — renders each public route to real HTML at build time |
| Base head tags | [index.html](../frontend-react/index.html) — full Open Graph, Twitter card, theme colour, manifest link |
| Structured data | `SoftwareApplication` and `Organization` on every page, `FAQPage` on `/` only |
| `robots.txt` / `sitemap.xml` | Generated at build from `INDEXABLE_ROUTES`, so they cannot drift from the app |
| Social/PWA images | [scripts/generate-og-assets.py](../frontend-react/scripts/generate-og-assets.py) — 1200×630 OG card plus the icon set |
| Landing content | [pages/Hero.jsx](../frontend-react/src/pages/Hero.jsx) — how-it-works, scoring dimensions, FAQ |
| Tool page content | [components/SeoContent.jsx](../frontend-react/src/components/SeoContent.jsx) — substantive copy on `/with-jd` and `/without-jd` |
| Performance | Route code-splitting and vendor chunking — Core Web Vitals is a ranking signal |

### Measured result

Crawlable text in the served HTML, before and after:

| Route | Before | After |
| --- | --- | --- |
| `/` | 0 | 4,213 chars |
| `/with-jd` | 0 | ~2,900 chars |
| `/without-jd` | 0 | ~2,700 chars |
| `/pricing` | 0 | ~700 chars |

Initial JavaScript payload:

| | Before | After |
| --- | --- | --- |
| Main app chunk | 520 KB (147 KB gzip) | **58 KB (18 KB gzip)** |
| Vendor chunks | — | react 164 KB · firebase 173 KB · motion 120 KB, cached independently |
| Authenticated routes | in main bundle | separate chunks, not fetched on first visit |

---

## Required deployment step

**`VITE_SITE_URL` must be set at build time.** Everything absolute derives
from it: canonical URLs, `og:url`, `og:image`, the sitemap, and the
`Sitemap:` line in `robots.txt`.

```bash
VITE_SITE_URL=https://yourdomain.com npm run build
```

Left unset, the build completes but stamps every canonical URL with the
placeholder `resume-optimizer.example.com`. That is worse than having no
canonical at all — it tells Google the real version of every page lives on
a domain you do not own, which can suppress your own pages from results.

The build prints a loud warning when this happens. Do not ignore it.

---

## How the build works

`npm run build` runs three steps:

```
1. build:client    vite build
                   → frontend-react-dist/ — hashed assets + shell index.html

2. build:ssr       vite build --ssr src/entry-server.jsx --outDir .prerender-ssr
                   → a Node-importable bundle exporting render(path),
                     plus everything re-exported from lib/seo.js

3. prerender       node scripts/prerender.mjs
                   → for each indexable route:
                       renderToString(<App> at that path)
                       inject into the shell's <div id="root">
                       rewrite title/description/canonical/OG per route
                       swap the placeholder origin for VITE_SITE_URL
                       append JSON-LD
                       write dist/<route>/index.html
                   → generate sitemap.xml and robots.txt
```

Output:

```
frontend-react-dist/
├── index.html              prerendered /
├── with-jd/index.html      prerendered /with-jd
├── without-jd/index.html   prerendered /without-jd
├── pricing/index.html      prerendered /pricing
├── robots.txt              generated
├── sitemap.xml             generated
├── site.webmanifest
├── og-image.png            1200x630
├── icon-192.png · icon-512.png · icon-512-maskable.png
└── assets/                 hashed JS and CSS
```

The directory-per-route layout means every URL resolves without host-specific
rewrite rules. Static hosts serve `/pricing` from `pricing/index.html`
automatically.

`npm run build:spa` still produces a plain SPA build with no prerendering,
if you need it.

### Two design decisions worth knowing

**Prerendering is not hydration.** The client still uses `createRoot`, not
`hydrateRoot`, so React discards the prerendered markup and re-renders on
mount. This is deliberate: the navbar and several pages render differently
for a signed-in user, and a hydration mismatch against auth-dependent
markup causes console errors and, worse, silently dead event handlers.
The prerendered HTML buys crawlability and a fast first paint. It is not
full SSR and is not claimed to be.

**Prerendered pages are always the signed-out view.** Effects do not run
during `renderToString`, so data fetched in `useEffect` is absent. This is
correct for static HTML — it is what a crawler and a first-time visitor
should see — but it is why `/pricing` prerenders thin: its tiers come from
`GET /billing/tiers` at runtime.

---

## Adding or changing a route

Everything flows from `PAGE_SEO` in [seo.js](../frontend-react/src/lib/seo.js):

```js
"/cover-letter": {
  title: "Free Cover Letter Generator",          // ≤ 60 chars
  description: "Generate a tailored cover letter…", // ≤ 160 chars
  keywords: "cover letter generator, ai cover letter",
},
```

Add the entry and the route is automatically titled at runtime,
prerendered, added to `sitemap.xml`, and covered by the test suite. Add
`noindex: true` instead and it is excluded from the sitemap, prerendering,
and gains a `noindex` robots tag plus a `Disallow` line.

The length limits are enforced by [seo.test.js](../frontend-react/src/lib/seo.test.js),
which also checks that no two indexable routes share a title or
description — duplicate metadata makes Google collapse pages and show only
one of them.

### Regenerating images

```bash
cd frontend-react
python scripts/generate-og-assets.py    # needs pillow
```

Pillow is intentionally not in `requirements.txt`. This is a one-off asset
generator, the PNGs are committed, and no build step depends on it.

---

## Verifying it works

### Locally

```bash
cd frontend-react
VITE_SITE_URL=https://yourdomain.com npm run build

# Content is in the HTML, not just in the JS bundle:
grep -c "Frequently asked questions" ../frontend-react-dist/index.html

# Per-route titles differ:
grep -h "<title>" ../frontend-react-dist/index.html ../frontend-react-dist/pricing/index.html

# See what a non-JS crawler sees:
curl -s http://localhost:5175/ | grep -A2 "<title>"
```

`npm run preview` serves the built output on `:5175`.

### After deploying

| Tool | Checks |
| --- | --- |
| [Google Rich Results Test](https://search.google.com/test/rich-results) | FAQ and SoftwareApplication structured data parse |
| [Schema Markup Validator](https://validator.schema.org/) | All JSON-LD is valid |
| [Facebook Sharing Debugger](https://developers.facebook.com/tools/debug/) | OG card renders; forces a re-scrape after changes |
| [LinkedIn Post Inspector](https://www.linkedin.com/post-inspector/) | LinkedIn preview |
| [PageSpeed Insights](https://pagespeed.web.dev/) | Core Web Vitals |
| `curl -A "facebookexternalhit/1.1" <url>` | Exactly what a non-JS crawler receives |

---

## Post-launch checklist

Code cannot do these. They need doing once, by hand.

- [ ] Build with the real `VITE_SITE_URL`.
- [ ] Verify `https://yourdomain.com/robots.txt` and `/sitemap.xml` are reachable.
- [ ] Create a [Google Search Console](https://search.google.com/search-console) property, verify the domain, submit the sitemap.
- [ ] Do the same in [Bing Webmaster Tools](https://www.bing.com/webmasters) — Bing's JS rendering is weakest, so prerendering helps most there.
- [ ] Serve over HTTPS with HTTP redirected to it. HTTPS is a ranking signal, and duplicate HTTP/HTTPS pages split it.
- [ ] Pick one canonical host — `www` or bare — and 301 the other. Both resolving is duplicate content.
- [ ] Configure the static host to serve `index.html` for unmatched routes so client-side navigation deep links work.
- [ ] Set long `Cache-Control` on `/assets/*` (hashed filenames) and short on the HTML.
- [ ] Add analytics to find out which queries actually convert.
- [ ] Re-run the Facebook and LinkedIn debuggers to force a re-scrape of the new OG tags.

### Beyond the code

Technical SEO makes a site indexable. It does not make it rank. Ranking
for competitive terms like "ats resume checker" is driven mostly by
content depth and inbound links, neither of which is a build step:

- **Publish substantive guides.** "How to get past an ATS", "resume
  keywords for software engineers". These rank for long-tail queries and
  are what other sites link to. There is no blog route yet — adding one
  is the single highest-leverage SEO work remaining.
- **Earn links** from career-services pages, university job boards,
  developer communities.
- **Watch Search Console** for queries you already appear for on page 2
  and improve those pages first. That is far cheaper than chasing new terms.

---

## What this does not do

Stated plainly, so nothing here is assumed to be handled.

| Gap | Impact | Fix |
| --- | --- | --- |
| No blog or article content | Biggest single ranking limitation. Tool pages rarely outrank editorial content for informational searches. | Add a content route and write guides. |
| `/pricing` prerenders thin (~700 chars) | Weak ranking for pricing queries. Tiers load from the API after mount. | Seed static tier copy, accepting the drift risk against `app/config.py`. |
| Firebase is on the critical path | 173 KB fetched on first load, needed only after sign-in. | Make `firebase.js` use a dynamic import — changes `getFirebaseAuth()` to async and ripples through `authContext`. A behavioural change, not a config one. |
| No hydration | Brief flash as React replaces prerendered markup. | `hydrateRoot` plus resolving auth-dependent markup mismatches. |
| No `hreflang` / i18n | English only. | Only relevant if you localise. |
| No `BreadcrumbList` markup | Minor missed rich-result opportunity. | Add once there is a deeper page hierarchy. |
| OG image is static | Every page shares one social card. | Per-route cards need an image generation service. |

---

## Related documents

- [DEPLOYMENT.md](DEPLOYMENT.md) — build and deploy steps
- [CONFIGURATION.md](CONFIGURATION.md) — `VITE_SITE_URL` and other variables
- [DEVELOPMENT.md](DEVELOPMENT.md) — local setup
