import { useState } from "react";
import {
  AlertCircle, AlertTriangle, FileCheck, HelpCircle, Lightbulb, ListChecks, Tags, ThumbsUp,
} from "lucide-react";
import { BulletList } from "../../components/BulletList";
import { BulletRewritePanel } from "../rewrite/BulletRewritePanel";
import { DimensionTile } from "../../components/DimensionTile";
import { ErrorBox } from "../../components/ErrorBox";
import { FadeUpSection } from "../../components/FadeUpSection";
import { KnockoutBanner } from "../../components/KnockoutBanner";
import { LimitReachedDialog } from "../../components/LimitReachedDialog";
import { ParsingLoader } from "../../components/ParsingLoader";
import { ReportHero } from "../../components/ReportHero";
import { RequirementRow } from "../../components/RequirementRow";
import { ReportSkeleton } from "../../components/ReportSkeleton";
import { SectionHeader } from "../../components/SectionHeader";
import { StepIndicator } from "../../components/StepIndicator";
import { TagList } from "../../components/TagList";
import { TopList } from "../../components/TopList";
import { FileDropzone } from "../upload/FileDropzone";
import { useResumeUpload } from "../upload/useResumeUpload";
import { useFullReport } from "./useFullReport";

const STEPS = ["Upload resume", "Add job description", "Report"];

const DIMENSION_LABELS = {
  knockout_requirements: "Knockout requirements",
  technical_skills: "Technical skills",
  semantic_fit: "Semantic fit",
  experience_match: "Experience",
  project_relevance: "Projects",
  education_match: "Education",
  ats_readability: "ATS readability",
};

