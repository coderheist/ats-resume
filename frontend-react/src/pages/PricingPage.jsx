import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import { apiGet, apiPost } from "../lib/api";
import { openRazorpayCheckout } from "../lib/razorpay";
import { useAuth } from "../lib/authContext";

const FEATURE_LABELS = {
  basic_ats_readiness_score: "Basic ATS readiness score",
  json_resume_export: "JSON Resume export",
  full_xai_breakdown: "Full explainable match breakdown",
  jd_less_scoring: "JD-less readiness scoring",
  cover_letter_draft: "Cover letter drafting",
  voice_editor: "Voice-editing agent",
  unlimited_resume_versions: "Unlimited resume versions",
  uncapped_voice_minutes: "Uncapped voice minutes",
  multilanguage_stt: "Multi-language voice input",
  jd_bias_audit_tool: "JD bias audit tool",
};

const CURRENCY_LABELS = { USD: "USD ($)", INR: "INR (₹)" };
const CURRENCY_SYMBOLS = { USD: "$", INR: "₹" };

/**
 * Prices are listed per currency in app/config.py, never converted
 * here -- so what the card shows is exactly what create-order charges,
 * with no exchange rate able to move it in between.
 */
export function PricingPage() {
  const { user, configured } = useAuth();
  const navigate = useNavigate();
  const [tiers, setTiers] = useState(null);
  const [billingCycle, setBillingCycle] = useState("monthly");
  const [currency, setCurrency] = useState("USD");
  const [currencies, setCurrencies] = useState(["USD"]);
  const [currentTier, setCurrentTier] = useState(null);
  const [checkoutStatus, setCheckoutStatus] = useState({}); // { [tierId]: "idle" | "processing" | "success" | "error" }
  const [checkoutError, setCheckoutError] = useState(null);

  useEffect(() => {
    apiGet("/billing/tiers").then((data) => {
      setTiers(data.consumer);
      // Served by the backend rather than hard-coded: a toggle offering
      // a currency checkout would reject is worse than not offering it.
      if (data.currencies?.length) setCurrencies(data.currencies);
      if (data.default_currency) setCurrency(data.default_currency);
    });
  }, []);

  useEffect(() => {
    if (user) apiGet("/auth/me").then((data) => setCurrentTier(data.tier)).catch(() => {});
  }, [user]);

  // The tier objects carry a field per (cycle, currency) pair --
  // monthly_price_inr, annual_price_usd, and so on -- mirroring
  // config.py's price_for(). null means this plan doesn't offer that
  // combination, which the card renders as "Not offered".
  function priceFor(tier) {
    return tier[`${billingCycle}_price_${currency.toLowerCase()}`] ?? null;
  }

  function formatPrice(value) {
    const symbol = CURRENCY_SYMBOLS[currency] || `${currency} `;
    // Indian prices are four and five digits, so they need thousands
    // separators to stay readable where the dollar ones never did.
    return `${symbol}${Number(value).toLocaleString(currency === "INR" ? "en-IN" : "en-US")}`;
  }

  async function handleUpgrade(tierId) {
    if (!configured || !user) {
      navigate("/login");
      return;
    }
    setCheckoutError(null);
    setCheckoutStatus((s) => ({ ...s, [tierId]: "processing" }));
    try {
      const order = await apiPost("/payments/create-order", { tier: tierId, billing_cycle: billingCycle, currency });
      const result = await openRazorpayCheckout(order, { prefillEmail: user.email });
      await apiPost("/payments/verify", result);
      setCheckoutStatus((s) => ({ ...s, [tierId]: "success" }));
      setCurrentTier(tierId);
    } catch (err) {
      if (err.message === "dismissed") {
        // User closed the checkout widget themselves -- not a real error.
        setCheckoutStatus((s) => ({ ...s, [tierId]: "idle" }));
        return;
      }
      setCheckoutStatus((s) => ({ ...s, [tierId]: "error" }));
      setCheckoutError(err.message);
    }
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Plans and pricing</h1>
        <p>Start free. Upgrade for unlimited scans and the voice-editing agent.</p>
      </header>

      <div className="billing-toggle">
        <button
          className={`billing-toggle-btn ${billingCycle === "monthly" ? "active" : ""}`}
          onClick={() => setBillingCycle("monthly")}
        >
          Monthly
        </button>
        <button
          className={`billing-toggle-btn ${billingCycle === "annual" ? "active" : ""}`}
          onClick={() => setBillingCycle("annual")}
        >
          Annual
        </button>
      </div>

      {currencies.length > 1 && (
        <div className="billing-toggle" style={{ marginTop: 8 }}>
          {currencies.map((code) => (
            <button
              key={code}
              className={`billing-toggle-btn ${currency === code ? "active" : ""}`}
              onClick={() => setCurrency(code)}
            >
              {CURRENCY_LABELS[code] || code}
            </button>
          ))}
        </div>
      )}

      {!configured && (
        <p className="tag-empty" style={{ marginBottom: 16 }}>
          Accounts and checkout aren't connected yet in this deployment (no Firebase/Razorpay project configured) —
          plans are shown for preview.
        </p>
      )}
      {checkoutError && <div className="error-box" style={{ marginBottom: 16 }}>{checkoutError}</div>}

      {!tiers && <p className="status-text">Loading plans…</p>}

      {tiers && (
        <div className="pricing-grid">
          {Object.values(tiers).map((tier) => {
            const price = priceFor(tier);
            const isFree = tier.id === "free";
            const isCurrent = currentTier === tier.id;
            const status = checkoutStatus[tier.id] || "idle";
            const unavailable = price === null && !isFree;

            return (
              <div key={tier.id} className={`pricing-card ${isCurrent ? "pricing-card-current" : ""}`}>
                <p className="pricing-card-name">{tier.name}</p>
                <p className="pricing-card-price">
                  {isFree ? (
                    "Free"
                  ) : unavailable ? (
                    <span className="tag-empty">Not offered {billingCycle}</span>
                  ) : (
                    <>
                      {formatPrice(price)}
                      <span className="pricing-card-period">/{billingCycle === "annual" ? "yr" : "mo"}</span>
                    </>
                  )}
                </p>
                <ul className="pricing-card-features">
                  {tier.features.map((f) => (
                    <li key={f}>
                      <Check size={14} /> {FEATURE_LABELS[f] || f.replace(/_/g, " ")}
                    </li>
                  ))}
                </ul>
                {isFree ? (
                  <span className="tag-empty">Always free</span>
                ) : isCurrent ? (
                  <button className="btn-outline" disabled>
                    Current plan
                  </button>
                ) : (
                  <button
                    className="btn-primary"
                    disabled={unavailable || status === "processing"}
                    onClick={() => handleUpgrade(tier.id)}
                  >
                    {status === "processing" ? "Processing…" : status === "success" ? "Upgraded ✓" : "Upgrade"}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
