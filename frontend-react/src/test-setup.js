import "@testing-library/jest-dom/vitest";

// jsdom doesn't implement matchMedia; framer-motion's useReducedMotion()
// calls it internally, so every test would throw without this.
if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

