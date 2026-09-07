import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProtectedRoute } from "./ProtectedRoute";
import { AuthProvider } from "../lib/authContext";

vi.mock("firebase/auth", () => ({
  GoogleAuthProvider: vi.fn(),
  createUserWithEmailAndPassword: vi.fn(),
  onAuthStateChanged: vi.fn((auth, callback) => {
    callback(auth.currentUser);
    return () => {};
  }),
  signInWithEmailAndPassword: vi.fn(),
  signInWithPopup: vi.fn(),
  signOut: vi.fn(),
  updateProfile: vi.fn(),
}));

vi.mock("../lib/firebase", () => ({
  isFirebaseConfigured: vi.fn(() => true),
  getFirebaseAuth: vi.fn(),
}));

function renderProtected(currentUser) {
  return render(
    <MemoryRouter initialEntries={["/protected"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>Login page</div>} />
          <Route path="/protected" element={<ProtectedRoute><div>Secret content</div></ProtectedRoute>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("ProtectedRoute with Firebase configured", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("redirects to /login when configured but signed out", async () => {
    const { getFirebaseAuth } = await import("../lib/firebase");
    getFirebaseAuth.mockReturnValue({ currentUser: null });
    renderProtected();
    await waitFor(() => expect(screen.getByText("Login page")).toBeInTheDocument());
  });

  it("renders the protected content when configured and signed in", async () => {
    const { getFirebaseAuth } = await import("../lib/firebase");
    getFirebaseAuth.mockReturnValue({ currentUser: { email: "jordan@example.com" } });
    renderProtected();
    await waitFor(() => expect(screen.getByText("Secret content")).toBeInTheDocument());
  });
});

describe("ProtectedRoute without Firebase configured", () => {
  it("renders children directly rather than redirecting into a login page that can't do anything either", async () => {
    const { isFirebaseConfigured } = await import("../lib/firebase");
    isFirebaseConfigured.mockReturnValue(false);
    renderProtected();
    await waitFor(() => expect(screen.getByText("Secret content")).toBeInTheDocument());
  });
});
