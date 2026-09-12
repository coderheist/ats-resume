import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_SEO,
  FAQ,
  INDEXABLE_ROUTES,
  PAGE_SEO,
  SITE_URL,
  applySeo,
  faqPageLd,
  seoFor,
  softwareApplicationLd,
  titleFor,
} from "./seo";

describe("route metadata", () => {
  it("gives every route a title and a description", () => {
    for (const [path, page] of Object.entries(PAGE_SEO)) {
      expect(page.title, `${path} has no title`).toBeTruthy();
      expect(page.description, `${path} has no description`).toBeTruthy();
    }
  });

  it("keeps titles and descriptions inside the widths search results truncate at", () => {
    // Google cuts titles around 60 chars and descriptions around 155.
    // Past those, the distinguishing words are simply not shown.
    for (const [path, page] of Object.entries(PAGE_SEO)) {
      expect(page.title.length, `${path} title is too long`).toBeLessThanOrEqual(60);
      expect(page.description.length, `${path} description is too long`).toBeLessThanOrEqual(160);
    }
  });

  it("gives every indexable route a distinct title and description", () => {
    // Duplicate metadata across routes is a real ranking problem: Google
    // collapses near-identical pages and picks one, so the others simply
    // stop appearing.
    const titles = INDEXABLE_ROUTES.map((p) => seoFor(p).title);
    const descriptions = INDEXABLE_ROUTES.map((p) => seoFor(p).description);
    expect(new Set(titles).size).toBe(titles.length);
    expect(new Set(descriptions).size).toBe(descriptions.length);
  });

  it("excludes authenticated and auth routes from the indexable set", () => {
    for (const path of ["/login", "/signup", "/dashboard", "/history", "/settings"]) {
      expect(INDEXABLE_ROUTES, `${path} must not be indexable`).not.toContain(path);
      expect(seoFor(path).noindex).toBe(true);
    }
  });

  it("marks public tool pages as indexable", () => {
    for (const path of ["/", "/with-jd", "/without-jd", "/pricing"]) {
      expect(INDEXABLE_ROUTES).toContain(path);
      expect(seoFor(path).noindex).toBe(false);
    }
  });

  it("builds absolute canonical URLs with no double slash", () => {
    expect(seoFor("/").canonical).toBe(`${SITE_URL}/`);
    expect(seoFor("/pricing").canonical).toBe(`${SITE_URL}/pricing`);
    for (const path of INDEXABLE_ROUTES) {
      expect(seoFor(path).canonical).not.toMatch(/[^:]\/\//);
    }
  });

  it("appends the site name once, leading with the page-specific part", () => {
    // Search results and browser tabs both truncate from the right, so
    // the distinguishing words have to come first.
    expect(titleFor("/pricing")).toBe("Pricing — Resume Scans & AI Rewrites from ₹149 | Resume Optimizer");
    expect(titleFor("/pricing").match(/Resume Optimizer/g)).toHaveLength(1);
  });

  it("falls back to the default title for an unknown route", () => {
    expect(titleFor("/no-such-route")).toBe(DEFAULT_SEO.title);
    expect(seoFor("/no-such-route").description).toBe(DEFAULT_SEO.description);
  });
});

describe("structured data", () => {
  it("emits valid schema.org types", () => {
    expect(softwareApplicationLd()["@context"]).toBe("https://schema.org");
    expect(softwareApplicationLd()["@type"]).toBe("SoftwareApplication");
    expect(faqPageLd()["@type"]).toBe("FAQPage");
  });

  it("covers every FAQ entry the page actually renders", () => {
    // Structured data describing content the page doesn't display is a
    // spam signal to Google, so these must stay in step by construction.
    const ld = faqPageLd();
    expect(ld.mainEntity).toHaveLength(FAQ.length);
    for (const [i, entry] of ld.mainEntity.entries()) {
      expect(entry["@type"]).toBe("Question");
      expect(entry.name).toBe(FAQ[i].q);
      expect(entry.acceptedAnswer.text).toBe(FAQ[i].a);
    }
  });

  it("serialises to JSON without throwing", () => {
    expect(() => JSON.stringify(softwareApplicationLd())).not.toThrow();
    expect(() => JSON.stringify(faqPageLd())).not.toThrow();
  });
});

describe("applySeo", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    document.title = "";
  });

  const content = (selector) => document.head.querySelector(selector)?.getAttribute("content");

  it("sets title, description and canonical for a route", () => {
    applySeo("/with-jd");
    expect(document.title).toBe(titleFor("/with-jd"));
    expect(content('meta[name="description"]')).toBe(PAGE_SEO["/with-jd"].description);
    expect(document.head.querySelector('link[rel="canonical"]').getAttribute("href")).toBe(
      `${SITE_URL}/with-jd`
    );
  });

  it("mirrors the title and description into Open Graph and Twitter tags", () => {
    applySeo("/without-jd");
    const expected = titleFor("/without-jd");
    expect(content('meta[property="og:title"]')).toBe(expected);
    expect(content('meta[name="twitter:title"]')).toBe(expected);
    expect(content('meta[property="og:url"]')).toBe(`${SITE_URL}/without-jd`);
  });

  it("marks noindex routes noindex, and indexable ones index", () => {
    applySeo("/login");
    expect(content('meta[name="robots"]')).toContain("noindex");

    applySeo("/");
    expect(content('meta[name="robots"]')).toContain("index");
    expect(content('meta[name="robots"]')).not.toContain("noindex");
  });

  it("updates existing tags in place rather than appending duplicates", () => {
    // Two <meta name="description"> tags is not harmless -- crawlers pick
    // one unpredictably, so a route can be indexed with the wrong copy
    // while the right one sits beside it in the DOM.
    applySeo("/");
    applySeo("/pricing");
    applySeo("/with-jd");
    expect(document.head.querySelectorAll('meta[name="description"]')).toHaveLength(1);
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1);
    expect(document.head.querySelectorAll('meta[property="og:title"]')).toHaveLength(1);
    expect(content('meta[name="description"]')).toBe(PAGE_SEO["/with-jd"].description);
  });
});
