// ============================================================
// Config: API base URL, persisted locally (this is a standalone
// static app run from your own machine, not a claude.ai artifact,
// so localStorage is the normal/correct tool here).
// ============================================================
const API_BASE_KEY = "dossier.apiBase";
const apiBaseInput = document.getElementById("api-base");
const apiStatusDot = document.getElementById("api-status");

function getApiBase() {
  return (apiBaseInput.value || "http://localhost:8000").replace(/\/+$/, "");
}

apiBaseInput.value = localStorage.getItem(API_BASE_KEY) || "http://localhost:8000";
apiBaseInput.addEventListener("change", () => {
  localStorage.setItem(API_BASE_KEY, apiBaseInput.value);
  checkHealth();
});

async function checkHealth() {
  try {
    const res = await fetch(`${getApiBase()}/health`);
    apiStatusDot.classList.toggle("online", res.ok);
    apiStatusDot.title = res.ok ? "Connected" : "Backend responded but not healthy";
  } catch {
    apiStatusDot.classList.remove("online");
    apiStatusDot.title = "Can't reach the backend — is uvicorn running?";
  }
}
checkHealth();
setInterval(checkHealth, 15000);

async function apiPost(path, body) {
  const res = await fetch(`${getApiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data && data.detail ? JSON.stringify(data.detail) : res.statusText;
    throw new Error(`${res.status} ${detail}`);
  }
  return data;
}

async function apiGet(path) {
  const res = await fetch(`${getApiBase()}${path}`);
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(res.statusText);
  return data;
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function errorBox(err) {
  return `<div class="error-box">Request failed: ${escapeHtml(err.message || String(err))}</div>`;
}

// ============================================================
// Tabs
// ============================================================
const tabs = document.querySelectorAll(".tab");
const panels = document.querySelectorAll(".panel");

function activateTab(panelId) {
  tabs.forEach((t) => t.setAttribute("aria-selected", t.dataset.panel === panelId ? "true" : "false"));
  panels.forEach((p) => (p.hidden = p.id !== panelId));
  if (panelId === "panel-pricing" && !pricingLoaded) loadPricing();
}

tabs.forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.panel));
});

// ============================================================
// Resume input: three interchangeable ways to get a JsonResume
// into the same hidden "Paste JSON" textarea, which stays the
// single source of truth the run-* handlers below already read
// from — uploading a file or pasting text just fills it in via
// POST /resume/parse-file or /resume/parse-text instead of
// requiring the person to hand-write JSON.
// ============================================================
function switchResumeMode(prefix, mode) {
  document.querySelectorAll(`.resume-mode-tab[data-resume-prefix="${prefix}"]`).forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.resumeMode === mode);
  });
  document.querySelectorAll(`.resume-mode-panel[data-resume-prefix="${prefix}"]`).forEach((panel) => {
    panel.hidden = panel.dataset.resumeModePanel !== mode;
  });
}

document.querySelectorAll(".resume-mode-tab").forEach((btn) => {
  btn.addEventListener("click", () => switchResumeMode(btn.dataset.resumePrefix, btn.dataset.resumeMode));
});

// ------------------------------------------------------------
// LLM tier selector — Basic (Groq) / Medium (Gemini) / Advanced
// (Claude). Purely a per-request choice sent along with the parse
// call (`tier` field) — this is what lets someone with only a
// GROQ_API_KEY configured actually use it, without also having to
// set LLM_PROVIDER server-side to match. See router.py's Tier enum.
// ------------------------------------------------------------
function getSelectedTier(prefix) {
  const active = document.querySelector(`.tier-btn.active[data-resume-prefix="${prefix}"]`);
  return active ? active.dataset.tier : "basic";
}

document.querySelectorAll(".tier-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    const prefix = btn.dataset.resumePrefix;
    document.querySelectorAll(`.tier-btn[data-resume-prefix="${prefix}"]`).forEach((b) => {
      b.classList.toggle("active", b === btn);
      b.setAttribute("aria-checked", String(b === btn));
    });
  });
});

function resumeParseStatusEl(prefix) {
  return document.getElementById(`${prefix}-parse-status`);
}

function renderResumePreview(prefix, data) {
  const el = document.getElementById(`${prefix}-resume-preview`);
  const r = data.resume || {};
  const name = (r.basics && r.basics.name) || "Unnamed";
  const counts = [
    [(r.work || []).length, "work entries"],
    [(r.education || []).length, "education"],
    [(r.projects || []).length, "projects"],
    [(r.skills || []).length, "skill groups"],
  ];
  const methodLabel = data.parse_method === "llm"
    ? `LLM-parsed${data.provider_used ? ` via ${data.provider_used}` : ""}`
    : "Heuristic parse";
  const warnings = data.warnings || [];
  el.hidden = false;
  el.innerHTML = `
    <div class="resume-preview-head">
      <span class="parse-method-badge ${data.parse_method}">${escapeHtml(methodLabel)}</span>
      <strong>${escapeHtml(name)}</strong>
    </div>
    <div class="resume-preview-counts">
      ${counts.map(([n, label]) => `<span class="preview-count"><b>${n}</b> ${label}</span>`).join("")}
    </div>
    ${warnings.length ? `<ul class="parse-warnings">${warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("")}</ul>` : ""}
    <p class="preview-note">Switch to "Paste JSON" above to review or edit the full parsed result before scoring.</p>`;
}

function applyParsedResume(prefix, data) {
  document.getElementById(`${prefix}-resume`).value = JSON.stringify(data.resume, null, 2);
  renderResumePreview(prefix, data);
}

function parseErrorMessage(res, data) {
  if (!data) return res.statusText;
  if (typeof data.detail === "string") return data.detail;
  if (data.detail) return JSON.stringify(data.detail);
  return res.statusText;
}

async function parseResumeFile(prefix, file) {
  const statusEl = resumeParseStatusEl(prefix);
  statusEl.textContent = "Parsing…";
  statusEl.className = "resume-parse-status";
  try {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("tier", getSelectedTier(prefix));
    const res = await fetch(`${getApiBase()}/resume/parse-file`, { method: "POST", body: formData });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`${res.status} ${parseErrorMessage(res, data)}`);
    applyParsedResume(prefix, data);
    statusEl.textContent = "Parsed — review the summary below.";
  } catch (err) {
    statusEl.textContent = `Parse failed: ${err.message}`;
    statusEl.className = "resume-parse-status err";
  }
}

async function parseResumePastedText(prefix) {
  const statusEl = resumeParseStatusEl(prefix);
  const text = document.getElementById(`${prefix}-paste-input`).value;
  if (!text.trim()) {
    statusEl.textContent = "Paste some resume text first.";
    statusEl.className = "resume-parse-status err";
    return;
  }
  statusEl.textContent = "Parsing…";
  statusEl.className = "resume-parse-status";
  try {
    const data = await apiPost("/resume/parse-text", { text, tier: getSelectedTier(prefix) });
    applyParsedResume(prefix, data);
    statusEl.textContent = "Parsed — review the summary below.";
  } catch (err) {
    statusEl.textContent = `Parse failed: ${err.message}`;
    statusEl.className = "resume-parse-status err";
  }
}

document.querySelectorAll('input[type="file"][id$="-file-input"]').forEach((input) => {
  input.addEventListener("change", () => {
    const prefix = input.id.replace(/-file-input$/, "");
    const file = input.files[0];
    document.getElementById(`${prefix}-file-name`).textContent = file ? file.name : "";
    if (file) parseResumeFile(prefix, file);
  });
});

document.querySelectorAll("[data-resume-parse]").forEach((btn) => {
  btn.addEventListener("click", () => parseResumePastedText(btn.dataset.resumeParse));
});

// ============================================================
// Sample data — matches app/schemas/json_resume.py exactly
// ============================================================
const SAMPLE_RESUME = {
  schema_version: "v1.0.0",
  basics: {
    name: "Jordan Alvarez",
    label: "Backend Engineer",
    email: "jordan.alvarez@example.com",
    summary: "Backend engineer focused on scalable systems and developer tooling.",
    location: "Denver, CO",
  },
  work: [
    {
      name: "Northwind Data",
      position: "Software Engineer",
      start_date: "2021-03",
      end_date: null,
      highlights: [
        { text: "Led migration of the ingestion pipeline to a queue-based architecture, cutting processing latency 42%." },
        { text: "Scaled the primary Postgres cluster to handle 12,000 concurrent connections during peak load." },
        { text: "Built an internal React dashboard for on-call engineers to trace failed jobs." },
      ],
    },
    {
      name: "Fieldstone Labs",
      position: "Junior Software Engineer",
      start_date: "2019-06",
      end_date: "2021-02",
      highlights: [
        { text: "Implemented automated test coverage for the billing service, catching 15 regressions pre-release." },
      ],
    },
  ],
  education: [
    { institution: "Colorado State University", area: "Computer Science", study_type: "Bachelor", end_date: "2019-05" },
  ],
  skills: [
    { name: "Backend", keywords: ["software engineering", "python", "postgresql", "react"] },
    { name: "Infrastructure", keywords: ["docker", "aws"] },
  ],
  projects: [],
};

const SAMPLE_JD = `We're hiring a Senior Software Engineer to join our backend platform team.

Requirements:
- 5+ years of professional software development experience
- Strong experience with React and PostgreSQL
- Experience scaling backend systems under real production load
- Familiarity with AWS and containerized deployments

You'll work closely with our data and infrastructure teams to build reliable, well-tested services.`;

const SAMPLE_JD_BIASED = `We need a dominant, aggressive self-starter who isn't afraid to dominate the market. Our ideal candidate is fiercely competitive, assertive in meetings, and driven to outperform everyone around them. Only fearless, superior talent need apply — we want a rockstar who is independent and thrives in high-pressure, winner-takes-all environments.`;

const SAMPLE_JD_NEUTRAL = `We're looking for a collaborative engineer to join our supportive, team-oriented backend group. You'll work cooperatively with designers and PMs, mentoring junior teammates and contributing to an inclusive, dependable engineering culture. We value clear communication and helpful code review as much as technical depth.`;

document.querySelectorAll("[data-sample]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const target = document.getElementById(btn.dataset.target);
    const kind = btn.dataset.sample;
    if (kind === "resume") {
      target.value = JSON.stringify(SAMPLE_RESUME, null, 2);
      const prefix = btn.dataset.target.replace(/-resume$/, "");
      switchResumeMode(prefix, "json");
      const preview = document.getElementById(`${prefix}-resume-preview`);
      if (preview) preview.hidden = true;
    } else if (kind === "jd") target.value = SAMPLE_JD;
    else if (kind === "jd-biased") target.value = SAMPLE_JD_BIASED;
    else if (kind === "jd-neutral") target.value = SAMPLE_JD_NEUTRAL;
  });
});

