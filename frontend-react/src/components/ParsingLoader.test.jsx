import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ParsingLoader } from "./ParsingLoader";

describe("ParsingLoader", () => {
  it("renders as an announced status region", () => {
    render(<ParsingLoader />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders each letter of the given text as a separate span", () => {
    render(<ParsingLoader text="Hi" />);
    const overlay = screen.getByRole("status");
    expect(overlay.querySelectorAll(".parsing-loader-text span")).toHaveLength(2);
  });

  it("defaults to 'Analyzing'", () => {
    render(<ParsingLoader />);
    expect(screen.getByRole("status")).toHaveAttribute("aria-label", "Analyzing…");
  });
});
