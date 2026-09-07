import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TopList } from "./TopList";

const ITEMS = ["one", "two", "three", "four", "five", "six", "seven"];

describe("TopList", () => {
  it("shows only the top N items by default", () => {
    render(<TopList items={ITEMS} limit={5} emptyText="none">{(visible) => <ul>{visible.map((i) => <li key={i}>{i}</li>)}</ul>}</TopList>);
    expect(screen.getByText("five")).toBeInTheDocument();
    expect(screen.queryByText("six")).not.toBeInTheDocument();
    expect(screen.getByText("Show 2 more")).toBeInTheDocument();
  });

  it("expands to show all items when toggled, and collapses back", () => {
    render(<TopList items={ITEMS} limit={5} emptyText="none">{(visible) => <ul>{visible.map((i) => <li key={i}>{i}</li>)}</ul>}</TopList>);
    fireEvent.click(screen.getByText("Show 2 more"));
    expect(screen.getByText("seven")).toBeInTheDocument();
    expect(screen.getByText("Show less")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Show less"));
    expect(screen.queryByText("seven")).not.toBeInTheDocument();
  });

  it("shows no toggle when the list already fits within the limit", () => {
    render(<TopList items={["a", "b"]} limit={5} emptyText="none">{(visible) => <ul>{visible.map((i) => <li key={i}>{i}</li>)}</ul>}</TopList>);
    expect(screen.queryByText(/show/i)).not.toBeInTheDocument();
  });

  it("shows the empty-state text for an empty list", () => {
    render(<TopList items={[]} limit={5} emptyText="Nothing here.">{() => null}</TopList>);
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
  });
});
