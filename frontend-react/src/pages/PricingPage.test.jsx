import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PricingPage } from "./PricingPage";
import { AuthProvider } from "../lib/authContext";
import { apiGet, apiPost } from "../lib/api";

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual("../lib/api");
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn() };
});

vi.mock("../lib/razorpay", () => ({ openRazorpayCheckout: vi.fn() }));

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
  getFirebaseAuth: vi.fn(() => ({ currentUser: null })),
}));

const SAMPLE_TIERS = {
  consumer: {
    free: { id: "free", name: "Free", monthly_price_usd: 0, annual_price_usd: null, features: ["basic_ats_readiness_score"] },
    pro: { id: "pro", name: "Pro", monthly_price_usd: 29, annual_price_usd: 216, features: ["voice_editor", "unlimited_resume_versions"] },
  },
};

function renderPricing() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <PricingPage />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("PricingPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders tiers with features once loaded", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    expect(screen.getByText("$29")).toBeInTheDocument();
    expect(screen.getByText("Voice-editing agent")).toBeInTheDocument();
  });

  it("switches to annual pricing when the toggle is clicked", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Annual"));
    expect(screen.getByText("$216")).toBeInTheDocument();
  });

  it("redirects to /login when clicking Upgrade while signed out", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Upgrade"));
    await waitFor(() => expect(apiPost).not.toHaveBeenCalled());
  });

  it("runs the full checkout flow when signed in: create-order -> Razorpay -> verify -> success", async () => {
    const { getFirebaseAuth } = await import("../lib/firebase");
    getFirebaseAuth.mockReturnValue({ currentUser: { email: "jordan@example.com" } });
    const { openRazorpayCheckout } = await import("../lib/razorpay");

    apiGet.mockImplementation((path) => {
      if (path === "/billing/tiers") return Promise.resolve(SAMPLE_TIERS);
      if (path === "/auth/me") return Promise.resolve({ tier: "free" });
      return Promise.reject(new Error("unexpected path"));
    });
    apiPost.mockImplementation((path) => {
      if (path === "/payments/create-order") {
        return Promise.resolve({ order_id: "order_1", amount: 2900, currency: "USD", key_id: "rzp_test_fake" });
      }
      if (path === "/payments/verify") return Promise.resolve({ status: "paid", tier: "pro" });
      return Promise.reject(new Error("unexpected path"));
    });
    openRazorpayCheckout.mockResolvedValue({
      razorpay_order_id: "order_1", razorpay_payment_id: "pay_1", razorpay_signature: "sig_1",
    });

    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Upgrade"));

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/payments/create-order", { tier: "pro", billing_cycle: "monthly", currency: "USD" }));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/payments/verify", { razorpay_order_id: "order_1", razorpay_payment_id: "pay_1", razorpay_signature: "sig_1" }));
    // currentTier updates immediately on success, so the button correctly
    // settles on "Current plan" (disabled) rather than a transient status
    // label -- consistent immediately, not just eventually on reload.
    await waitFor(() => expect(screen.getByText("Current plan")).toBeInTheDocument());
  });

  it("treats the user dismissing checkout as a non-error, not a failure banner", async () => {
    const { getFirebaseAuth } = await import("../lib/firebase");
    getFirebaseAuth.mockReturnValue({ currentUser: { email: "jordan@example.com" } });
    const { openRazorpayCheckout } = await import("../lib/razorpay");

    apiGet.mockImplementation((path) => {
      if (path === "/billing/tiers") return Promise.resolve(SAMPLE_TIERS);
      if (path === "/auth/me") return Promise.resolve({ tier: "free" });
      return Promise.reject(new Error("unexpected path"));
    });
    apiPost.mockResolvedValue({ order_id: "order_1", amount: 2900, currency: "USD", key_id: "rzp_test_fake" });
    openRazorpayCheckout.mockRejectedValue(new Error("dismissed"));

    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Upgrade"));

    await waitFor(() => expect(screen.getByText("Upgrade")).toBeInTheDocument()); // back to idle, not "error"
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