// Pre-fill on load so the console isn't empty on first open.
document.getElementById("jd-match-resume").value = JSON.stringify(SAMPLE_RESUME, null, 2);
document.getElementById("jd-match-jd").value = SAMPLE_JD;
document.getElementById("standalone-resume").value = JSON.stringify(SAMPLE_RESUME, null, 2);
document.getElementById("bias-jd").value = SAMPLE_JD_BIASED;

function parseResumeInput(raw) {
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`Resume JSON didn't parse: ${e.message}`);
  }
}

// ============================================================
// Signature component: the weighted-contribution formula chart.
// Segment WIDTH = the formula's fixed weight; fill HEIGHT = that
// component's subscore. Renders the actual mechanism, not a
// generic gauge.
// ============================================================
function formulaChart(components) {
  // components: [{ label, weight, value }]
  const bars = components
    .map(
      (c) => `
      <div class="formula-segment" style="flex: ${c.weight} 0 0%;">
        <div class="formula-fill" data-target="${c.value}"></div>
      </div>`
    )
    .join("");
  const labels = components
    .map(
      (c) => `
      <div class="formula-segment-label" style="flex: ${c.weight} 0 0%;">
        <b>${c.value.toFixed(1)}</b>${c.label}<br/>(weight ${c.weight})
      </div>`
    )
    .join("");
  return `
    <div class="formula-chart">
      <p class="formula-caption">score = ${components.map((c) => `${c.weight}×${c.short}`).join(" + ")}</p>
      <div class="formula-bars">${bars}</div>
      <div class="formula-segment-labels">${labels}</div>
    </div>`;
}

