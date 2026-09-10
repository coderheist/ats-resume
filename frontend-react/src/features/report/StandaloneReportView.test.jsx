import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiGet, apiPost, apiPostFile } from "../../lib/api";
import { StandaloneReportView } from "./StandaloneReportView";

vi.mock("../../lib/api", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPostFile: vi.fn(),
}));

const SAMPLE_ROLES = {
  roles: [
    { id: "ai_engineer", label: "Ai Engineer", expected_skills: ["machine_learning", "python"] },
    { id: "software_engineer", label: "Software Engineer", expected_skills: ["python", "sql"] },
  ],
};

beforeEach(() => {
  // The role picker fetches its options on mount (useRoles). Default it
  // to a successful, empty-ish response so every existing test keeps
  // exercising the path it was written for rather than the
  // list-failed-to-load fallback.
  apiGet.mockResolvedValue(SAMPLE_ROLES);
});

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

    await waitFor(() => expect(screen.getByText("Software Engineer")).toBeInTheDocument());
    expect(screen.getByText("certifications")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Add a metric here.")).toBeInTheDocument());
  });

  it("pops the limit dialog -- not just an error box -- when the month's scans are spent", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockRejectedValue(Object.assign(new Error("You've used all 10 scans included in the Free plan this month."), {
      status: 429,
      detail: {
        error: "scan_limit_reached", message: "You've used all 10 scans included in the Free plan this month.",
        used: 10, limit: 10, resets_at: "2099-10-01T00:00:00Z",
      },
    }));

    // Wrapped in a router only because the dialog links to /pricing --
    // the view itself has no routing of its own.
    render(<MemoryRouter><StandaloneReportView /></MemoryRouter>);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent(/all 10 scans/i);
    expect(dialog).toHaveTextContent(/Resets/);
    expect(screen.getByRole("link", { name: /see plans/i })).toHaveAttribute("href", "/pricing");

    fireEvent.click(screen.getByRole("button", { name: /not now/i }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  });

  it("leaves ordinary failures as an inline error box, with no dialog", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockRejectedValue(Object.assign(new Error("Internal Server Error"), { status: 500, detail: "Internal Server Error" }));

    render(<MemoryRouter><StandaloneReportView /></MemoryRouter>);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText(/Internal Server Error/)).toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("still shows the score if the suggestions call fails independently", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce(SAMPLE_READINESS).mockRejectedValueOnce(new Error("suggestions down"));
    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText("Software Engineer")).toBeInTheDocument());
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
    await waitFor(() => expect(screen.getByText("Software Engineer")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Use a different resume"));
    expect(screen.getByText(/drop your resume here/i)).toBeInTheDocument();
    expect(screen.queryByText("Software Engineer")).not.toBeInTheDocument();
  });
});

describe("StandaloneReportView target role", () => {
  it("sends target_role when one is picked", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce({ ...SAMPLE_READINESS, inferred_role: "ai_engineer", role_source: "user_specified" })
      .mockResolvedValueOnce(SAMPLE_SUGGESTIONS);

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    await waitFor(() => screen.getByRole("combobox"));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "ai_engineer" } });
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/score/standalone", {
        resume: PARSED_RESUME.resume,
        target_role: "ai_engineer",
      }),
    );
  });

  it("omits target_role entirely when inferring", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce(SAMPLE_READINESS).mockResolvedValueOnce(SAMPLE_SUGGESTIONS);

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    // Not `target_role: ""` -- the backend validates any string it is
    // given, so an empty one would 400 and break the default path.
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/score/standalone", { resume: PARSED_RESUME.resume }),
    );
  });

  it("says the role was chosen, not guessed, when the caller picked it", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce({ ...SAMPLE_READINESS, inferred_role: "ai_engineer", role_source: "user_specified" })
      .mockResolvedValueOnce(SAMPLE_SUGGESTIONS);

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText(/role you selected/i)).toBeInTheDocument());
  });

  it("keeps the guessed wording when the role was inferred", async () => {
    apiPostFile.mockResolvedValue(PARSED_RESUME);
    apiPost.mockResolvedValueOnce({ ...SAMPLE_READINESS, role_source: "inferred" })
      .mockResolvedValueOnce(SAMPLE_SUGGESTIONS);

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));
    fireEvent.click(screen.getByText("Run readiness score"));

    await waitFor(() => expect(screen.getByText(/Based on your current resume/i)).toBeInTheDocument());
  });

  it("hides the picker when the role list fails to load", async () => {
    apiGet.mockRejectedValue(new Error("roles down"));
    apiPostFile.mockResolvedValue(PARSED_RESUME);

    render(<StandaloneReportView />);
    uploadResume();
    await waitFor(() => screen.getByText("Run readiness score"));

    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
