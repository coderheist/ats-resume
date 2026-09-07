import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";
import { AuthProvider } from "../lib/authContext";
import { apiGet } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual("../lib/api");
  return { ...actual, apiGet: vi.fn() };
});

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
  getFirebaseAuth: vi.fn(() => ({ currentUser: { email: "jordan@example.com", displayName: "Jordan Alvarez" } })),
}));

function renderSettings() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <SettingsPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("SettingsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows the signed-in user's name and email", async () => {
    apiGet.mockResolvedValue({ tier: "free", tier_name: "Free", jd_match_scans_per_month: 3, jd_match_scans_used_this_month: 1 });
    renderSettings();
    await waitFor(() => expect(screen.getByText("Jordan Alvarez")).toBeInTheDocument());
    expect(screen.getByText("jordan@example.com")).toBeInTheDocument();
  });

  it("shows the current plan and usage", async () => {
    apiGet.mockResolvedValue({ tier: "free", tier_name: "Free", jd_match_scans_per_month: 3, jd_match_scans_used_this_month: 1 });
    renderSettings();
    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
  });

  it("calls signOutUser and navigates home when Sign out is clicked", async () => {
    apiGet.mockResolvedValue({ tier: "free", tier_name: "Free", jd_match_scans_per_month: 3, jd_match_scans_used_this_month: 1 });
    const { signOut } = await import("firebase/auth");
    renderSettings();
    await waitFor(() => screen.getByText("Sign out"));
    fireEvent.click(screen.getByText("Sign out"));
    await waitFor(() => expect(signOut).toHaveBeenCalled());
  });
});
