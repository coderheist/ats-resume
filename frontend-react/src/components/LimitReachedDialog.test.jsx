import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { LimitReachedDialog } from "./LimitReachedDialog";

const DETAIL = {
  error: "scan_limit_reached",
  message: "You've used all 10 scans included in the Free plan this month.",
  used: 10,
  limit: 10,
  resets_at: "2026-10-01T00:00:00Z",
};

function renderDialog(props = {}) {
  const onClose = vi.fn();
  render(
    <MemoryRouter>
      <LimitReachedDialog detail={DETAIL} onClose={onClose} {...props} />
    </MemoryRouter>
  );
  return onClose;
}

describe("LimitReachedDialog", () => {
  it("names the limit and when the allowance comes back", () => {
    renderDialog();
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(screen.getByText(/all 10 scans/i)).toBeInTheDocument();
    expect(screen.getByText(/^Resets /)).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /see plans/i })).toHaveAttribute("href", "/pricing");
  });

  it("renders nothing at all without a detail payload", () => {
    render(
      <MemoryRouter>
        <LimitReachedDialog detail={null} onClose={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    const onClose = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on 'Not now'", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /not now/i }));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the backdrop behind the dialog is clicked", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("alertdialog").parentElement);
    expect(onClose).toHaveBeenCalled();
  });

  it("does not close when the dialog body itself is clicked", () => {
    const onClose = renderDialog();
    fireEvent.click(screen.getByRole("alertdialog"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("still renders when the backend sent no reset timestamp", () => {
    renderDialog({ detail: { ...DETAIL, resets_at: null } });
    expect(screen.getByText(/all 10 scans/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Resets /)).not.toBeInTheDocument();
  });
});