export function FullReportView() {
  const upload = useResumeUpload();
  const [jdText, setJdText] = useState("");
  const { data, status, error, limitDetail, dismissLimit, run, reset } = useFullReport();
  const [lastAnalyzedKey, setLastAnalyzedKey] = useState(null);

  const resume = upload.result?.resume;
  const currentKey = resume ? `${JSON.stringify(resume)}::${jdText}` : null;
  const isStale = data && currentKey !== lastAnalyzedKey;

  function handleRun() {
    if (!resume || !jdText.trim()) return;
    setLastAnalyzedKey(currentKey);
    run(resume, jdText);
  }

  function handleResumeReset() {
    upload.reset();
    reset();
    setLastAnalyzedKey(null);
  }

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
          <div className="resume-loaded-row">
            <div className="resume-loaded-info">
              <div className="resume-loaded-icon">
                <FileCheck size={15} />
              </div>
              <div>
                <div className="resume-loaded-name">{upload.result.resume.basics?.name || upload.fileName}</div>
                <div className="resume-loaded-sub">Resume loaded</div>
              </div>
            </div>
            <button className="btn-link" onClick={handleResumeReset}>
              Use a different resume
            </button>
          </div>
          <label htmlFor="fr-jd">Job description</label>
          <textarea
            id="fr-jd"
            rows={6}
            placeholder="Paste the job description here…"
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
          />
          <div className="input-row">
            <button className="btn-primary" onClick={handleRun} disabled={status === "loading" || !jdText.trim()}>
              Run full report
            </button>
            {status === "loading" && <span className="status-text">Scoring…</span>}
            {status === "success" && !isStale && <span className="status-text">Done</span>}
            {status === "error" && <span className="status-text error">Failed</span>}
          </div>
        </div>
      )}

      {status === "error" && <ErrorBox message={error} />}
      {limitDetail && <LimitReachedDialog detail={limitDetail} onClose={dismissLimit} />}
      {status === "loading" && <ReportSkeleton tileCount={4} listRows={3} />}

      {status === "success" && data && (
        <div className="score-card">
          {isStale && (
            <div className="stale-banner">
              <span>Your job description has changed since this report was generated.</span>
              <button className="btn-primary" onClick={handleRun}>
                Refresh report
              </button>
            </div>
          )}
          <KnockoutBanner risk={data.knockout_risk} />
          <ReportHero
            mode="match"
            score={data.overall_score}
            scoreLabel="/ 100 overall"
            badge={<span className="classification-pill">{data.classification}</span>}
            caption="Based on your current resume and this job description."
          />

          <div className="tile-row">
            {Object.entries(data.dimensions).map(([key, d], i) => (
              <DimensionTile
                key={key}
                label={DIMENSION_LABELS[key] || key}
                value={d.score}
                accent={key !== "knockout_requirements"}
                delay={i * 0.08}
              />
            ))}
          </div>

          <FadeUpSection order={0}>
            <SectionHeader icon={Tags} title="Keyword coverage" />
            <div className="skill-columns">
              <div>
                <p className="skill-col-title match-title">Exact matches</p>
                <TopList items={data.keyword_categories.exact_matches} emptyText="None.">
                  {(visible) => <TagList items={visible} kind="match" emptyText="None." />}
                </TopList>
              </div>
              <div>
                <p className="skill-col-title gap-title">Missing keywords</p>
                <TopList items={data.keyword_categories.missing_keywords} emptyText="None missing.">
                  {(visible) => <TagList items={visible} kind="gap" emptyText="None missing." />}
                </TopList>
              </div>
              <div>
                <p className="skill-col-title">Semantic matches</p>
                <TopList items={data.keyword_categories.semantic_matches} emptyText="None with the current semantic-matching backend.">
                  {(visible) => <TagList items={visible} kind="warn" emptyText="None." />}
                </TopList>
              </div>
              <div>
                <p className="skill-col-title">Weak (skills-list only)</p>
                <TopList items={data.keyword_categories.weak_keywords} emptyText="None.">
                  {(visible) => <TagList items={visible} kind="warn" emptyText="None." />}
                </TopList>
              </div>
            </div>
          </FadeUpSection>

          <FadeUpSection order={1}>
            <SectionHeader icon={ListChecks} title="Requirement-by-requirement detail" />
            <TopList items={data.requirements} emptyText="No requirements extracted from this job description.">
              {(visible) => (
                <div className="requirement-list">
                  {visible.map((r) => (
                    <RequirementRow key={`${r.kind}-${r.label}`} requirement={r} />
                  ))}
                </div>
              )}
            </TopList>
          </FadeUpSection>

          <FadeUpSection order={2} className="report-columns">
            <div>
              <SectionHeader icon={ThumbsUp} title="Top 5 strengths" tone="match" />
              <TopList items={data.strengths} emptyText="Nothing stood out as a strength yet.">
                {(visible) => <BulletList items={visible} kind="strengths" emptyText="Nothing stood out as a strength yet." />}
              </TopList>
            </div>
            <div>
              <SectionHeader icon={AlertTriangle} title="Top 5 gaps" tone="gap" />
              <TopList items={data.where_you_lack} emptyText="No major gaps found.">
                {(visible) => <BulletList items={visible} kind="gaps" emptyText="No major gaps found." />}
              </TopList>
            </div>
          </FadeUpSection>

          {data.relevance_gaps.length > 0 && (
            <FadeUpSection order={3}>
              <SectionHeader icon={HelpCircle} title="Possibly unrelated to this role" />
              <TopList items={data.relevance_gaps} emptyText="">
                {(visible) => <BulletList items={visible} kind="warnish" emptyText="" />}
              </TopList>
            </FadeUpSection>
          )}

          {data.keyword_stuffing_flags.length > 0 && (
            <FadeUpSection order={4}>
              <SectionHeader icon={AlertCircle} title="Keyword density check" />
              <TopList items={data.keyword_stuffing_flags} emptyText="">
                {(visible) => <BulletList items={visible} kind="warnish" emptyText="" />}
              </TopList>
            </FadeUpSection>
          )}

          <FadeUpSection order={5}>
            <SectionHeader icon={Lightbulb} title="Top 5 recommendations" />
            <TopList items={data.suggestions} emptyText="No recommendations — this resume is in strong shape against this JD.">
              {(visible) => <BulletList items={visible} kind="suggestions" emptyText="No recommendations — this resume is in strong shape against this JD." />}
            </TopList>
          </FadeUpSection>

          {/* Directly after the recommendations, and given the JD, because
              this is the moment the reader has just been told which
              bullets are weak and against what. Sending them elsewhere to
              act on it, with the findings off screen, is how a feature
              goes unused. */}
          <FadeUpSection order={6}>
            <BulletRewritePanel resume={resume} jdText={jdText} />
          </FadeUpSection>
        </div>
      )}
    </div>
  );
}
