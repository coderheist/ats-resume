import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RoleSelect } from "./RoleSelect";

const ROLES = [
  { id: "ai_engineer", label: "Ai Engineer", expected_skills: ["machine_learning", "python"] },
  { id: "software_engineer", label: "Software Engineer", expected_skills: ["python", "sql"] },
];

describe("RoleSelect", () => {
  it("offers every role plus an infer-it default", () => {
    render(<RoleSelect roles={ROLES} value="" onChange={vi.fn()} />);

    const options = screen.getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Infer from my resume", "Ai Engineer", "Software Engineer"]);
  });

  it("defaults to inferring, so the previous behaviour is what you get by doing nothing", () => {
    render(<RoleSelect roles={ROLES} value="" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox")).toHaveValue("");
  });

  it("reports the selected role id, not its label", () => {
    const onChange = vi.fn();
    render(<RoleSelect roles={ROLES} value="" onChange={onChange} />);

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ai_engineer" } });

    expect(onChange).toHaveBeenCalledWith("ai_engineer");
  });

  it("explains which mode you are in", () => {
    const { rerender } = render(<RoleSelect roles={ROLES} value="" onChange={vi.fn()} />);
    expect(screen.getByText(/We'll guess the role/)).toBeInTheDocument();

    rerender(<RoleSelect roles={ROLES} value="ai_engineer" onChange={vi.fn()} />);
    expect(screen.getByText(/measured against this role/)).toBeInTheDocument();
  });

  it("renders nothing when the role list could not be loaded", () => {
    // useRoles swallows a failed fetch and yields []. An empty dropdown
    // would look broken; omitting the control lets the backend infer,
    // which is a working report rather than a dead control.
    const { container } = render(<RoleSelect roles={[]} value="" onChange={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is disabled while a scan is running", () => {
    render(<RoleSelect roles={ROLES} value="" onChange={vi.fn()} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
