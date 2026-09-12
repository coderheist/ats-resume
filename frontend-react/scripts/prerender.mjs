/**
 * Build-time prerendering.
 *
 * Why this exists: a Vite SPA serves every route as an empty
 * `<div id="root"></div>`. Googlebot does render JavaScript and can
 * eventually index that, but it costs crawl budget and delays indexing by
 * days-to-weeks; Bing's JS rendering is patchier; and the social crawlers
 * (Facebook, LinkedIn, Slack, X) execute no JavaScript at all, so a
 * shared link produces a blank preview card. Static meta tags alone fix
 * the preview but not the "there is no content on this page" problem.
 *
 * This script renders each public route to real HTML at build time and
 * writes it as its own file, so the first byte a crawler receives already
 * contains the headings, copy, and structured data.
 *
 * What it does NOT do is set up hydration. The client still uses
 * createRoot (see main.jsx), which discards the prerendered markup and
 * re-renders on mount, rather than hydrateRoot which would attempt to
 * adopt it. That is a deliberate trade: the Navbar and several pages
 * render differently for a signed-in user, and a hydration mismatch
 * against auth-dependent markup produces console errors and, worse,
 * silently dropped event handlers. Prerendering here buys crawlability
 * and a fast first paint; it is not a full SSR setup and is not claimed
 * to be one.
 *
 * Run automatically by `npm run build`. Requires the two builds that
 * precede it in that script -- the client build (for dist/index.html and
 * its hashed asset URLs) and the SSR build (for the render function).
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const distDir = resolve(root, "../frontend-react-dist");
const ssrEntry = resolve(root, ".prerender-ssr/entry-server.js");

// Deliberately NOT defining `window` here.
//
// The obvious-looking fix for "framer-motion calls matchMedia during
// render" is to stub window + matchMedia. That backfires: framer-motion
// decides whether it is in a browser with `typeof window !== "undefined"`,
// so defining it flips the library into its full browser path, which then
// reaches for SVGElement, HTMLElement and the rest of the DOM and throws
// `SVGElement is not defined`. Verified by doing exactly that first.
//
// Leaving window undefined lets framer-motion take its server branch,
// where useReducedMotion() returns false without touching matchMedia at
// all -- no stubs needed, and no risk of a half-mocked DOM producing
// markup that differs from what the browser actually renders.

function fail(message) {
  console.error(`\n[prerender] ${message}\n`);
  process.exit(1);
}

if (!existsSync(distDir)) {
  fail(`No build output at ${distDir}. Run the client build first (npm run build).`);
}
if (!existsSync(ssrEntry)) {
  fail(`No SSR bundle at ${ssrEntry}. Run the SSR build first (npm run build).`);
}

// entry-server.jsx re-exports src/lib/seo.js, so one SSR bundle carries
// both the renderer and the route metadata they must agree on.
const { render, INDEXABLE_ROUTES, PAGE_SEO, SITE_URL, seoFor, faqPageLd, organizationLd, robotsTxt, llmsTxt } =
  await import(pathToFileURL(ssrEntry).href);

const template = readFileSync(join(distDir, "index.html"), "utf-8");

const escapeAttr = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * Replaces the value of an existing tag rather than appending a second
 * one. Two <meta name="description"> tags is not a neutral mistake --
 * crawlers pick one unpredictably, so a route could be indexed with the
 * generic default despite having a specific description right beside it.
 */
function setMeta(html, matcher, attr, value) {
  const re = new RegExp(`(<(?:meta|link)[^>]*${matcher}[^>]*)\\s${attr}="[^"]*"`, "i");
  if (re.test(html)) {
    return html.replace(re, `$1 ${attr}="${escapeAttr(value)}"`);
  }
  return html;
}

