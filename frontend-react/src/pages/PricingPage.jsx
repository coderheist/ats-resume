import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import { apiGet, apiPost } from "../lib/api";
import { openRazorpayCheckout } from "../lib/razorpay";
import { useAuth } from "../lib/authContext";
import { PLANS } from "../lib/seo";

const FEATURE_LABELS = {
  ats_readiness_score: "ATS readiness score",
  jd_match_report: "Job-description match report",
  top_5_suggestions: "Ranked fix list",
  json_resume_export: "JSON Resume export",
  ai_bullet_rewrite: "AI bullet rewriting",
  full_xai_breakdown: "Full explainable breakdown",
  scan_history: "Saved scan history",
  unlimited_resume_versions: "Unlimited resume versions",
  priority_support: "Priority support",
};

const CURRENCY_LABELS = { USD: "USD ($)", INR: "INR (₹)" };
const CURRENCY_SYMBOLS = { USD: "$", INR: "₹" };

/**
 * Cards to render before /billing/tiers answers -- and, more importantly,
 * the cards a crawler sees.
 *
 * This page is prerendered to static HTML at build time (scripts/
 * prerender.mjs). With the plans arriving only from an API call, the
 * prerendered /pricing was about 1.5 KB of empty shell: no prices at all
 * in the served markup, which is exactly what a search crawler and an AI
 * assistant read. Seeding from PLANS means the prices are in the HTML
 * before any JavaScript runs.
 *
 * The API response still replaces this the moment it lands, so the
 * backend stays the authority on what is actually sold -- and
 * tests/test_pricing_copy_matches_config.py fails the build if these two
 * ever disagree.
 */
function seedTiers() {
  return Object.fromEntries(
    PLANS.map((p) => [
      p.id,
      {
        id: p.id,
        name: p.name,
        tagline: "",
        price_inr: p.inr,
        price_usd: p.usd,
        duration_days: p.days,
        jd_match_scans: p.scans,
        ai_rewrites: p.rewrites,
        features: [],
      },
    ]),
  );
}

// How long a pass lasts, in the words a buyer uses. Derived from
// duration_days rather than stored separately so a pricing change in
// app/config.py can never leave the label saying something the checkout
// doesn't honour.
function durationLabel(days) {
  if (days === 7) return "for 7 days";
  if (days === 30) return "for 30 days";
  if (days % 30 === 0) return `for ${days / 30} months`;
  return `for ${days} days`;
}

/**
 * Plans are fixed-length passes, not auto-renewing subscriptions -- there
 * is no monthly/annual toggle because the tier IS the duration (see
 * app/config.py's Tier docstring). The page says "for 30 days" rather
 * than "/mo" for exactly that reason: "/mo" implies a recurring charge,
 * and nothing here recurs. Overstating the commitment is the version of
 * this mistake that produces chargebacks.
 *
 * Prices are listed per currency in app/config.py and never converted
 * here, so what the card shows is exactly what create-order charges.
 */
export function PricingPage() {
  const { user, configured } = useAuth();
  const navigate = useNavigate();
  const [tiers, setTiers] = useState(seedTiers);
  const [order, setOrder] = useState(PLANS.map((p) => p.id));
  const [recommended, setRecommended] = useState("pro");
  const [currency, setCurrency] = useState("USD");
  const [currencies, setCurrencies] = useState(["USD"]);
  const [currentTier, setCurrentTier] = useState(null);
  const [checkoutStatus, setCheckoutStatus] = useState({}); // { [tierId]: "idle" | "processing" | "success" | "error" }
  const [checkoutError, setCheckoutError] = useState(null);

  useEffect(() => {
    apiGet("/billing/tiers")
      .then((data) => {
      setTiers(data.consumer);
      // Display order and the highlighted plan are commercial decisions,
      // so they come from the backend's pricing table rather than being
      // decided again here from whatever order the object arrived in.
      if (data.display_order?.length) setOrder(data.display_order);
      if (data.recommended) setRecommended(data.recommended);
      if (data.currencies?.length) setCurrencies(data.currencies);
      if (data.default_currency) setCurrency(data.default_currency);
      })
      // The seeded cards stay up if the call fails -- a pricing page that
      // shows the plans beats one that shows a spinner forever.
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (user) apiGet("/auth/me").then((data) => setCurrentTier(data.tier)).catch(() => {});
  }, [user]);

  function priceFor(tier) {
    return tier[`price_${currency.toLowerCase()}`] ?? null;
  }

  function formatPrice(value) {
    const symbol = CURRENCY_SYMBOLS[currency] || `${currency} `;
    // Indian prices need thousands separators where the dollar ones
    // never did, and en-IN groups them differently (1,00,000).
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
      const created = await apiPost("/payments/create-order", { tier: tierId, currency });
      const result = await openRazorpayCheckout(created, { prefillEmail: user.email });
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

  const ordered = tiers ? (order.length ? order.map((id) => tiers[id]).filter(Boolean) : Object.values(tiers)) : [];

  return (
    <div className="app-shell">
      <header className="app-header">
        <h1>Plans and pricing</h1>
        <p>
          Every plan is a one-time pass, not a subscription. Nothing renews on its own and there is
          nothing to cancel.
        </p>
      </header>

      {currencies.length > 1 && (
        <div className="billing-toggle">
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

      {tiers && (
        <div className="pricing-grid">
          {ordered.map((tier) => {
            const price = priceFor(tier);
            const isFree = tier.id === "free";
            const isCurrent = currentTier === tier.id;
            const isRecommended = tier.id === recommended;
            const status = checkoutStatus[tier.id] || "idle";

            return (
              <div
                key={tier.id}
                className={`pricing-card ${isCurrent ? "pricing-card-current" : ""} ${
                  isRecommended ? "pricing-card-recommended" : ""
                }`}
              >
                {isRecommended && <p className="pricing-card-badge">Most popular</p>}
                <p className="pricing-card-name">{tier.name}</p>
                <p className="pricing-card-price">
                  {isFree ? (
                    "Free"
                  ) : (
                    <>
                      {formatPrice(price)}
                      <span className="pricing-card-period"> {durationLabel(tier.duration_days)}</span>
                    </>
                  )}
                </p>
                {tier.tagline && <p className="pricing-card-tagline">{tier.tagline}</p>}

                {/* The allowances are the product, so they lead -- a
                    buyer decides on "how many scans and rewrites do I
                    get", not on a feature checklist. */}
                <ul className="pricing-card-allowance">
                  <li>
                    <strong>{tier.jd_match_scans ?? "Unlimited"}</strong> resume scans
                  </li>
                  <li>
                    <strong>{tier.ai_rewrites ?? "Unlimited"}</strong> AI bullet rewrites
                  </li>
                </ul>

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
                    disabled={status === "processing"}
                    onClick={() => handleUpgrade(tier.id)}
                  >
                    {status === "processing"
                      ? "Processing…"
                      : status === "success"
                        ? "Activated ✓"
                        : `Get ${tier.name}`}
                  </button>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="pricing-footnote">
        Buying while a pass is still running adds the new days to what you have left — you never lose
        time you already paid for. Fair-use limit of 15 scans a day on paid plans.
      </p>
    </div>
  );
}
