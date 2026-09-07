/**
 * Razorpay's Checkout widget isn't an npm package -- it's a script tag
 * (https://checkout.razorpay.com/v1/checkout.js) that attaches
 * `window.Razorpay` globally, per Razorpay's own integration docs. This
 * loads it once (cached) and exposes a promise-based `openCheckout()`
 * instead of the raw callback-based `new Razorpay(options).open()` API,
 * so the calling code can `await` a result the same way it awaits every
 * other API call in this app.
 */
let scriptLoadPromise = null;

function loadCheckoutScript() {
  if (scriptLoadPromise) return scriptLoadPromise;
  scriptLoadPromise = new Promise((resolve, reject) => {
    if (window.Razorpay) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Couldn't load the payment widget. Check your connection and try again."));
    document.body.appendChild(script);
  });
  return scriptLoadPromise;
}

/**
 * order: { order_id, amount, currency, key_id } -- exactly what
 * POST /payments/create-order returns.
 * Resolves with { razorpay_order_id, razorpay_payment_id, razorpay_signature }
 * on success (ready to hand to POST /payments/verify). Rejects if the
 * user dismisses the widget (a real, common, non-error outcome -- not
 * every rejection here is a failure) or the script fails to load.
 */
export async function openRazorpayCheckout(order, { name, description, prefillEmail } = {}) {
  await loadCheckoutScript();

  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      order_id: order.order_id,
      name: name || "Resume Optimizer",
      description: description || "Subscription upgrade",
      prefill: prefillEmail ? { email: prefillEmail } : undefined,
      handler: (response) => {
        resolve({
          razorpay_order_id: response.razorpay_order_id,
          razorpay_payment_id: response.razorpay_payment_id,
          razorpay_signature: response.razorpay_signature,
        });
      },
      modal: {
        ondismiss: () => reject(new Error("dismissed")),
      },
    });
    rzp.on("payment.failed", (response) => {
      reject(new Error(response.error?.description || "Payment failed."));
    });
    rzp.open();
  });
}