function buildPage(path, appHtml) {
  const meta = seoFor(path);
  let html = template;

  html = html.replace(/<title>[\s\S]*?<\/title>/i, `<title>${escapeAttr(meta.title)}</title>`);
  html = setMeta(html, 'name="description"', "content", meta.description);
  html = setMeta(html, 'name="robots"', "content",
    meta.noindex ? "noindex, nofollow" : "index, follow, max-image-preview:large");
  html = setMeta(html, 'rel="canonical"', "href", meta.canonical);

  html = setMeta(html, 'property="og:title"', "content", meta.title);
  html = setMeta(html, 'property="og:description"', "content", meta.description);
  html = setMeta(html, 'property="og:url"', "content", meta.canonical);
  html = setMeta(html, 'name="twitter:title"', "content", meta.title);
  html = setMeta(html, 'name="twitter:description"', "content", meta.description);

  // Every absolute URL in the template still carries the placeholder
  // origin from index.html. Rewriting them here means VITE_SITE_URL is
  // the single thing that has to be set for a deployment, instead of
  // index.html needing a hand-edit that is easy to forget.
  html = html.replaceAll("https://resume-optimizer.example.com", SITE_URL);

  if (meta.keywords) {
    html = html.replace(
      "</head>",
      `  <meta name="keywords" content="${escapeAttr(meta.keywords)}" />\n</head>`
    );
  }

  // FAQPage markup goes only on the route that actually renders the FAQ.
  // Structured data describing content a page doesn't display is a
  // spam signal to Google, not a shortcut to a rich result.
  const extraLd = [organizationLd()];
  if (path === "/") extraLd.push(faqPageLd());

  html = html.replace(
    "</head>",
    extraLd
      .map((ld) => `  <script type="application/ld+json">\n${JSON.stringify(ld, null, 2)}\n  </script>\n`)
      .join("") + "</head>"
  );

  html = html.replace('<div id="root"></div>', `<div id="root">${appHtml}</div>`);
  return html;
}

function outputPathFor(route) {
  // "/" -> dist/index.html; "/pricing" -> dist/pricing/index.html, which
  // serves at the extensionless URL on every static host without needing
  // per-host rewrite rules.
  return route === "/" ? join(distDir, "index.html") : join(distDir, route, "index.html");
}

let rendered = 0;
const failures = [];

for (const route of INDEXABLE_ROUTES) {
  try {
    const appHtml = render(route);
    const file = outputPathFor(route);
    mkdirSync(dirname(file), { recursive: true });
    writeFileSync(file, buildPage(route, appHtml), "utf-8");
    console.log(`[prerender] ${route.padEnd(14)} -> ${file.replace(distDir, "dist")} (${appHtml.length.toLocaleString()} chars)`);
    rendered++;
  } catch (err) {
    failures.push({ route, err });
    console.error(`[prerender] ${route.padEnd(14)} FAILED: ${err.message}`);
  }
}

// ---------------------------------------------------------------------
// sitemap.xml and robots.txt
// ---------------------------------------------------------------------
// Generated from INDEXABLE_ROUTES rather than hand-maintained, so a route
// marked noindex in seo.js can never end up advertised in the sitemap --
// telling Google to crawl a page that then refuses indexing is a
// contradiction it reports as an error in Search Console.

const today = new Date().toISOString().slice(0, 10);
const priority = { "/": "1.0", "/with-jd": "0.9", "/without-jd": "0.9", "/pricing": "0.7" };

const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${INDEXABLE_ROUTES.map(
  (r) => `  <url>
    <loc>${SITE_URL}${r === "/" ? "/" : r}</loc>
    <lastmod>${today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>${priority[r] || "0.5"}</priority>
  </url>`
).join("\n")}
</urlset>
`;
writeFileSync(join(distDir, "sitemap.xml"), sitemap, "utf-8");

// robots.txt comes from seo.js rather than being assembled here. This
// file overwrites whatever public/robots.txt contained, so a rule added
// only to the static copy would silently vanish from every real
// deployment -- which is exactly what happened to the AI-crawler block.
writeFileSync(join(distDir, "robots.txt"), robotsTxt(SITE_URL), "utf-8");

// llms.txt (llmstxt.org): a plain-text brief for language models. An
// assistant asked "what's a good ATS resume checker?" works from whatever
// prose it can extract, and a React app's markup is a poor summary of
// what the product does -- this states it directly, including the limits,
// so the tool is less likely to be described wrongly.
writeFileSync(join(distDir, "llms.txt"), llmsTxt(SITE_URL), "utf-8");

console.log(`\n[prerender] ${rendered}/${INDEXABLE_ROUTES.length} routes prerendered`);
console.log(`[prerender] sitemap.xml + robots.txt + llms.txt written for ${SITE_URL}`);

if (SITE_URL.includes("example.com")) {
  console.warn(
    "\n[prerender] WARNING: VITE_SITE_URL is unset, so canonical URLs, og:url\n" +
    "            and sitemap.xml all point at the placeholder domain\n" +
    "            resume-optimizer.example.com. Set VITE_SITE_URL to your real\n" +
    "            origin before deploying -- wrong canonicals are worse than none."
  );
}

if (failures.length) {
  fail(`${failures.length} route(s) failed to prerender. Build output is incomplete.`);
}
