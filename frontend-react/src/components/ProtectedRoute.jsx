import { Navigate } from "react-router-dom";
import { useAuth } from "../lib/authContext";

export function ProtectedRoute({ children }) {
  const { user, loading, configured } = useAuth();

  if (!configured) {
    // No Firebase project configured in this deployment at all -- don't
    // redirect into a login page that can't do anything either; the
    // page itself is responsible for showing why nothing is available.
    return children;
  }
  if (loading) {
    return <div className="app-shell">Loading…</div>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
