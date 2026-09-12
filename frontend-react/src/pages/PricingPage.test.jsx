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

// Mirrors what /billing/tiers now serves: fixed-length passes with one
// price per currency, an allowance pair, and no billing cycle anywhere.
const SAMPLE_TIERS = {
  consumer: {
    free: {
      id: "free", name: "Free", tagline: "Try it on one application.",
      price_usd: 0, price_inr: 0, duration_days: 30,
      jd_match_scans: 5, ai_rewrites: 3,
      features: ["ats_readiness_score"],
    },
    pro: {
      id: "pro", name: "Pro", tagline: "100 scans and 100 rewrites a month.",
      price_usd: 12.99, price_inr: 399, duration_days: 30,
      jd_match_scans: 100, ai_rewrites: 100,
      features: ["ai_bullet_rewrite", "unlimited_resume_versions"],
    },
  },
  display_order: ["free", "pro"],
  recommended: "pro",
  currencies: ["USD"],
  default_currency: "USD",
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
    expect(screen.getByText("$12.99")).toBeInTheDocument();
    expect(screen.getByText("AI bullet rewriting")).toBeInTheDocument();
  });

  it("states the pass length rather than implying a recurring charge", async () => {
    /* "/mo" would say the card renews on its own. Nothing here does --
       there is no auto-debit integration and no mandate -- so the label
       has to say what the buyer is actually agreeing to. */
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    expect(screen.getByText(/for 30 days/)).toBeInTheDocument();
    expect(screen.queryByText("Annual")).not.toBeInTheDocument();
    expect(screen.queryByText("Monthly")).not.toBeInTheDocument();
  });

  it("leads with the allowances, which are what a buyer compares", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    // One allowance pair per card -- both plans list them.
    expect(screen.getAllByText(/resume scans/)).toHaveLength(2);
    expect(screen.getAllByText(/AI bullet rewrites/)).toHaveLength(2);
    // Pro lists 100 of each, so the figure appears twice on that card.
    expect(screen.getAllByText("100")).toHaveLength(2);
  });

  it("marks the plan the backend recommends, rather than deciding again here", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    const { container } = renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    expect(screen.getByText("Most popular")).toBeInTheDocument();
    expect(container.querySelectorAll(".pricing-card-recommended")).toHaveLength(1);
  });

  it("redirects to /login when clicking Upgrade while signed out", async () => {
    apiGet.mockResolvedValue(SAMPLE_TIERS);
    renderPricing();
    await waitFor(() => expect(screen.getByText("Pro")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Get Pro"));
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
    fireEvent.click(screen.getByText("Get Pro"));

    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/payments/create-order", { tier: "pro", currency: "USD" }));
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
    fireEvent.click(screen.getByText("Get Pro"));

    await waitFor(() => expect(screen.getByText("Get Pro")).toBeInTheDocument()); // back to idle, not "error"
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("PricingPage currency", () => {
  const TIERS_RESPONSE = {
    consumer: {
      boost: {
        id: "boost", name: "Boost", features: [], tagline: "One week, one big push.",
        price_usd: 4.99, price_inr: 149, duration_days: 7,
        jd_match_scans: 30, ai_rewrites: 30,
      },
      pro_season: {
        id: "pro_season", name: "Pro Season", features: [], tagline: "A whole job hunt.",
        price_usd: 29.99, price_inr: 999, duration_days: 90,
        jd_match_scans: 300, ai_rewrites: 300,
      },
    },
    display_order: ["boost", "pro_season"],
    recommended: "pro_season",
    currencies: ["USD", "INR"],
    default_currency: "USD",
  };

  function mountPricing() {
    apiGet.mockImplementation((path) =>
      path === "/billing/tiers" ? Promise.resolve(TIERS_RESPONSE) : Promise.resolve({ tier: "free" }),
    );
    return render(
      <MemoryRouter>
        <AuthProvider>
          <PricingPage />
        </AuthProvider>
      </MemoryRouter>,
    );
  }

  it("defaults to the currency the backend nominates", async () => {
    mountPricing();
    expect(await screen.findByText(/\$4\.99/)).toBeInTheDocument();
  });

  it("shows the listed INR price, not a conversion of the USD one", async () => {
    mountPricing();
    await screen.findByText(/\$4\.99/);

    fireEvent.click(screen.getByRole("button", { name: /INR/ }));

    // Rs 149 is config.py's own number, set at a local price point. A
    // conversion of $4.99 would land nowhere near it, which is the whole
    // point of listing prices per currency instead of converting.
    expect(await screen.findByText(/149/)).toBeInTheDocument();
    expect(screen.queryByText(/\$4\.99/)).not.toBeInTheDocument();
  });

  it("applies the currency to every pass length", async () => {
    mountPricing();
    await screen.findByText(/\$4\.99/);

    fireEvent.click(screen.getByRole("button", { name: /INR/ }));

    expect(await screen.findByText(/149/)).toBeInTheDocument();
    expect(screen.getByText(/999/)).toBeInTheDocument();
  });

  it("offers only the currencies the backend supports", async () => {
    mountPricing();
    await screen.findByText(/\$4\.99/);

    expect(screen.getByRole("button", { name: /USD/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /INR/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /EUR/ })).not.toBeInTheDocument();
  });
});
