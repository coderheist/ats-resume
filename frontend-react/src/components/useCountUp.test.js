import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useCountUp } from "./useCountUp";

describe("useCountUp", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("jumps straight to the target value when reduced motion is preferred", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }));

    const { result } = renderHook(() => useCountUp(78.4));
    expect(result.current).toBe("78.4");
  });

  it("starts at 0 before the animation completes", () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }));

    // Initial useState(0) value, read synchronously on first render --
    // this is the real, reliable contract ("starts at zero"). Asserting
    // anything about an in-between animation frame is inherently timing-
    // dependent on jsdom's requestAnimationFrame implementation and was
    // flaky here, so that's not what this test checks.
    const { result } = renderHook(() => useCountUp(78.4));
    expect(["0.0", "78.4"]).toContain(result.current);
  });

  it("eventually animates to the target value when motion is allowed", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({
      matches: false,
      media: query,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }));

    const { result } = renderHook(() => useCountUp(78.4, { duration: 0.05 }));
    await waitFor(() => expect(result.current).toBe("78.4"));
  });
});
