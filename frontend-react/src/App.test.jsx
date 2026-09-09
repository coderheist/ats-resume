import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./lib/authContext";

// Firebase is stubbed rather than left to the real SDK so the auth state
// every route sees is decided by the test, not by whatever VITE_FIREBASE_*
// happens to be in the developer's .env. /with-jd and /without-jd are gated
// now, so "is there a signed-in user" is the difference between rendering
// the tool and redirecting to /login -- it can't be ambient.
vi.mock("firebase/auth", () => ({
  GoogleAuthProvider: vi.fn(),
  createUserWithEmailAndPassword: vi.fn(),
  onAuthStateChanged: vi.fn((auth, callback) => {
    callback(auth?.currentUser ?? null);
    return () => {};
  }),
  signInWithEmailAndPassword: vi.fn(),
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock("./lib/firebase", () => ({
  isFirebaseConfigured: vi.fn(() => true),
  getFirebaseAuth: vi.fn(() => ({ currentUser: null })),
}));

async function signedInAs(user) {
  const { getFirebaseAuth, isFirebaseConfigured } = await import("./lib/firebase");
  isFirebaseConfigured.mockReturnValue(true);
  getFirebaseAuth.mockReturnValue({ currentUser: user });
}

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}

beforeEach(async () => {
  await signedInAs(null);
});

describe("App routing", () => {
  it("renders the hero at /", () => {
    renderAt("/");
    expect(screen.getByText(/Know exactly where your resume stands/i)).toBeInTheDocument();
  });

  it("renders the with-JD report page at /with-jd for a signed-in user", async () => {
    await signedInAs({ email: "jordan@example.com" });
    renderAt("/with-jd");
    expect(screen.getByText("Score against a job description")).toBeInTheDocument();
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
  });

  it("renders the standalone report page at /without-jd for a signed-in user", async () => {
    await signedInAs({ email: "jordan@example.com" });
    renderAt("/without-jd");
    expect(screen.getByText("General ATS readiness")).toBeInTheDocument();
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
  });

  // The bug this guards: both scoring tools used to render for anyone,
  // so a signed-out visitor could run scans that no account could be
  // billed or credited for.
  it("sends a signed-out visitor from /with-jd to the login page", async () => {
    renderAt("/with-jd");
    expect(await screen.findByText("Sign in to your account")).toBeInTheDocument();
    expect(screen.queryByText(/drop your resume here/i)).not.toBeInTheDocument();
  });

  it("sends a signed-out visitor from /without-jd to the login page", async () => {
    renderAt("/without-jd");
    expect(await screen.findByText("Sign in to your account")).toBeInTheDocument();
    expect(screen.queryByText(/drop your resume here/i)).not.toBeInTheDocument();
  });

  it("hero links point at the two report routes", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /analyze against a job description/i })).toHaveAttribute("href", "/with-jd");
    expect(screen.getByRole("link", { name: /check general ats readiness/i })).toHaveAttribute("href", "/without-jd");
  });

  // AuthPage is code-split (React.lazy in App.jsx -- /login and /signup are
  // noindex routes nobody lands on first, so their JS is kept out of the
  // bundle that blocks the landing page's first paint). These two therefore
  // have to await the chunk resolving instead of asserting synchronously.
  it("renders the login page at /login", async () => {
    renderAt("/login");
    expect(await screen.findByText("Sign in to your account")).toBeInTheDocument();
  });

  it("renders the signup page at /signup", async () => {
    renderAt("/signup");
    expect(await screen.findByText("Create an account")).toBeInTheDocument();
  });

  it("shows the navbar on the hero and report pages, but not on auth pages", () => {
    renderAt("/");
    expect(screen.getByText("Resume Optimizer")).toBeInTheDocument();
  });

  it("has a skip-to-content link and a main landmark for keyboard/screen-reader users", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /skip to main content/i })).toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  });
});
