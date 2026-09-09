import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AlertCircle } from "lucide-react";
import { PasswordField } from "../components/PasswordField";
import { Typewriter } from "../components/Typewriter";
import { useAuth } from "../lib/authContext";

/**
 * Adapted from the supplied auth-ui.tsx. Two real, deliberate departures
 * from the source, not oversights:
 *
 * 1. No Radix/cva/clsx/tailwind-merge -- this app has no Tailwind, and
 *    the actual markup (a labeled input, a styled button, a toggle link)
 *    doesn't need three extra dependencies to be accessible; plain
 *    label/htmlFor and a real <button> already are.
 * 2. Now wired to real Firebase Auth (lib/authContext.jsx) -- but still
 *    honest when it isn't configured: if no Firebase project is set up
 *    (no VITE_FIREBASE_* env vars), `configured` is false and submitting
 *    shows a real, visible "not configured yet" message instead of a
 *    cryptic SDK error or a silent no-op.
 */
/**
 * Where to land after a successful sign-in.
 *
 * ProtectedRoute stashes the path the visitor was actually trying to
 * reach in the redirect's location state, so someone who clicked
 * "Analyze against a job description" on the landing page arrives at
 * /with-jd once signed in rather than at a generic history page with no
 * memory of what they came to do.
 *
 * Only same-origin, single-slash paths are honoured: `from` reaches us
 * through router state that a crafted link could otherwise use to bounce
 * a freshly authenticated user off to another site.
 */
function safeRedirect(from) {
  if (typeof from !== "string") return "/history";
  if (!from.startsWith("/") || from.startsWith("//")) return "/history";
  // Never bounce straight back to the auth pages themselves.
  if (from === "/login" || from === "/signup") return "/history";
  return from;
}

const QUOTES = {
  signin: { text: "Welcome back — pick up right where you left off.", author: "Resume Optimizer" },
  signup: { text: "Every application starts with knowing where you stand.", author: "Resume Optimizer" },
};

export function AuthPage({ mode }) {
  const isSignIn = mode === "signin";
  const [notice, setNotice] = useState(null);
  const [isError, setIsError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { configured, signInWithEmail, signUpWithEmail, signInWithGoogle } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const destination = safeRedirect(location.state?.from);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!configured) {
      setIsError(true);
      setNotice("Sign-in isn't configured yet in this deployment (no Firebase project set up).");
      return;
    }
    const form = new FormData(e.target);
    setSubmitting(true);
    setNotice(null);
    try {
      if (isSignIn) {
        await signInWithEmail(form.get("email"), form.get("password"));
      } else {
        await signUpWithEmail(form.get("email"), form.get("password"), form.get("name"));
      }
      navigate(destination, { replace: true });
    } catch (err) {
      setIsError(true);
      setNotice(err.message.replace(/^Firebase:\s*/, ""));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGoogleClick() {
    if (!configured) {
      setIsError(true);
      setNotice("Google sign-in isn't configured yet in this deployment (no Firebase project set up).");
      return;
    }
    setIsError(false);
    setNotice(null);
    try {
      await signInWithGoogle();
      navigate(destination, { replace: true });
    } catch (err) {
      setIsError(true);
      setNotice(err.message.replace(/^Firebase:\s*/, ""));
    }
  }

  const quote = QUOTES[isSignIn ? "signin" : "signup"];

  return (
    <main className="auth-page">
      <div className="auth-form-panel">
        <div className="auth-form-inner">
          {!configured && <p className="auth-preview-badge">PREVIEW — no Firebase project configured in this deployment</p>}
          <h1>{isSignIn ? "Sign in to your account" : "Create an account"}</h1>
          <p className="auth-subtitle">
            {isSignIn ? "Enter your email below to sign in." : "Enter your details below to get started."}
          </p>

          <form onSubmit={handleSubmit} className="auth-form">
            {!isSignIn && (
              <div className="form-field">
                <label htmlFor="name">Full name</label>
                <input id="name" name="name" type="text" placeholder="Jordan Alvarez" required autoComplete="name" />
              </div>
            )}
            <div className="form-field">
              <label htmlFor="email">Email</label>
              <input id="email" name="email" type="email" placeholder="you@example.com" required autoComplete="email" />
            </div>
            <PasswordField
              name="password"
              label="Password"
              required
              placeholder="Password"
              autoComplete={isSignIn ? "current-password" : "new-password"}
            />
            <button type="submit" className="btn-primary auth-submit" disabled={submitting}>
              {submitting ? "Please wait…" : isSignIn ? "Sign In" : "Sign Up"}
            </button>
          </form>

          {notice && (
            <div className={`auth-notice${isError ? " auth-notice-error" : ""}`} role="status">
              <AlertCircle size={15} />
              <span>{notice}</span>
            </div>
          )}

          <p className="auth-toggle">
            {isSignIn ? "Don't have an account? " : "Already have an account? "}
            {/* Carries the pending destination across the sign-in/sign-up
                toggle, so someone who came from "Analyze against a job
                description" and decides to register first still lands on
                /with-jd rather than losing the errand. */}
            <Link to={isSignIn ? "/signup" : "/login"} state={location.state}>
              {isSignIn ? "Sign up" : "Sign in"}
            </Link>
          </p>

          <div className="auth-divider">
            <span>Or continue with</span>
          </div>
          <button type="button" className="btn-outline auth-google" onClick={handleGoogleClick}>
            Continue with Google
          </button>
        </div>
      </div>

      <div className="auth-side-panel" aria-hidden="true">
        <div className="auth-side-glow" />
        <div className="auth-side-quote">
          <p>
            "<Typewriter key={quote.text} text={quote.text} speed={45} />"
          </p>
          <cite>— {quote.author}</cite>
        </div>
      </div>
    </main>
  );
}