function animateFormulaFills(container) {
  requestAnimationFrame(() => {
    container.querySelectorAll(".formula-fill").forEach((el) => {
      const target = parseFloat(el.dataset.target) || 0;
      requestAnimationFrame(() => (el.style.height = `${Math.max(target, 1)}%`));
    });
  });
}

function tagList(items, kind, emptyText) {
  if (!items || items.length === 0) return `<span class="tag-empty">${emptyText}</span>`;
  return `<div class="tag-list">${items.map((s) => `<span class="tag ${kind}">${escapeHtml(s)}</span>`).join("")}</div>`;
}

// ============================================================
// JD Match
// ============================================================
document.getElementById("run-jd-match").addEventListener("click", async () => {
  const statusEl = document.getElementById("jd-match-status");
  const resultEl = document.getElementById("jd-match-result");
  statusEl.textContent = "Scoring…";
  statusEl.className = "inline-status";
  resultEl.innerHTML = "";
  try {
    const resume = parseResumeInput(document.getElementById("jd-match-resume").value);
    const jd_text = document.getElementById("jd-match-jd").value;
    const data = await apiPost("/score/jd-match", { resume, jd_text });
    statusEl.textContent = "Done";

    resultEl.innerHTML = `
      <div class="score-card">
        <div class="score-headline">
          <span class="score-number">${data.score.toFixed(1)}</span>
          <span class="score-label">/ 100 final score</span>
          <span class="seniority-badge" title="Detected from the JD text; shifts the weights below">${data.seniority_detected} profile</span>
        </div>
        ${formulaChart([
          { label: "Semantic fit", short: "semantic", weight: data.weights_used.semantic, value: data.breakdown.semantic_fit },
          { label: "Skill match", short: "skill", weight: data.weights_used.skill, value: data.breakdown.skill_match },
          { label: "Experience match", short: "experience", weight: data.weights_used.experience, value: data.breakdown.experience_match },
        ])}
        <div class="skill-columns">
          <div>
            <p class="skill-col-title match-title">Matched skills</p>
            ${tagList(data.matched_skills, "match", "No overlapping skills found.")}
          </div>
          <div>
            <p class="skill-col-title gap-title">Skill gaps</p>
            ${tagList(data.skill_gaps, "gap", "No gaps against the JD's requested skills.")}
          </div>
        </div>
        <div class="detail-row">
          <span>Required experience: <strong>${data.experience.required_years ?? "not specified in JD"}</strong>${data.experience.required_years ? " yrs" : ""}</span>
          <span>Candidate experience: <strong>${data.experience.candidate_years}</strong> yrs</span>
        </div>
        ${data.skill_gaps.length ? `<button class="link-btn gap-resolution-cta" id="jd-match-resolve-gaps">Resolve gaps conversationally →</button>` : ""}
      </div>`;
    animateFormulaFills(resultEl);

    const resolveBtn = document.getElementById("jd-match-resolve-gaps");
    if (resolveBtn) {
      resolveBtn.addEventListener("click", () => {
        gapResolutionState.resume = resume;
        gapResolutionState.jd_text = jd_text;
        activateTab("panel-gap-resolution");
        startGapResolutionLoop();
      });
    }
  } catch (err) {
    statusEl.textContent = "Failed";
    statusEl.className = "inline-status err";
    resultEl.innerHTML = errorBox(err);
  }
});

