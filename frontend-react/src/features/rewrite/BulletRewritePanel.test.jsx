import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BulletRewritePanel } from "./BulletRewritePanel";
import { ApiError, apiPost } from "../../lib/api";

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual("../../lib/api");
  return { ...actual, apiPost: vi.fn() };
});

const RESUME = {
  work: [
    {
      name: "Acme",
      position: "Engineer",
      highlights: [{ text: "Responsible for the billing system." }, { text: "Helped with monitoring." }],
    },
    {
      name: "Globex",
      position: "Intern",
      highlights: [{ text: "Wrote documentation." }],
    },
  ],
};

function mount(props = {}) {
  return render(
    <MemoryRouter>
      <BulletRewritePanel resume={RESUME} {...props} />
    </MemoryRouter>,
  );
}

afterEach(() => vi.clearAllMocks());

describe("BulletRewritePanel", () => {
  it("shows the role's existing bullets before anything is rewritten", () => {
    mount();
    expect(screen.getByText("Responsible for the billing system.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Rewrite 2 bullets/ })).toBeInTheDocument();
  });

  it("renders nothing at all when the resume has no bullets to work on", () => {
    const { container } = render(
      <MemoryRouter>
        <BulletRewritePanel resume={{ work: [{ name: "A", position: "B", highlights: [] }] }} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("sends the whole role in one request, which is how it is metered", async () => {
    apiPost.mockResolvedValue({ bullets: [], rewrites_used: 1, rewrites_limit: 3 });
    mount({ jdText: "Python and AWS role." });

    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/resume/rewrite-bullets", {
        bullets: ["Responsible for the billing system.", "Helped with monitoring."],
        role_title: "Engineer",
        company: "Acme",
        jd_text: "Python and AWS role.",
      }),
    );
    expect(apiPost).toHaveBeenCalledTimes(1);
  });

  it("renders each rewrite against the original it replaces", async () => {
    apiPost.mockResolvedValue({
      bullets: [
        { original: "Responsible for the billing system.", rewritten: "Owned the billing system end to end.", needs_metric: false, metric_hint: "" },
      ],
      rewrites_used: 1,
      rewrites_limit: 3,
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    expect(await screen.findByText("Owned the billing system end to end.")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 rewrites used")).toBeInTheDocument();
  });

  it("asks for the missing number instead of presenting an invented one", async () => {
    /* The honesty rule made visible. A bullet the model could not finish
       honestly must read as "your turn", not as a finished result -- if
       the UI hid this flag, the whole no-fabrication guarantee in
       bullet_rewrite.py would be invisible to the person it protects. */
    apiPost.mockResolvedValue({
      bullets: [
        {
          original: "Helped with monitoring.",
          rewritten: "Instrumented monitoring across the service fleet.",
          needs_metric: true,
          metric_hint: "How many services, and what did detection time go from and to?",
        },
      ],
      rewrites_used: 2,
      rewrites_limit: 3,
    });
    const { container } = mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    expect(await screen.findByText(/Add a number to finish this one/)).toBeInTheDocument();
    expect(screen.getByText(/How many services/)).toBeInTheDocument();
    expect(container.querySelector(".rewrite-results .needs-metric")).not.toBeNull();
  });

  it("switching roles clears the previous role's results", async () => {
    apiPost.mockResolvedValue({
      bullets: [{ original: "x", rewritten: "Rewrote it.", needs_metric: false, metric_hint: "" }],
      rewrites_used: 1,
      rewrites_limit: 3,
    });
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));
    expect(await screen.findByText("Rewrote it.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Intern — Globex/ }));

    // Stale rewrites shown under a different job would read as that job's
    // output, which is worse than showing nothing.
    expect(screen.queryByText("Rewrote it.")).not.toBeInTheDocument();
    expect(screen.getByText("Wrote documentation.")).toBeInTheDocument();
  });

  it("prompts a signed-out visitor to sign in rather than showing an error", async () => {
    apiPost.mockRejectedValue(new ApiError("Not authenticated", 401));
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    expect(await screen.findByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("pops the limit dialog -- not an error box -- when rewrites are spent", async () => {
    apiPost.mockRejectedValue(
      new ApiError("You've used all 3 AI rewrites included in the Free plan.", 429, {
        error: "rewrite_limit_reached",
        message: "You've used all 3 AI rewrites included in the Free plan.",
        used: 3,
        limit: 3,
        tier: "free",
        resets_at: "2026-10-01T00:00:00Z",
      }),
    );
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    const dialog = await screen.findByRole("alertdialog");
    // The dialog reads the noun out of the 429 body, so it must say
    // rewrites here and scans on the scoring routes.
    expect(dialog).toHaveTextContent(/AI rewrites/);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a plain error for anything else", async () => {
    apiPost.mockRejectedValue(new ApiError("The rewrite model didn't return a usable answer.", 502));
    mount();
    fireEvent.click(screen.getByRole("button", { name: /Rewrite 2 bullets/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/didn't return a usable answer/);
  });

  it("accepts plain-string highlights as well as { text } objects", () => {
    render(
      <MemoryRouter>
        <BulletRewritePanel resume={{ work: [{ name: "A", position: "Dev", highlights: ["Shipped a thing."] }] }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Shipped a thing.")).toBeInTheDocument();
  });
});
