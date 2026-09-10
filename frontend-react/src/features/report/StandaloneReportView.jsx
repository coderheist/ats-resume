import { FileCheck, Layers, Lightbulb, Zap } from "lucide-react";
import { useState } from "react";
import { BulletList } from "../../components/BulletList";
import { DimensionTile } from "../../components/DimensionTile";
import { ErrorBox } from "../../components/ErrorBox";
import { FadeUpSection } from "../../components/FadeUpSection";
import { LimitReachedDialog } from "../../components/LimitReachedDialog";
import { ParsingLoader } from "../../components/ParsingLoader";
import { ReportHero } from "../../components/ReportHero";
import { ReportSkeleton } from "../../components/ReportSkeleton";
import { RoleBadge } from "../../components/RoleBadge";
import { RoleSelect } from "../../components/RoleSelect";
import { SectionHeader } from "../../components/SectionHeader";
import { StepIndicator } from "../../components/StepIndicator";
import { TagList } from "../../components/TagList";
import { TopList } from "../../components/TopList";
import { FileDropzone } from "../upload/FileDropzone";
import { useResumeUpload } from "../upload/useResumeUpload";
import { useRoles } from "./useRoles";
import { useStandaloneReport } from "./useStandaloneReport";

const STEPS = ["Upload resume", "Run analysis", "Report"];

export function StandaloneReportView() {
  const upload = useResumeUpload();
  const { data, suggestions, suggestionsError, status, error, limitDetail, dismissLimit, run, reset } = useStandaloneReport();
  const roles = useRoles();
  const [targetRole, setTargetRole] = useState("");

  const resume = upload.result?.resume;

  function handleRun() {
    if (!resume) return;
    run(resume, targetRole);
  }

  function handleResumeReset() {
    upload.reset();
    reset();
    // The role belongs to the analysis, not the session -- a different
    // resume is a different question, so it starts from the default
    // rather than silently inheriting the last choice.
    setTargetRole("");
  }

  const tiles = data
    ? [
        { label: "Structural completeness", value: data.structural_completeness, accent: false },
        { label: "Action-verb density", value: data.action_verb_density, accent: true },
        { label: "Quantified-metric density", value: data.quantified_metric_density, accent: true },
        { label: "Active voice", value: data.active_voice_score, accent: true },
      ]
    : [];

  // Prefer the human label the roles endpoint already supplies over
  // rendering the raw id ("ai_engineer") at the reader.
  const roleLabel = data
    ? roles.find((r) => r.id === data.inferred_role)?.label || data.inferred_role || "unclassified"
    : "unclassified";

  const emptyGapText =
    data?.role_source === "user_specified"
      ? `Your resume covers every skill expected for ${roleLabel}.`
      : "No ontology gaps for the inferred role.";

  let currentStep = 1;
  if (upload.status === "success" && status === "idle") currentStep = 2;
  if (status === "loading" || status === "success" || status === "error") currentStep = 3;

  return (
    <div>
      <StepIndicator steps={STEPS} current={currentStep} />
      {upload.status === "uploading" && <ParsingLoader text="Analyzing" />}
      {upload.status !== "success" ? (
        <div className="input-card">
          <label>Upload your resume</label>
          <FileDropzone
            status={upload.status}
            error={upload.error}
            fileName={upload.fileName}
            onFileSelected={upload.upload}
            onReset={upload.reset}
          />
        </div>
      ) : (
        <div className="input-card">
          <RoleSelect
            roles={roles}
            value={targetRole}
            onChange={setTargetRole}
            disabled={status === "loading"}
          />
          <div className="resume-loaded-row" style={{ marginBottom: 0 }}>
            <div className="resume-loaded-info">
              <div className="resume-loaded-icon">
                <FileCheck size={15} />
              </div>
              <div>
                <div className="resume-loaded-name">{upload.result.resume.basics?.name || upload.fileName}</div>
                <div className="resume-loaded-sub">Resume loaded</div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button className="btn-link" onClick={handleResumeReset}>
                Use a different resume
              </button>
              <button className="btn-primary" onClick={handleRun} disabled={status === "loading"}>
                Run readiness score
              </button>
              {status === "loading" && <span className="status-text">Scoring…</span>}
              {status === "success" && <span className="status-text">Done</span>}
              {status === "error" && <span className="status-text error">Failed</span>}
            </div>
          </div>
        </div>
      )}

      {status === "error" && <ErrorBox message={error} />}
      {limitDetail && <LimitReachedDialog detail={limitDetail} onClose={dismissLimit} />}
      {status === "loading" && <ReportSkeleton tileCount={4} listRows={3} />}

      {status === "success" && data && (
        <div className="score-card">
          <ReportHero
            mode="readiness"
            score={data.score}
            scoreLabel="/ 100 readiness"
            badge={<RoleBadge label={roleLabel} />}
            // A guessed role and a chosen one deserve different wording:
            // "we think you're a QA engineer" is a claim the report has
            // to stand behind, while "scored against the role you picked"
            // is just describing what was asked for.
            caption={
              data.role_source === "user_specified"
                ? `Scored against the ${roleLabel} role you selected, with no specific job description.`
                : "Based on your current resume, with no specific job description."
            }
          />

          <div className="tile-row">
            {tiles.map((t, i) => (
              <DimensionTile key={t.label} label={t.label} value={t.value} accent={t.accent} delay={i * 0.08} />
            ))}
          </div>

          <FadeUpSection order={0} className="skill-columns">
            <div>
              <SectionHeader icon={Layers} title="Missing sections" tone="gap" />
              {data.missing_sections.length ? (
                <div className="pill-list">
                  {data.missing_sections.map((s) => (
                    <span key={s} className="pill">{s}</span>
                  ))}
                </div>
              ) : (
                <span className="tag-empty">Resume has every core section.</span>
              )}
            </div>
            <div>
              <SectionHeader icon={Zap} title={`Missing skills for ${roleLabel}`} tone="gap" />
              <TopList items={data.missing_ontology_skills} emptyText={emptyGapText}>
                {(visible) => <TagList items={visible} kind="gap" emptyText={emptyGapText} />}
              </TopList>
            </div>
          </FadeUpSection>

          <FadeUpSection order={1}>
            <SectionHeader icon={Lightbulb} title="Top 5 recommendations" />
            {suggestions ? (
              <TopList items={suggestions} emptyText="No recommendations — this resume is in strong shape.">
                {(visible) => <BulletList items={visible} kind="suggestions" emptyText="No recommendations — this resume is in strong shape." />}
              </TopList>
            ) : (
              <p className="tag-empty">
                {suggestionsError ? `Recommendations unavailable: ${suggestionsError}` : "Loading recommendations…"}
              </p>
            )}
          </FadeUpSection>
        </div>
      )}
    </div>
  );
}