// ============================================================
// Standalone readiness
// ============================================================
document.getElementById("run-standalone").addEventListener("click", async () => {
  const statusEl = document.getElementById("standalone-status");
  const resultEl = document.getElementById("standalone-result");
  statusEl.textContent = "Scoring…";
  statusEl.className = "inline-status";
  resultEl.innerHTML = "";
  try {
    const resume = parseResumeInput(document.getElementById("standalone-resume").value);
    const data = await apiPost("/score/standalone", { resume });
    statusEl.textContent = "Done";

    resultEl.innerHTML = `
      <div class="score-card">
        <div class="score-headline">
          <span class="score-number">${data.score.toFixed(1)}</span>
          <span class="score-label">/ 100 readiness · inferred role: <strong>${data.inferred_role || "unclassified"}</strong></span>
        </div>
        <div class="readiness-grid">
          <div class="readiness-tile">
            <div class="tile-value">${data.structural_completeness.toFixed(0)}%</div>
            <div class="tile-label">Structural completeness</div>
          </div>
          <div class="readiness-tile">
            <div class="tile-value">${data.action_verb_density.toFixed(0)}%</div>
            <div class="tile-label">Action-verb density</div>
          </div>
          <div class="readiness-tile">
            <div class="tile-value">${data.quantified_metric_density.toFixed(0)}%</div>
            <div class="tile-label">Quantified-metric density</div>
          </div>
        </div>
        <div class="skill-columns">
          <div>
            <p class="skill-col-title gap-title">Missing sections</p>
            ${
              data.missing_sections.length
                ? `<div class="pill-list">${data.missing_sections.map((s) => `<span class="pill">${escapeHtml(s)}</span>`).join("")}</div>`
                : `<span class="tag-empty">Resume has every core section.</span>`
            }
          </div>
          <div>
            <p class="skill-col-title gap-title">Missing skills for this role</p>
            ${tagList(data.missing_ontology_skills, "gap", "No ontology gaps for the inferred role.")}
          </div>
        </div>
      </div>`;
  } catch (err) {
    statusEl.textContent = "Failed";
    statusEl.className = "inline-status err";
    resultEl.innerHTML = errorBox(err);
  }
});

