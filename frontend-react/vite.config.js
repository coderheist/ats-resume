import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output goes to ../frontend-react-dist -- served as its own
// static origin (e.g. `npm run preview`, or any static file server),
// same pattern as the existing frontend/ console. Not mounted into
// FastAPI: that keeps the backend API-only, consistent with how
// frontend/ already works (see app/main.py's CORS comment) rather than
// introducing a second, different serving convention for this one.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../frontend-react-dist",
    emptyOutDir: true,
  },
  preview: {
    port: 5175,
  },
  server: {
    port: 5174,
    proxy: {
      // Dev-time convenience: `npm run dev` proxies API calls straight to
      // the FastAPI backend, so VITE_API_BASE_URL can be left unset in
      // local dev without hitting CORS at all. Production build calls
      // the API directly (no proxy at build time) -- see lib/api.js.
      "/score": "http://localhost:8000",
      "/resume": "http://localhost:8000",
      "/bias-audit": "http://localhost:8000",
      "/voice": "http://localhost:8000",
      "/billing": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/history": "http://localhost:8000",
      "/payments": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.js"],
  },
});
