import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";
import { AuthProvider } from "../lib/authContext";
import { apiGet } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual("../lib/api");
  return { ...actual, apiGet: vi.fn() };
});

function renderDashboard() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <DashboardPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("DashboardPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("shows the plan name, usage, and recent history once loaded", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/auth/me") return Promise.resolve({ tier: "free", tier_name: "Free", jd_match_scans_per_month: 3, jd_match_scans_used_this_month: 1 });
      if (path === "/history") return Promise.resolve({ history: [{ scan_id: "1", resume_name: "Jordan Alvarez", mode: "jd_match", final_score: 82.4, created_at: "2026-01-01T00:00:00Z" }] });
      return Promise.reject(new Error("unexpected"));
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByText("Free")).toBeInTheDocument());
    expect(screen.getByText(/1 of 3 scans used/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Jordan Alvarez")).toBeInTheDocument());
  });

  it("shows an upgrade link for free-tier users", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/auth/me") return Promise.resolve({ tier: "free", tier_name: "Free", jd_match_scans_per_month: 3, jd_match_scans_used_this_month: 0 });
      if (path === "/history") return Promise.resolve({ history: [] });
      return Promise.reject(new Error("unexpected"));
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByRole("link", { name: "Upgrade" })).toBeInTheDocument());
  });

  it("shows an empty-state message with no history yet", async () => {
    apiGet.mockImplementation((path) => {
      if (path === "/auth/me") return Promise.resolve({ tier: "pro", tier_name: "Pro", jd_match_scans_per_month: null, jd_match_scans_used_this_month: 0 });
      if (path === "/history") return Promise.resolve({ history: [] });
      return Promise.reject(new Error("unexpected"));
    });
    renderDashboard();
    await waitFor(() => expect(screen.getByText(/no scans yet/i)).toBeInTheDocument());
  });
});