// ============================================================
// Bias audit — inline markup + margin-note rewrites
// ============================================================
function markupBiasedText(jdText, agenticTerms, communalTerms, ageistTerms = []) {
  let html = escapeHtml(jdText);
  const wrap = (term, cls) => {
    const re = new RegExp(`\\b(${term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})\\b`, "gi");
    html = html.replace(re, `<mark class="${cls}">$1</mark>`);
  };
  agenticTerms.forEach((t) => wrap(t, "agentic"));
  communalTerms.forEach((t) => wrap(t, "communal"));
  ageistTerms.forEach((t) => wrap(t, "ageist"));
  return html;
}

document.getElementById("run-bias-audit").addEventListener("click", async () => {
  const statusEl = document.getElementById("bias-audit-status");
  const resultEl = document.getElementById("bias-audit-result");
  statusEl.textContent = "Scanning…";
  statusEl.className = "inline-status";
  resultEl.innerHTML = "";
  try {
    const jd_text = document.getElementById("bias-jd").value;
    const data = await apiPost("/bias-audit/jd", { jd_text });
    statusEl.textContent = "Done";

    const rewrites = Object.entries(data.suggested_rewrites || {});
    resultEl.innerHTML = `
      <div class="bias-summary">
        <div class="bias-stat ${data.flagged ? "flagged" : "clear"}">
          <div class="stat-value">${data.flagged ? "Flagged" : "Clear"}</div>
          <div class="stat-label">skew ${data.skew >= 0 ? "+" : ""}${data.skew} (threshold 3) or any ageist phrasing</div>
        </div>
        <div class="bias-stat">
          <div class="stat-value">${data.agentic_count}</div>
          <div class="stat-label">agentic-coded terms</div>
        </div>
        <div class="bias-stat">
          <div class="stat-value">${data.communal_count}</div>
          <div class="stat-label">communal-coded terms</div>
        </div>
        <div class="bias-stat ${data.ageist_terms_found.length ? "flagged" : ""}">
          <div class="stat-value">${data.ageist_terms_found.length}</div>
          <div class="stat-label">ageist phrases — non-scoring flag only, never fed into the candidate's match score</div>
        </div>
      </div>
      <div class="markup-text">${markupBiasedText(jd_text, data.agentic_terms_found, data.communal_terms_found, data.ageist_terms_found)}</div>
      ${
        rewrites.length
          ? `<div class="rewrite-list">
              <p class="skill-col-title gap-title">Suggested neutral rewrites</p>
              ${rewrites
                .map(([from, to]) => `<div class="rewrite-row"><span class="from">${escapeHtml(from)}</span><span class="arrow">→</span><span class="to">${escapeHtml(to)}</span></div>`)
                .join("")}
            </div>`
          : ""
      }
      <p class="draft-note" style="margin-top:16px;">${escapeHtml(data.disclaimer)}</p>`;
  } catch (err) {
    statusEl.textContent = "Failed";
    statusEl.className = "inline-status err";
    resultEl.innerHTML = errorBox(err);
  }
});

