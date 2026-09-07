import { Gauge, Target } from "lucide-react";
import { GaugeBar } from "./GaugeBar";
import { ScoreHeadline } from "./ScoreHeadline";

const MODE_CONFIG = {
  match: { icon: Target, eyebrow: "MATCH REPORT", className: "report-hero-match" },
  readiness: { icon: Gauge, eyebrow: "READINESS REPORT", className: "report-hero-readiness" },
};

/**
 * The with-JD and without-JD reports previously shared the exact same
 * plain score-headline treatment, which is part of why the report read
 * as "a simple component" rather than two purpose-built experiences.
 * This gives each mode its own eyebrow label, icon, and accent gradient
 * (green-leaning for a match score, gold-leaning for a readiness score
 * -- consistent with this app's existing two-tone accent language, see
 * Hero.jsx's background glows) so the two reports are visually
 * distinguishable at a glance, not just by their text content.
 */
export function ReportHero({ mode, score, scoreLabel, badge, caption }) {
  const config = MODE_CONFIG[mode];
  const Icon = config.icon;

  return (
    <div className={`report-hero ${config.className}`}>
      <div className="report-hero-eyebrow">
        <Icon size={13} />
        {config.eyebrow}
      </div>
      <ScoreHeadline score={score} label={scoreLabel} badge={badge} />
      {caption && <p className="report-caption">{caption}</p>}
      <GaugeBar value={score} />
    </div>
  );
}
