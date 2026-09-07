import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { Navbar } from "./Navbar";
import { PasswordField } from "./PasswordField";
import { AuthProvider } from "../lib/authContext";

function renderNavbar() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Navbar />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("Navbar", () => {
  it("links only to real routes -- no dead nav items", () => {
    renderNavbar();
    expect(screen.getByRole("link", { name: "Resume Optimizer" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Score vs. a job" })).toHaveAttribute("href", "/with-jd");
    expect(screen.getByRole("link", { name: "General readiness" })).toHaveAttribute("href", "/without-jd");
  });

  it("toggles the mobile menu open and closed", () => {
    renderNavbar();
    const toggle = screen.getByRole("button", { name: "Open menu" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close menu" }));
    expect(screen.getByRole("button", { name: "Open menu" })).toBeInTheDocument();
  });
});

describe("PasswordField", () => {
  it("masks the input by default and toggles visibility", () => {
    render(<PasswordField label="Password" name="password" />);
    const input = screen.getByLabelText("Password");
    expect(input).toHaveAttribute("type", "password");

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input).toHaveAttribute("type", "text");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input).toHaveAttribute("type", "password");
  });
});
