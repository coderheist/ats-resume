import { afterEach, describe, expect, it, vi } from "vitest";

describe("openRazorpayCheckout", () => {
  afterEach(() => {
    vi.resetModules();
    delete window.Razorpay;
    document.querySelectorAll("script").forEach((s) => s.remove());
  });

  it("resolves with the payment details when the handler fires", async () => {
    let capturedOptions;
    window.Razorpay = vi.fn().mockImplementation((options) => {
      capturedOptions = options;
      return {
        open: () => {
          options.handler({
            razorpay_order_id: "order_1",
            razorpay_payment_id: "pay_1",
            razorpay_signature: "sig_1",
          });
        },
        on: vi.fn(),
      };
    });

    const { openRazorpayCheckout } = await import("./razorpay");
    const result = await openRazorpayCheckout(
      { order_id: "order_1", amount: 2900, currency: "USD", key_id: "rzp_test_fake" },
      { prefillEmail: "jordan@example.com" }
    );

    expect(result).toEqual({
      razorpay_order_id: "order_1",
      razorpay_payment_id: "pay_1",
      razorpay_signature: "sig_1",
    });
    expect(capturedOptions.key).toBe("rzp_test_fake");
    expect(capturedOptions.prefill).toEqual({ email: "jordan@example.com" });
  });

  it("rejects with a 'dismissed' error when the user closes the widget", async () => {
    window.Razorpay = vi.fn().mockImplementation((options) => ({
      open: () => options.modal.ondismiss(),
      on: vi.fn(),
    }));

    const { openRazorpayCheckout } = await import("./razorpay");
    await expect(
      openRazorpayCheckout({ order_id: "order_1", amount: 2900, currency: "USD", key_id: "rzp_test_fake" })
    ).rejects.toThrow("dismissed");
  });

  it("rejects with the failure description when payment.failed fires", async () => {
    window.Razorpay = vi.fn().mockImplementation((options) => ({
      open: () => {},
      on: (event, cb) => {
        if (event === "payment.failed") cb({ error: { description: "Card declined" } });
      },
    }));

    const { openRazorpayCheckout } = await import("./razorpay");
    await expect(
      openRazorpayCheckout({ order_id: "order_1", amount: 2900, currency: "USD", key_id: "rzp_test_fake" })
    ).rejects.toThrow("Card declined");
  });
});
