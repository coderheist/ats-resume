import { renderHook, waitFor } from "@testing-library/react";
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./authContext";

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

vi.mock("./firebase", () => ({
  isFirebaseConfigured: vi.fn(() => true),
  getFirebaseAuth: vi.fn(() => ({ currentUser: null })),
}));

function wrapper({ children }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("signInWithGoogle error handling", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("silently returns (no throw) when the user closes the popup themselves", async () => {
    const { signInWithPopup } = await import("firebase/auth");
    const err = new Error("popup closed");
    err.code = "auth/popup-closed-by-user";
    signInWithPopup.mockRejectedValue(err);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(act(() => result.current.signInWithGoogle())).resolves.toBeUndefined();
  });

  it("translates a blocked popup into an actionable message", async () => {
    const { signInWithPopup } = await import("firebase/auth");
    const err = new Error("popup blocked");
    err.code = "auth/popup-blocked";
    signInWithPopup.mockRejectedValue(err);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(act(() => result.current.signInWithGoogle())).rejects.toThrow(/blocked the sign-in popup/i);
  });

  it("translates account-exists-with-different-credential into an actionable message", async () => {
    const { signInWithPopup } = await import("firebase/auth");
    const err = new Error("account exists");
    err.code = "auth/account-exists-with-different-credential";
    signInWithPopup.mockRejectedValue(err);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(act(() => result.current.signInWithGoogle())).rejects.toThrow(/different sign-in method/i);
  });

  it("re-throws unrecognized error codes as-is", async () => {
    const { signInWithPopup } = await import("firebase/auth");
    const err = new Error("something else broke");
    err.code = "auth/network-request-failed";
    signInWithPopup.mockRejectedValue(err);

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(act(() => result.current.signInWithGoogle())).rejects.toThrow("something else broke");
  });

  it("resolves normally on success", async () => {
    const { signInWithPopup } = await import("firebase/auth");
    signInWithPopup.mockResolvedValue({ user: { email: "jordan@example.com" } });

    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.loading).toBe(false));

    await expect(act(() => result.current.signInWithGoogle())).resolves.toBeUndefined();
  });
});
