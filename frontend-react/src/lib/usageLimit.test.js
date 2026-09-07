import { describe, expect, it } from "vitest";
import { formatResetAt, formatResetCountdown, resetSentence, scanLimitDetail } from "./usageLimit";

const LIMIT_ERROR = {
  status: 429,
  detail: { error: "scan_limit_reached", message: "You've used all 10 scans.", used: 10, limit: 10, resets_at: "2026-10-01T00:00:00Z" },
};

describe("scanLimitDetail", () => {
  it("recognizes the spent-allowance 429 and hands back its payload", () => {
    expect(scanLimitDetail(LIMIT_ERROR)).toEqual(LIMIT_ERROR.detail);
  });

  it("ignores other failures so they still render as ordinary errors", () => {
    expect(scanLimitDetail(null)).toBeNull();
    expect(scanLimitDetail({ status: 500, detail: "boom" })).toBeNull();
    expect(scanLimitDetail({ status: 429, detail: "some other rate limit" })).toBeNull();
    expect(scanLimitDetail({ status: 429, detail: { error: "ip_rate_limited" } })).toBeNull();
  });
});

describe("formatResetAt", () => {
  it("renders the UTC instant as a readable local date and time", () => {
    const formatted = formatResetAt("2026-10-01T00:00:00Z");
    expect(formatted).toMatch(/2026/);
    expect(formatted).toMatch(/\d/);
  });

  it("returns null rather than 'Invalid Date' for missing or junk input", () => {
    expect(formatResetAt(null)).toBeNull();
    expect(formatResetAt("not-a-date")).toBeNull();
  });
});

describe("formatResetCountdown", () => {
  const now = new Date("2026-09-07T10:00:00Z");

  it("counts whole days out", () => {
    expect(formatResetCountdown("2026-09-20T00:00:00Z", now)).toMatch(/^in \d+ days$/);
  });

  it("says 'tomorrow' instead of 'in 1 days'", () => {
    expect(formatResetCountdown("2026-09-08T12:00:00Z", now)).toBe("tomorrow");
  });

  it("falls back to hours inside the same day", () => {
    expect(formatResetCountdown("2026-09-07T15:00:00Z", now)).toBe("in 5 hours");
    expect(formatResetCountdown("2026-09-07T10:20:00Z", now)).toBe("in under an hour");
  });

  it("degrades gracefully when the reset instant has already passed", () => {
    expect(formatResetCountdown("2026-09-01T00:00:00Z", now)).toBe("shortly");
  });
});

describe("resetSentence", () => {
  it("combines the countdown and the exact local time", () => {
    expect(resetSentence("2026-10-01T00:00:00Z")).toMatch(/^Resets in \d+ days — .+ \(your local time\)\.$/);
  });

  it("is null when there's no reset time to talk about", () => {
    expect(resetSentence(undefined)).toBeNull();
  });
});
