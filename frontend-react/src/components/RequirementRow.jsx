export function RequirementRow({ requirement }) {
  const r = requirement;
  return (
    <div className={`requirement-row status-${r.status}`}>
      <span className="requirement-label">{r.label}</span>
      <span className="requirement-meta">
        {r.kind} · {r.tier} · {r.status.replace(/_/g, " ")} · {r.evidence_strength.replace(/_/g, " ")} evidence ·{" "}
        {r.match_type} match · {r.confidence} confidence
      </span>
      <span className="requirement-detail">
        {r.detail}
        {r.evidence_location ? ` — ${r.evidence_location}` : ""}
      </span>
    </div>
  );
}
