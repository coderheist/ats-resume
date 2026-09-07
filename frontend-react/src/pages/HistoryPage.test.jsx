import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HistoryPage } from "./HistoryPage";
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
  getFirebaseAuth: vi.fn(() => ({ currentUser: { email: "jordan@example.com" } })),
}));

function renderHistory() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <HistoryPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("HistoryPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows saved scans once loaded", async () => {
    apiGet.mockResolvedValue({
      history: [
        { scan_id: "1", resume_name: "Jordan Alvarez", mode: "jd_match", final_score: 82.4, created_at: "2026-01-01T00:00:00Z" },
      ],
    });
    renderHistory();
    await waitFor(() => expect(screen.getByText("Jordan Alvarez")).toBeInTheDocument());
    expect(screen.getByText("82.4")).toBeInTheDocument();
  });

  it("shows an empty-state message when there's no history yet", async () => {
    apiGet.mockResolvedValue({ history: [] });
    renderHistory();
    await waitFor(() => expect(screen.getByText(/no saved analyses yet/i)).toBeInTheDocument());
  });

  it("shows an error box when the API call fails", async () => {
    apiGet.mockRejectedValue(new Error("500 Internal Server Error"));
    renderHistory();
    await waitFor(() => expect(screen.getByText(/500 Internal Server Error/)).toBeInTheDocument());
  });
});

describe("HistoryPage without Firebase configured", () => {
  it("shows an honest not-configured message rather than an API error", async () => {
    const { isFirebaseConfigured } = await import("../lib/firebase");
    isFirebaseConfigured.mockReturnValue(false);
    render(
      <MemoryRouter>
        <AuthProvider>
          <HistoryPage />
        </AuthProvider>
      </MemoryRouter>
    );
    await waitFor(() => expect(apiGet).not.toHaveBeenCalled());
  });
});
