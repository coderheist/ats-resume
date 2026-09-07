import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { FileSearch, Gauge, History as HistoryIcon } from "lucide-react";
import { apiGet } from "../lib/api";
import { useAuth } from "../lib/authContext";

export function DashboardPage() {
  const { user } = useAuth();
  const [profile, setProfile] = useState(null);
  const [recentHistory, setRecentHistory] = useState(null);

  useEffect(() => {
    apiGet("/auth/me").then(setProfile).catch(() => {});
    apiGet("/history").then((data) => setRecentHistory(data.history.slice(0, 5))).catch(() => {});
  }, []);

  const usedPct = profile?.jd_match_scans_per_month
    ? Math.min(100, (profile.jd_match_scans_used_this_month / profile.jd_match_scans_per_month) * 100)
    : 0;

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Welcome back{user?.displayName ? `, ${user.displayName.split(" ")[0]}` : ""}</h1>
        <p>Here's where things stand.</p>
      </header>

      <div className="dashboard-grid">
        <div className="dashboard-card">
          <p className="skill-col-title">Your plan</p>
          {profile ? (
            <>
              <p className="dashboard-plan-name">{profile.tier_name}</p>
              {profile.jd_match_scans_per_month ? (
                <>
                  <div className="dashboard-usage-track">
                    <div className="dashboard-usage-fill" style={{ width: `${usedPct}%` }} />
                  </div>
                  <p className="dashboard-usage-label">
                    {profile.jd_match_scans_used_this_month} of {profile.jd_match_scans_per_month} scans used this month
                  </p>
                </>
              ) : (
                <p className="dashboard-usage-label">Unlimited scans</p>
              )}
              {profile.tier === "free" && (
                <Link to="/pricing" className="btn-primary" style={{ marginTop: 10, display: "inline-block" }}>
                  Upgrade
                </Link>
              )}
            </>
          ) : (
            <p className="status-text">Loading…</p>
          )}
        </div>

        <div className="dashboard-card">
          <p className="skill-col-title">Quick actions</p>
          <div className="dashboard-actions">
            <Link to="/with-jd" className="dashboard-action-link">
              <FileSearch size={16} /> Score vs. a job
            </Link>
            <Link to="/without-jd" className="dashboard-action-link">
              <Gauge size={16} /> General readiness
            </Link>
            <Link to="/history" className="dashboard-action-link">
              <HistoryIcon size={16} /> View full history
            </Link>
          </div>
        </div>
      </div>

      <div className="dashboard-card" style={{ marginTop: 18 }}>
        <p className="skill-col-title">Recent activity</p>
        {recentHistory === null && <p className="status-text">Loading…</p>}
        {recentHistory && recentHistory.length === 0 && (
          <p className="tag-empty">
            No scans yet — run one from <Link to="/with-jd">Score vs. a job</Link> or{" "}
            <Link to="/without-jd">General readiness</Link>.
          </p>
        )}
        {recentHistory && recentHistory.length > 0 && (
          <div className="history-list">
            {recentHistory.map((entry) => (
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
    </div>
  );
}
