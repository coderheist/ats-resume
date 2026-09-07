import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../lib/api";
import { useAuth } from "../lib/authContext";

export function HistoryPage() {
  const { configured, user } = useAuth();
  const [status, setStatus] = useState("loading"); // loading | success | error
  const [entries, setEntries] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!configured || !user) {
      setStatus("error");
      setError(configured ? null : "Sign-in isn't configured yet in this deployment (no Firebase project set up).");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet("/history");
        if (!cancelled) {
          setEntries(data.history);
          setStatus("success");
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message);
          setStatus("error");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [configured, user]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="btn-link" style={{ marginBottom: 16, display: "inline-block" }}>
          ← Back home
        </Link>
        <h1>Your analysis history</h1>
      </header>

      {status === "loading" && <p className="status-text">Loading…</p>}

      {status === "error" && (
        <div className="error-box">{error || "Couldn't load your history."}</div>
      )}

      {status === "success" && entries.length === 0 && (
        <p className="tag-empty">
          No saved analyses yet. Run a scan while signed in from <Link to="/with-jd">Score vs. a job</Link> or{" "}
          <Link to="/without-jd">General readiness</Link> and it'll show up here.
        </p>
      )}

      {status === "success" && entries.length > 0 && (
        <div className="history-list">
          {entries.map((entry) => (
            <div key={entry.scan_id} className="history-row">
              <div>
                <strong>{entry.resume_name || "Untitled resume"}</strong>
                <span className="history-meta">
                  {entry.mode === "jd_match" ? "Scored against a job description" : "General readiness"} ·{" "}
                  {new Date(entry.created_at).toLocaleDateString()}
                </span>
              </div>
              <span className="history-score">{entry.final_score.toFixed(1)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
