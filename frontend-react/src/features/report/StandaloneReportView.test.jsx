import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { apiPost, apiPostFile } from "../../lib/api";
import { StandaloneReportView } from "./StandaloneReportView";

vi.mock("../../lib/api", () => ({
  apiPost: vi.fn(),
  apiPostFile: vi.fn(),
}));

afterEach(() => {
  vi.resetAllMocks();
});

const PARSED_RESUME = {
  resume: { basics: { name: "Jordan Alvarez" }, work: [] },
  parse_method: "heuristic",
  warnings: [],
};

const SAMPLE_READINESS = {
  score: 65.2,
  inferred_role: "software_engineer",
  structural_completeness: 100,
  action_verb_density: 50,
  quantified_metric_density: 40,
  active_voice_score: 80,
  skill_coverage_score: 60,
  missing_sections: ["certifications"],
  missing_ontology_skills: ["docker"],
  format_issues: [],
  passive_voice_count: 1,
};

const SAMPLE_SUGGESTIONS = {
  mode: "no_jd",
  score: {},
  suggestions: [{ category: "unquantified_bullet", message: "Add a metric here.", target: null, estimated_impact: 0.2, score_context: "match_score" }],
  summary: "1. Add a metric here.",
  summary_source: "template",
};

function uploadResume() {
  const file = new File(["content"], "resume.pdf", { type: "application/pdf" });
  const input = screen.getByTestId("file-input");
  fireEvent.change(input, { target: { files: [file] } });
}

describe("StandaloneReportView", () => {
  it("shows the upload dropzone before a resume is uploaded", () => {
    render(<StandaloneReportView />);
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.queryByText("Run readiness score")).not.toBeInTheDocument();
  });

  it("shows the Run button once a resume is uploaded", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => expect(screen.getByText("Run readiness score")).toBeInTheDocument());
  });

  it("shows the skeleton while the readiness score is loading", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    let resolvePromise;
    apiPost.mockReturnValue(new Promise((resolve) => { resolvePromise = resolve; }));

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    expect(await screen.findByRole("status", { name: /loading report/i })).toBeInTheDocument();
    resolvePromise(SAMPLE_READINESS);
  });

  it("renders the readiness score, tiles, and suggestions on success", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce(SAMPLE_READINESS).mockResolvedValueOnce(SAMPLE_SUGGESTIONS);
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText("software_engineer")).toBeInTheDocument());
    expect(screen.getByText("certifications")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Add a metric here.")).toBeInTheDocument());
  });

  it("still shows the score if the suggestions call fails independently", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce(SAMPLE_READINESS).mockRejectedValueOnce(new Error("suggestions down"));
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText("software_engineer")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/Recommendations unavailable: suggestions down/)).toBeInTheDocument());
  });

  it("renders an error box when the readiness call fails", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockRejectedValue(new Error("500 Internal Server Error"));
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText(/500 Internal Server Error/)).toBeInTheDocument());
  });

  it("'Use a different resume' fully resets both the upload and the report", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce(SAMPLE_READINESS).mockResolvedValueOnce(SAMPLE_SUGGESTIONS);
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));
    await waitFor(() => expect(screen.getByText("software_engineer")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Use a different resume"));
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.queryByText("software_engineer")).not.toBeInTheDocument();
  });
});
