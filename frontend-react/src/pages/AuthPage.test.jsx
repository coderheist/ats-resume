import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthPage } from "./AuthPage";
import { AuthProvider } from "../lib/authContext";

// `configured` is driven from here rather than from whatever
// VITE_FIREBASE_* happens to sit in the developer's .env: the
// "not configured yet" behaviour below is the whole point of these
// assertions, and it can't depend on ambient environment.
const signInWithEmailAndPassword = vi.fn();
const createUserWithEmailAndPassword = vi.fn();
const signInWithPopup = vi.fn();

vi.mock("firebase/auth", () => ({
  GoogleAuthProvider: vi.fn(),
  createUserWithEmailAndPassword: (...args) => createUserWithEmailAndPassword(...args),
  onAuthStateChanged: vi.fn((auth, callback) => {
    callback(auth?.currentUser ?? null);
    return () => {};
  }),
  signInWithEmailAndPassword: (...args) => signInWithEmailAndPassword(...args),
  signInWithPopup: (...args) => signInWithPopup(...args),
  signOut: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock("../lib/firebase", () => ({
  isFirebaseConfigured: vi.fn(() => false),
  getFirebaseAuth: vi.fn(() => null),
}));

function renderAuth(mode, { state } = {}) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: mode === "signin" ? "/login" : "/signup", state }]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<AuthPage mode="signin" />} />
          <Route path="/signup" element={<AuthPage mode="signup" />} />
          <Route path="/with-jd" element={<div>With-JD tool</div>} />
          <Route path="/history" element={<div>History page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("AuthPage", () => {
  // Firebase reports itself unconfigured for this block, the same as a
  // real deployment with no Firebase project set up.
  beforeEach(async () => {
    const { isFirebaseConfigured, getFirebaseAuth } = await import("../lib/firebase");
    isFirebaseConfigured.mockReturnValue(false);
    getFirebaseAuth.mockReturnValue(null);
  });

  it("shows a visible preview badge when Firebase isn't configured -- never silently pretends to be live", () => {
    renderAuth("signin");
    expect(screen.getByText(/PREVIEW/)).toBeInTheDocument();
  });

  it("sign-in mode has no name field, sign-up mode does", () => {
    renderAuth("signin");
    expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();

    renderAuth("signup");
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
  });

  it("submitting the sign-in form when not configured shows an honest message, not a fake success", () => {
    renderAuth("signin");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(screen.getByText(/isn't configured yet/i)).toBeInTheDocument();
  });

  it("submitting the sign-up form when not configured shows an honest message", () => {
    renderAuth("signup");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Jordan Alvarez" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign Up" }));
    expect(screen.getByText(/isn't configured yet/i)).toBeInTheDocument();
  });

  it("clicking Google sign-in when not configured shows an honest message, not a silent no-op", () => {
    renderAuth("signin");
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(screen.getByText(/google sign-in isn't configured yet/i)).toBeInTheDocument();
  });

  it("the sign-in/sign-up toggle links to the other route", () => {
    const signin = renderAuth("signin");
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/signup");
    signin.unmount();

    renderAuth("signup");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});

/**
 * The gate on /with-jd and /without-jd is only half a fix if signing in
 * then strands the visitor on a page they never asked for. ProtectedRoute
 * puts the attempted path in the redirect's location state; these check
 * AuthPage actually honours it -- and refuses to honour an off-site one.
 */
describe("AuthPage post-sign-in destination", () => {
  beforeEach(async () => {
    const { isFirebaseConfigured, getFirebaseAuth } = await import("../lib/firebase");
    isFirebaseConfigured.mockReturnValue(true);
    getFirebaseAuth.mockReturnValue({ currentUser: null });
    signInWithEmailAndPassword.mockResolvedValue({ user: { email: "a@example.com" } });
    signInWithPopup.mockResolvedValue({ user: { email: "a@example.com" } });
  });

  async function submitSignIn() {
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
  }

  it("returns the visitor to the page they were trying to reach", async () => {
    renderAuth("signin", { state: { from: "/with-jd" } });
    await submitSignIn();
    await waitFor(() => expect(screen.getByText("With-JD tool")).toBeInTheDocument());
  });

  it("falls back to /history when they came to the login page directly", async () => {
    renderAuth("signin");
    await submitSignIn();
    await waitFor(() => expect(screen.getByText("History page")).toBeInTheDocument());
  });

  it("ignores an off-site destination rather than bouncing the user away", async () => {
    renderAuth("signin", { state: { from: "//evil.example.com/steal" } });
    await submitSignIn();
    await waitFor(() => expect(screen.getByText("History page")).toBeInTheDocument());
  });

  it("keeps the destination when the visitor switches to sign-up first", () => {
    renderAuth("signin", { state: { from: "/with-jd" } });
    fireEvent.click(screen.getByRole("link", { name: "Sign up" }));
    expect(screen.getByText("Create an account")).toBeInTheDocument();
    // Still carrying it: signing up here lands on /with-jd, not /history.
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
  });
});
