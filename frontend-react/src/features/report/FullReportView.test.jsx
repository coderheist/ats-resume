import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost, apiPostFile } from "../../lib/api";
import { FullReportView } from "./FullReportView";

vi.mock("../../lib/api", () => ({
  apiPost: vi.fn(),
  apiPostFile: vi.fn(),
}));

afterEach(() => {
  vi.resetAllMocks();
});

const PARSED_RESUME = {
  resume: { basics: { name: "Jordan Alvarez" }, work: [{ name: "Acme", position: "Engineer", highlights: [] }] },
  parse_method: "heuristic",
  warnings: [],
};

const SAMPLE_REPORT = {
  overall_score: 78.4,
  classification: "Good Match",
  knockout_risk: "LOW",
  dimensions: {
    knockout_requirements: { score: 100, weight: 0.3 },
    technical_skills: { score: 80, weight: 0.2 },
    semantic_fit: { score: 60, weight: 0.2 },
    experience_match: { score: 90, weight: 0.1 },
    project_relevance: { score: 50, weight: 0.1 },
    education_match: { score: 100, weight: 0.05 },
    ats_readability: { score: 100, weight: 0.05 },
  },
  keyword_categories: { exact_matches: ["python"], semantic_matches: [], missing_keywords: ["aws"], weak_keywords: [] },
  requirements: [
    { label: "python", kind: "skill", tier: "important", status: "matched", evidence_strength: "strong",
      match_type: "exact", confidence: "high", evidence_location: "Work Experience: Engineer", detail: "Demonstrated." },
  ],
  strengths: ["Strong Python evidence."],
  where_you_lack: ["Missing AWS."],
  relevance_gaps: [],
  keyword_stuffing_flags: [],
  suggestions: ["Add AWS evidence to a bullet."],
  top_reasons_for_score: ["Missing AWS keyword."],
  top_improvements_needed: ["Add AWS evidence to a bullet, ranked #1 by impact."],
};

function uploadResume() {
  const file = new File(["content"], "resume.pdf", { type: "application/pdf" });
  const input = screen.getByTestId("file-input");
  fireEvent.change(input, { target: { files: [file] } });
}

describe("FullReportView", () => {
  it("shows the upload dropzone before a resume is uploaded, no JD field yet", () => {
    render(<FullReportView />);
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Job description")).not.toBeInTheDocument();
  });

  it("shows the JD field and Run button once a resume is uploaded", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => expect(screen.getByLabelText("Job description")).toBeInTheDocument());
    expect(screen.getByText("Jordan Alvarez", { exact: false })).toBeInTheDocument();
  });

  it("shows the skeleton while the report is loading", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    let resolvePromise;
    apiPost.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));

    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some JD text" } });
    fireEvent.click(screen.getByText("Run full report"));

    expect(await screen.findByRole("status", { name: /loading report/i })).toBeInTheDocument();
    resolvePromise(SAMPLE_REPORT);
  });

  it("renders the report on success", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValue(SAMPLE_REPORT);
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some JD text" } });
    fireEvent.click(screen.getByText("Run full report"));

    await waitFor(() => expect(screen.getByText("Good Match")).toBeInTheDocument());
    expect(screen.getByText(/Knockout Risk: LOW/)).toBeInTheDocument();
    expect(screen.getByText("Add AWS evidence to a bullet.")).toBeInTheDocument();
    expect(screen.getByText("Missing AWS.")).toBeInTheDocument();
  });

  it("renders an error box when the scoring API call fails", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockRejectedValue(new Error("500 Internal Server Error"));
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some JD text" } });
    fireEvent.click(screen.getByText("Run full report"));

    await waitFor(() => expect(screen.getByText(/500 Internal Server Error/)).toBeInTheDocument());
  });

  it("Run full report is disabled until the JD field has text", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    expect(screen.getByText("Run full report")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some JD text" } });
    expect(screen.getByText("Run full report")).not.toBeDisabled();
  });

  it("shows the stale banner when the JD text changes after a report exists, and refreshing re-runs", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValue(SAMPLE_REPORT);
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "First JD" } });
    fireEvent.click(screen.getByText("Run full report"));
    await waitFor(() => expect(screen.getByText("Good Match")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "A different JD" } });
    expect(await screen.findByText(/job description has changed/i)).toBeInTheDocument();

    apiPost.mockClear();
    fireEvent.click(screen.getByText("Refresh report"));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/score/full-report", expect.objectContaining({ jd_text: "A different JD" })));
  });

  it("'Use a different resume' fully resets both the upload and the report", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValue(SAMPLE_REPORT);
    render(<FullReportView />);
    uploadResume();
    await waitFor(() => screen.getByLabelText("Job description"));
    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some JD" } });
    fireEvent.click(screen.getByText("Run full report"));
    await waitFor(() => expect(screen.getByText("Good Match")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Use a different resume"));
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.queryByText("Good Match")).not.toBeInTheDocument();
  });
});
