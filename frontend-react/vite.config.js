import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Build output goes to ../frontend-react-dist -- served as its own
// static origin (e.g. `npm run preview`, or any static file server),
// same pattern as the existing frontend/ console. Not mounted into
// FastAPI: that keeps the backend API-only, consistent with how
// frontend/ already works (see app/main.py's CORS comment) rather than
// introducing a second, different serving convention for this one.
// The config is a function so the SSR build (npm run build:ssr, used by
// scripts/prerender.mjs) can opt out of manualChunks. In an SSR build
// every dependency is external by design, and rollup rejects a
// manualChunks entry naming an external module outright:
//   "react" cannot be included in manualChunks because it is resolved as
//   an external module
// Chunk splitting is a browser-delivery concern and means nothing for a
// bundle that Node imports once at build time, so it simply doesn't apply
// there.
export default defineConfig(({ isSsrBuild }) => ({
  plugins: [react()],
  build: {
    outDir: "../frontend-react-dist",
    emptyOutDir: true,
    rollupOptions: {
      output: isSsrBuild
        ? {}
        : {
            // Split the big third-party deps into their own chunks. These
            // are still fetched on first load (they're statically
            // imported), but browsers fetch them in parallel and each
            // caches independently, so a deploy that only changes app
            // code no longer invalidates ~450 kB of unchanged vendor JS
            // for returning visitors.
            //
            // Firebase is the largest single dependency and is only
            // needed once someone signs in. Moving it off the critical
            // path entirely needs firebase.js to switch to a dynamic
            // import, which changes getFirebaseAuth() from sync to async
            // and ripples through authContext -- worth doing, but a
            // behavioural change rather than a build-config one. See
            // docs/SEO.md.
            manualChunks: {
              "vendor-react": ["react", "react-dom", "react-router-dom"],
              "vendor-firebase": ["firebase/app", "firebase/auth"],
              "vendor-motion": ["framer-motion"],
            },
          },
    },
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
    // Every test file gets its own jsdom instance, and spinning up 25 of
    // them at once starved the ones that were already running: whole
    // files passed in isolation but a handful of `waitFor` calls timed
    // out on each full-suite run, and WHICH ones varied per run. That is
    // the signature of contention, not of a real failure -- but a suite
    // that reports different results each time is worthless either way,
    // because nobody can tell a genuine regression from the noise.
    //
    // Two changes, both about headroom rather than hiding anything:
    // cap the worker pool so the machine is not oversubscribed, and give
    // `waitFor` a timeout that a slow-but-correct render can still meet.
    // The default 5s is generous for a fast machine and marginal for a
    // loaded one.
    testTimeout: 15000,
    hookTimeout: 15000,
    poolOptions: {
      threads: { maxThreads: 2, minThreads: 1 },
      forks: { maxForks: 2, minForks: 1 },
    },
  },
}));
