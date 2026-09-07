import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthPage } from "./AuthPage";
import { AuthProvider } from "../lib/authContext";

function renderAuth(mode) {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <AuthPage mode={mode} />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("AuthPage", () => {
  // No VITE_FIREBASE_* env vars in this test environment -- `configured`
  // is genuinely false here, same as it would be in a real deployment
  // with no Firebase project set up. This isn't mocked to be false; it's
  // the real isFirebaseConfigured() check evaluating honestly.

  it("shows a visible preview badge when Firebase isn't configured -- never silently pretends to be live", () => {
    renderAuth("signin");
    expect(screen.getByText(/PREVIEW/)).toBeInTheDocument();
  });

  it("sign-in mode has no name field, sign-up mode does", () => {
    renderAuth("signin");
    expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();

    renderAuth("signup");
    expect(screen.getByLabelText("Full name")).toBeInTheDocument();
  });

  it("submitting the sign-in form when not configured shows an honest message, not a fake success", () => {
    renderAuth("signin");
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(screen.getByText(/isn't configured yet/i)).toBeInTheDocument();
  });

  it("submitting the sign-up form when not configured shows an honest message", () => {
    renderAuth("signup");
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Jordan Alvarez" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign Up" }));
    expect(screen.getByText(/isn't configured yet/i)).toBeInTheDocument();
  });

  it("clicking Google sign-in when not configured shows an honest message, not a silent no-op", () => {
    renderAuth("signin");
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(screen.getByText(/google sign-in isn't configured yet/i)).toBeInTheDocument();
  });

  it("the sign-in/sign-up toggle links to the other route", () => {
    renderAuth("signin");
    expect(screen.getByRole("link", { name: "Sign up" })).toHaveAttribute("href", "/signup");

    renderAuth("signup");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});
