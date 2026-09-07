import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BulletList } from "../components/BulletList";
import { DimensionTile } from "../components/DimensionTile";
import { GaugeBar } from "../components/GaugeBar";
import { KnockoutBanner } from "../components/KnockoutBanner";
import { ReportSkeleton } from "../components/ReportSkeleton";
import { RoleBadge } from "../components/RoleBadge";
import { TagList } from "../components/TagList";

describe("TagList", () => {
  it("renders items as tags", () => {
    render(<TagList items={["python", "react"]} kind="match" emptyText="none" />);
    expect(screen.getByText("python")).toBeInTheDocument();
    expect(screen.getByText("react")).toBeInTheDocument();
  });

  it("shows the empty-state text when there are no items", () => {
    render(<TagList items={[]} kind="gap" emptyText="No gaps found." />);
    expect(screen.getByText("No gaps found.")).toBeInTheDocument();
  });
});

describe("BulletList", () => {
  it("renders each item as a list entry", () => {
    render(<BulletList items={["Fix this", "Fix that"]} kind="gaps" emptyText="none" />);
    expect(screen.getByText("Fix this")).toBeInTheDocument();
    expect(screen.getByText("Fix that")).toBeInTheDocument();
  });

  it("numbers suggestion items", () => {
    render(<BulletList items={["First fix", "Second fix"]} kind="suggestions" emptyText="none" />);
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("shows empty-state text for an empty list", () => {
    render(<BulletList items={[]} kind="strengths" emptyText="Nothing yet." />);
    expect(screen.getByText("Nothing yet.")).toBeInTheDocument();
  });
});

describe("KnockoutBanner", () => {
  it("renders HIGH risk", () => {
    render(<KnockoutBanner risk="HIGH" />);
    expect(screen.getByText(/Knockout Risk: HIGH/)).toBeInTheDocument();
  });

  it("renders LOW risk", () => {
    render(<KnockoutBanner risk="LOW" />);
    expect(screen.getByText(/Knockout Risk: LOW/)).toBeInTheDocument();
  });
});

describe("DimensionTile", () => {
  it("renders the rounded percentage and label", () => {
    render(<DimensionTile label="Semantic fit" value={62.4} />);
    expect(screen.getByText("62%")).toBeInTheDocument();
    expect(screen.getByText("Semantic fit")).toBeInTheDocument();
  });
});

describe("GaugeBar", () => {
  it("renders without crashing for a range of values", () => {
    const { container: c1 } = render(<GaugeBar value={0} />);
    const { container: c2 } = render(<GaugeBar value={100} />);
    expect(c1.querySelector(".gauge-track")).toBeInTheDocument();
    expect(c2.querySelector(".gauge-track")).toBeInTheDocument();
  });
});

describe("RoleBadge", () => {
  it("shows the pulse dot only when pulsing", () => {
    const { container: withPulse } = render(<RoleBadge label="scoring…" pulsing />);
    const { container: withoutPulse } = render(<RoleBadge label="software_engineer" pulsing={false} />);
    expect(withPulse.querySelector(".pulse-dot")).toBeInTheDocument();
    expect(withoutPulse.querySelector(".pulse-dot")).not.toBeInTheDocument();
  });
});

describe("ReportSkeleton", () => {
  it("renders as an aria-busy region so loading is announced", () => {
    render(<ReportSkeleton />);
    expect(screen.getByRole("status", { name: /loading report/i })).toBeInTheDocument();
  });

  it("respects the tileCount and listRows props", () => {
    render(<ReportSkeleton tileCount={4} listRows={2} />);
    const tileRow = screen.getByTestId("tile-row");
    expect(tileRow.children.length).toBe(4);
  });
});
