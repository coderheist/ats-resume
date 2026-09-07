import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { applySeo } from "./seo";

/**
 * Keeps the document's SEO tags in step with the current route.
 *
 * Mounted once at the app root rather than called per page: every route's
 * metadata already lives in seo.js's PAGE_SEO map, so a single
 * location-driven effect covers all of them and a new route can never
 * ship having forgotten to call this.
 *
 * Kept separate from seo.js because that module is also imported by
 * scripts/prerender.mjs under plain Node, where React and react-router
 * hooks are neither available nor meaningful.
 */
export function useSeo() {
  const { pathname } = useLocation();

  useEffect(() => {
    applySeo(pathname);
  }, [pathname]);
}
