import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepIndicator } from "./StepIndicator";

const STEPS = ["Upload", "Details", "Report"];

describe("StepIndicator", () => {
  it("shows the current step's number, and check marks for completed steps", () => {
    render(<StepIndicator steps={STEPS} current={2} />);
    expect(screen.getByText("Upload")).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
    expect(screen.getByText("Report")).toBeInTheDocument();
    // Step 1 is done -> checkmark icon rendered instead of "1"
    expect(screen.queryByText("1")).not.toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders all step labels regardless of current position", () => {
    render(<StepIndicator steps={STEPS} current={1} />);
    STEPS.forEach((label) => expect(screen.getByText(label)).toBeInTheDocument());
  });
});
