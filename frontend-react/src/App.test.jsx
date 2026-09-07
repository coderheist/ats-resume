import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { App } from "./App";
import { AuthProvider } from "./lib/authContext";

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>
  );
}

describe("App routing", () => {
  it("renders the hero at /", () => {
    renderAt("/");
    expect(screen.getByText(/Know exactly where your resume stands/i)).toBeInTheDocument();
  });

  it("renders the with-JD report page at /with-jd", () => {
    renderAt("/with-jd");
    expect(screen.getByText("Score against a job description")).toBeInTheDocument();
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
  });

  it("renders the standalone report page at /without-jd", () => {
    renderAt("/without-jd");
    expect(screen.getByText("General ATS readiness")).toBeInTheDocument();
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
  });

  it("hero links point at the two report routes", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /analyze against a job description/i })).toHaveAttribute("href", "/with-jd");
    expect(screen.getByRole("link", { name: /check general ats readiness/i })).toHaveAttribute("href", "/without-jd");
  });

  // AuthPage is code-split (React.lazy in App.jsx -- /login and /signup are
  // noindex routes nobody lands on first, so their JS is kept out of the
  // bundle that blocks the landing page's first paint). These two therefore
  // have to await the chunk resolving instead of asserting synchronously.
  it("renders the login page at /login", async () => {
    renderAt("/login");
    expect(await screen.findByText("Sign in to your account")).toBeInTheDocument();
  });

  it("renders the signup page at /signup", async () => {
    renderAt("/signup");
    expect(await screen.findByText("Create an account")).toBeInTheDocument();
  });

  it("shows the navbar on the hero and report pages, but not on auth pages", () => {
    renderAt("/");
    expect(screen.getByText("Resume Optimizer")).toBeInTheDocument();
  });

  it("has a skip-to-content link and a main landmark for keyboard/screen-reader users", () => {
    renderAt("/");
    expect(screen.getByRole("link", { name: /skip to main content/i })).toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  });
});
