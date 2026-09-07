import { useState } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { useAuth } from "../lib/authContext";

/**
 * Adapted from the supplied NavbarHero component. Dropped: the
 * About/Resources/Blog/Pricing nav with placeholder "Submenu 1/2"
 * dropdowns (there's no content behind them in this product, and a menu
 * that opens onto fake items is exactly the kind of "buttons that do
 * nothing" the project's own rules rule out), the email-capture
 * newsletter form (this is a direct-use tool, not a waitlist product),
 * and the theme toggle (there's no dark-mode token set built yet --
 * same reasoning: a toggle that doesn't actually change anything is
 * worse than no toggle).
 *
 * Kept: the responsive mobile-menu pattern, the CTA button styling
 * approach. Shows "Log in" or the signed-in user + Sign out, depending
 * on real Firebase auth state (lib/authContext.jsx) -- not a static
 * "Log in" link regardless of session, now that sign-in actually works.
 */
export function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, signOutUser } = useAuth();
  const navigate = useNavigate();

  const links = [
    { to: "/with-jd", label: "Score vs. a job" },
    { to: "/without-jd", label: "General readiness" },
    { to: "/pricing", label: "Pricing" },
    ...(user ? [
      { to: "/dashboard", label: "Dashboard" },
      { to: "/history", label: "History" },
      { to: "/settings", label: "Settings" },
    ] : []),
  ];

  async function handleSignOut() {
    await signOutUser();
    setMobileOpen(false);
    navigate("/");
  }

  return (
    <nav className="navbar">
      <div className="navbar-inner">
        <Link to="/" className="navbar-brand" onClick={() => setMobileOpen(false)}>
          Resume Optimizer
        </Link>

        <div className="navbar-links-desktop">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className={({ isActive }) => `navbar-link${isActive ? " active" : ""}`}>
              {l.label}
            </NavLink>
          ))}
        </div>

        <div className="navbar-actions-desktop">
          {user ? (
            <>
              <span className="navbar-user">{user.displayName || user.email}</span>
              <button className="btn-link" onClick={handleSignOut}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="btn-link">
                Log in
              </Link>
              <Link to="/with-jd" className="btn-primary navbar-cta">
                Get Started
              </Link>
            </>
          )}
        </div>

        <button
          className="navbar-mobile-toggle"
          onClick={() => setMobileOpen((o) => !o)}
          aria-label={mobileOpen ? "Close menu" : "Open menu"}
          aria-expanded={mobileOpen}
        >
          {mobileOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
      </div>

      {mobileOpen && (
        <div className="navbar-mobile-menu">
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} className="navbar-mobile-link" onClick={() => setMobileOpen(false)}>
              {l.label}
            </NavLink>
          ))}
          {user ? (
            <button className="navbar-mobile-link navbar-mobile-signout" onClick={handleSignOut}>
              Sign out ({user.displayName || user.email})
            </button>
          ) : (
            <>
              <Link to="/login" className="navbar-mobile-link" onClick={() => setMobileOpen(false)}>
                Log in
              </Link>
              <Link to="/with-jd" className="btn-primary navbar-cta" onClick={() => setMobileOpen(false)}>
                Get Started
              </Link>
            </>
          )}
        </div>
      )}
    </nav>
  );
}