// ============================================================
// Voice editor — real multi-turn state machine against /voice/turn.
// The server accumulates slots per session_id itself (see
// app/api/routes/voice.py's in-memory _SESSIONS), so each turn only
// sends the field the user just answered.
// ============================================================
const SLOT_LABELS = { scope: "Scope", scale: "Scale", outcome_metric: "Outcome metric" };

let voiceSessionId = null;
let voiceCurrentSlot = null; // which slot the next answer maps to
let voiceFilledSlots = {};

const transcriptEl = document.getElementById("voice-transcript");
const voiceForm = document.getElementById("voice-form");
const voiceAnswerInput = document.getElementById("voice-answer");
const voiceSendBtn = document.getElementById("voice-send");
const voiceSlotsEl = document.getElementById("voice-slots");
const voiceGenerateBlock = document.getElementById("voice-generate-block");
const voiceDraftBullet = document.getElementById("voice-draft-bullet");

function addBubble(kind, text) {
  const div = document.createElement("div");
  div.className = `bubble ${kind}`;
  div.textContent = text;
  transcriptEl.appendChild(div);
  transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function renderSlots() {
  const entries = Object.entries(voiceFilledSlots);
  if (entries.length === 0) {
    voiceSlotsEl.innerHTML = `<div class="slot-empty">Nothing captured yet.</div>`;
    return;
  }
  voiceSlotsEl.innerHTML = entries
    .map(([k, v]) => `<div class="slot-row"><dt>${SLOT_LABELS[k] || k}</dt><dd>${escapeHtml(v)}</dd></div>`)
    .join("");
}

function templatePreviewBullet(slots) {
  // Deliberately simple and clearly non-AI — see the disclaimer in the
  // panel copy. Real generation happens via append_work_highlight,
  // called by the live conversational agent (voice_system_prompt.py),
  // not here.
  const scope = slots.scope || "the system";
  const outcome = slots.outcome_metric || slots.scale;
  return outcome
    ? `Improved ${scope}, resulting in ${outcome}.`
    : `Worked on ${scope}.`;
}

async function startVoiceSession() {
  voiceSessionId = crypto.randomUUID ? crypto.randomUUID() : `sess_${Date.now()}`;
  voiceFilledSlots = {};
  document.getElementById("voice-session-id").textContent = voiceSessionId.slice(0, 8);
  transcriptEl.innerHTML = "";
  voiceGenerateBlock.hidden = true;
  renderSlots();
  addBubble("system", "New session started");
  await sendVoiceTurn({}, "(session start)");
}

async function sendVoiceTurn(extractedSlots, transcriptText) {
  voiceAnswerInput.disabled = true;
  voiceSendBtn.disabled = true;
  try {
    const data = await apiPost("/voice/turn", {
      session_id: voiceSessionId,
      transcript: transcriptText,
      extracted_slots: extractedSlots,
    });

    if (data.action === "ask_clarifying_question") {
      voiceCurrentSlot = data.missing_slot;
      addBubble("agent", data.question);
      voiceAnswerInput.placeholder = `Answer for: ${SLOT_LABELS[voiceCurrentSlot] || voiceCurrentSlot}`;
      voiceAnswerInput.disabled = false;
      voiceSendBtn.disabled = false;
      voiceAnswerInput.focus();
    } else if (data.action === "generate_highlight") {
      voiceFilledSlots = data.filled_slots;
      renderSlots();
      addBubble("system", "Enough detail captured — ready to generate.");
      voiceGenerateBlock.hidden = false;
      voiceDraftBullet.textContent = templatePreviewBullet(voiceFilledSlots);
      voiceAnswerInput.placeholder = "Session complete — start a new one to continue";
    }
  } catch (err) {
    addBubble("system", `Request failed: ${err.message}`);
    voiceAnswerInput.disabled = false;
    voiceSendBtn.disabled = false;
  }
}

voiceForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = voiceAnswerInput.value.trim();
  if (!text || !voiceCurrentSlot) return;
  addBubble("user", text);
  voiceFilledSlots[voiceCurrentSlot] = text;
  renderSlots();
  voiceAnswerInput.value = "";
  await sendVoiceTurn({ [voiceCurrentSlot]: text }, text);
});

