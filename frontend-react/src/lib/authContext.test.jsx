import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./authContext";

// Stubbed rather than relying on VITE_FIREBASE_* being absent: a real
// .env in a developer's checkout would otherwise make isFirebaseConfigured()
// true and this file would assert the opposite of what it renders.
vi.mock("./firebase", () => ({
  isFirebaseConfigured: vi.fn(() => false),
  getFirebaseAuth: vi.fn(() => null),
}));

function Probe() {
  const { user, loading, configured } = useAuth();
  if (loading) return <span>loading</span>;
  return (
    <span>
      configured={String(configured)} user={user ? user.email : "none"}
    </span>
  );
}

describe("AuthProvider", () => {
  it("resolves loading=false immediately when Firebase isn't configured", async () => {
    render(
      <AuthProvider>
        <Probe />
      </AuthProvider>
    );
    await waitFor(() => expect(screen.getByText(/configured=false/)).toBeInTheDocument());
    expect(screen.getByText(/user=none/)).toBeInTheDocument();
  });

  it("useAuth throws a clear error outside AuthProvider, rather than silently returning undefined", () => {
    // Swallow the expected console.error from React's error boundary noise
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow("useAuth must be used within an AuthProvider");
    spy.mockRestore();
  });
});
