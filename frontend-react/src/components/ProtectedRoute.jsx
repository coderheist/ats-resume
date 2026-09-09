import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../lib/authContext";

export function ProtectedRoute({ children }) {
  const { user, loading, configured } = useAuth();
  const location = useLocation();

  if (!configured) {
    // No Firebase project configured in this deployment at all -- don't
    // redirect into a login page that can't do anything either; the
    // page itself is responsible for showing why nothing is available.
    return children;
  }
  if (typeof window === "undefined") {
    // Build-time prerender (scripts/prerender.mjs) renders this in Node,
    // where onAuthStateChanged never fires and `loading` would stay true
    // forever -- every prerendered page would be the word "Loading…".
    // The indexable routes (/with-jd, /without-jd) carry real SEO copy
    // below the tool, so render the page as-is into the static HTML and
    // let the client-side gate below take over the moment React mounts.
    return children;
  }
  if (loading) {
    return <div className="app-shell">Loading…</div>;
  }
  if (!user) {
    // Remember where they were headed so AuthPage can send them there
    // once they're signed in, instead of dumping everyone on /history
    // and making them re-navigate to the thing they actually clicked.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  return children;
}