document.getElementById("voice-restart").addEventListener("click", startVoiceSession);

// ============================================================
// Pricing
// ============================================================
let pricingLoaded = false;

function formatPrice(monthly) {
  if (monthly === 0) return `<span class="free">Free</span>`;
  if (monthly === null || monthly === undefined) return "—";
  return `$${monthly}/mo`;
}

async function loadPricing() {
  const resultEl = document.getElementById("pricing-result");
  resultEl.innerHTML = `<p class="loading-note">Loading tiers…</p>`;
  try {
    const data = await apiGet("/billing/tiers");
    pricingLoaded = true;
    const groups = Object.entries(data)
      .map(([groupName, tiers]) => {
        const rows = Object.values(tiers)
          .map(
            (t) => `
            <div class="tier-row">
              <div class="tier-name">${escapeHtml(t.name)}</div>
              <div class="tier-price">${formatPrice(t.monthly_price_usd)}</div>
              <div class="tier-features">${t.features.map((f) => `<span class="tier-feature">${escapeHtml(f.replace(/_/g, " "))}</span>`).join("")}</div>
            </div>`
          )
          .join("");
        return `
          <div class="tier-group">
            <p class="tier-group-title">${escapeHtml(groupName)}</p>
            <div class="tier-rows">${rows}</div>
          </div>`;
      })
      .join("");
    resultEl.innerHTML = groups;
  } catch (err) {
    resultEl.innerHTML = errorBox(err);
  }
}

// ============================================================
// Gap resolution loop — POST /voice/gap-prompt + /voice/gap-answer.
// Mirrors the voice-editor transcript pattern above, but each "turn" is
// driven by a scoring gap rather than a fixed slot list: ask about the
// highest-priority missing skill, patch the answer into the resume,
// rescore, show the delta, then ask about the next gap (if any).
//
// gapResolutionState.resume/jd_text are set either by the "Resolve gaps
// conversationally" handoff button on the JD Match panel, or by this
// panel's own "Load sample pair" button.
// ============================================================
const gapResolutionState = { resume: null, jd_text: null };

const GAP_RESOLUTION_SAMPLE_JD = `${SAMPLE_JD}\n- Some hands-on machine learning experience is required.`;

