import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiGet, apiPost } from "./api";

function respond({ body = "{}", contentType = "application/json", status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "OK",
    headers: { get: (name) => (name.toLowerCase() === "content-type" ? contentType : null) },
    json: async () => JSON.parse(body),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("non-JSON responses", () => {
  /**
   * Reproduces the deployed failure: with VITE_API_BASE_URL unset the
   * request goes to the frontend's own origin, and /history is rewritten
   * to index.html by vercel.json -- so it is a 200 carrying HTML, not a
   * 404. Left to res.json(), that surfaces as the browser's opaque
   * "Unexpected token '<', "<!doctype "... is not valid JSON".
   */
  it("explains an HTML response instead of failing to parse it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond({
      body: "<!doctype html><html></html>",
      contentType: "text/html; charset=utf-8",
    })));

    const err = await apiGet("/history").catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).not.toMatch(/Unexpected token/);
    expect(err.message).toContain("/history");
    expect(err.message).toContain("text/html");
    expect(err.message).toContain("VITE_API_BASE_URL");
  });

  it("applies to POSTs as well, not just GETs", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond({
      body: "<!doctype html>", contentType: "text/html",
    })));

    const err = await apiPost("/score/full-report", {}).catch((e) => e);

    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("/score/full-report");
  });

  it("still parses a normal JSON response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond({ body: '{"history":[]}' })));
    await expect(apiGet("/history")).resolves.toEqual({ history: [] });
  });

  it("leaves a real API error message intact", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => respond({
      body: '{"detail":"Sign in required -- no bearer token provided."}',
      status: 401,
    })));

    const err = await apiGet("/history").catch((e) => e);

    expect(err.status).toBe(401);
    expect(err.message).toBe("Sign in required -- no bearer token provided.");
  });
});
