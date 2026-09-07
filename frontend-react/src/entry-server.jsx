import { StrictMode } from "react";
import { renderToString } from "react-dom/server";
import { StaticRouter } from "react-router-dom/server";
import { App } from "./App";
import { AuthProvider } from "./lib/authContext";

/**
 * Build-time-only entry point, consumed by scripts/prerender.mjs.
 *
 * Mirrors main.jsx with two necessary differences: StaticRouter instead
 * of BrowserRouter (there is no history API here), and renderToString
 * instead of createRoot.
 *
 * Note what is deliberately NOT imported: the CSS. Vite's SSR build
 * would try to resolve those imports in a Node context where they mean
 * nothing, and the client bundle already emits the real stylesheet links
 * into dist/index.html -- which is the markup the prerendered pages are
 * built on top of.
 *
 * AuthProvider is included because Navbar calls useAuth() and would throw
 * without it. Its effects never run during renderToString, so every
 * prerendered page is the signed-out view. That is the correct thing to
 * bake into static HTML anyway: it is what a crawler and a first-time
 * visitor should see, and the client render corrects it for a signed-in
 * user the moment React mounts.
 */
/**
 * Re-exported so the SSR build has a single entry point that carries both
 * the renderer and the route metadata. `vite build --ssr` takes one entry,
 * and bundling seo.js through this module keeps the prerender script to
 * one import instead of needing a second SSR build for the metadata.
 */
export * from "./lib/seo";

export function render(path) {
  return renderToString(
    <StrictMode>
      <StaticRouter location={path}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </StaticRouter>
    </StrictMode>
  );
}