const gapTranscriptEl = document.getElementById("gap-resolution-transcript");
const gapForm = document.getElementById("gap-resolution-form");
const gapAnswerInput = document.getElementById("gap-resolution-answer");
const gapSendBtn = document.getElementById("gap-resolution-send");
const gapScoreBlock = document.getElementById("gap-resolution-score-block");
const gapSourceLabel = document.getElementById("gap-resolution-source-label");

function addGapBubble(kind, text) {
  const div = document.createElement("div");
  div.className = `bubble ${kind}`;
  div.textContent = text;
  gapTranscriptEl.appendChild(div);
  gapTranscriptEl.scrollTop = gapTranscriptEl.scrollHeight;
}

function renderGapScore(scoreData, deltaFromPrevious) {
  const deltaHtml =
    deltaFromPrevious !== undefined
      ? `<div class="detail-row"><span>Change this turn: <strong class="${deltaFromPrevious >= 0 ? "match-title" : "gap-title"}">${deltaFromPrevious >= 0 ? "+" : ""}${(deltaFromPrevious * 100).toFixed(1)} pts</strong></span></div>`
      : "";
  gapScoreBlock.innerHTML = `
    <div class="score-headline">
      <span class="score-number">${scoreData.score.toFixed(1)}</span>
      <span class="score-label">/ 100</span>
      <span class="seniority-badge">${scoreData.seniority_detected} profile</span>
    </div>
    ${deltaHtml}
    <p class="skill-col-title gap-title" style="margin-top:14px;">Remaining gaps</p>
    ${tagList(scoreData.skill_gaps, "gap", "None — every recognized JD skill is covered.")}
  `;
}

async function askNextGap() {
  gapAnswerInput.disabled = true;
  gapSendBtn.disabled = true;
  try {
    const data = await apiPost("/voice/gap-prompt", {
      resume: gapResolutionState.resume,
      jd_text: gapResolutionState.jd_text,
    });

    if (data.done) {
      renderGapScore(data.score);
      addGapBubble("system", "No more gaps against this JD — resume fully covers the recognized skills.");
      gapAnswerInput.placeholder = "Nothing left to resolve";
      return;
    }

    renderGapScore(data.current_score);
    addGapBubble("agent", data.prompt);
    gapAnswerInput.placeholder = `Answer about: ${data.target_skill}`;
    gapAnswerInput.disabled = false;
    gapSendBtn.disabled = false;
    gapAnswerInput.focus();
  } catch (err) {
    addGapBubble("system", `Request failed: ${err.message}`);
  }
}

async function startGapResolutionLoop() {
  if (!gapResolutionState.resume || !gapResolutionState.jd_text) return;
  gapTranscriptEl.innerHTML = "";
  gapScoreBlock.innerHTML = `<p class="slot-empty">Scoring…</p>`;
  gapSourceLabel.textContent = `${gapResolutionState.resume.basics?.name || "Resume"} vs. loaded JD`;
  addGapBubble("system", "Scan started — asking about the highest-priority gap first.");
  await askNextGap();
}

gapForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = gapAnswerInput.value.trim();
  if (!text) return;
  addGapBubble("user", text);
  gapAnswerInput.value = "";
  gapAnswerInput.disabled = true;
  gapSendBtn.disabled = true;

  try {
    const data = await apiPost("/voice/gap-answer", {
      resume: gapResolutionState.resume,
      jd_text: gapResolutionState.jd_text,
      answer_text: text,
    });
    gapResolutionState.resume = data.updated_resume;
    renderGapScore(data.after, data.score_delta);
    await askNextGap();
  } catch (err) {
    addGapBubble("system", `Request failed: ${err.message}`);
    gapAnswerInput.disabled = false;
    gapSendBtn.disabled = false;
  }
});

document.getElementById("gap-resolution-load-sample").addEventListener("click", () => {
  gapResolutionState.resume = JSON.parse(JSON.stringify(SAMPLE_RESUME));
  gapResolutionState.jd_text = GAP_RESOLUTION_SAMPLE_JD;
  startGapResolutionLoop();
});
