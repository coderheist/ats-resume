import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiGet } from "../lib/api";
import { useAuth } from "../lib/authContext";
import { resetSentence } from "../lib/usageLimit";

/**
 * Deliberately minimal: account info and subscription status pulled
 * from real endpoints (/auth/me), plus sign-out -- no toggles or
 * preferences that don't actually do anything. Password/email changes
 * go through Firebase's own account-management flows rather than a
 * custom form here duplicating what Firebase already handles securely.
 */
export function SettingsPage() {
  const { user, signOutUser } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    apiGet("/auth/me").then(setProfile).catch(() => {});
  }, []);

  async function handleSignOut() {
    await signOutUser();
    navigate("/");
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Settings</h1>
      </header>

      <div className="dashboard-card">
        <p className="skill-col-title">Account</p>
        <div className="settings-row">
          <span className="settings-label">Name</span>
          <span>{user?.displayName || "—"}</span>
        </div>
        <div className="settings-row">
          <span className="settings-label">Email</span>
          <span>{user?.email}</span>
        </div>
      </div>

      <div className="dashboard-card" style={{ marginTop: 18 }}>
        <p className="skill-col-title">Subscription</p>
        {profile ? (
          <>
            <div className="settings-row">
              <span className="settings-label">Current plan</span>
              <span>{profile.tier_name}</span>
            </div>
            {profile.jd_match_scans_per_month && (
              <div className="settings-row">
                <span className="settings-label">Scans used this month</span>
                <span>{profile.jd_match_scans_used_this_month} / {profile.jd_match_scans_per_month}</span>
              </div>
            )}
            {resetSentence(profile.jd_match_scans_reset_at) && (
              <div className="settings-row">
                <span className="settings-label">Allowance resets</span>
                <span>{resetSentence(profile.jd_match_scans_reset_at)}</span>
              </div>
            )}
            <Link to="/pricing" className="btn-outline" style={{ marginTop: 12, display: "inline-block", width: "auto" }}>
              Manage plan
            </Link>
          </>
        ) : (
          <p className="status-text">Loading…</p>
        )}
      </div>

      <div className="dashboard-card" style={{ marginTop: 18 }}>
        <p className="skill-col-title">Session</p>
        <button className="btn-outline" style={{ width: "auto" }} onClick={handleSignOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}
