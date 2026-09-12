import { useState } from "react";
import { Link } from "react-router-dom";
import { Check, Copy, HelpCircle, Sparkles } from "lucide-react";
import { LimitReachedDialog } from "../../components/LimitReachedDialog";
import { useBulletRewrite } from "./useBulletRewrite";

/**
 * AI bullet rewriting, over the roles in a resume that has already been
 * parsed and scored.
 *
 * Placed inside the report rather than on a page of its own because the
 * report is where a person has just been told which bullets are weak.
 * Sending them somewhere else to act on that, with the findings no longer
 * on screen, is how a feature goes unused.
 *
 * One role at a time, matching how the endpoint meters (one request =
 * one rewrite regardless of bullet count) and how the model writes best
 * -- it can see a role's bullets together and avoid opening four in a row
 * with the same verb.
 */

function roleLabel(job, index) {
  const title = job.position || "Role";
  return job.name ? `${title} — ${job.name}` : `${title} ${index + 1}`;
}

function highlightsOf(job) {
  // Work.highlights is a list of { text } objects (see
  // app/schemas/json_resume.py); Project.highlights is a list of plain
  // strings. Accept either so this component can be pointed at both
  // without the caller having to normalise first.
  return (job.highlights || [])
    .map((h) => (typeof h === "string" ? h : h?.text))
    .filter((t) => t && t.trim());
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="rewrite-copy"
      aria-label={copied ? "Copied" : "Copy rewritten bullet"}
      onClick={async () => {
        try {
          await navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1600);
        } catch {
          // Clipboard permission denied or unavailable (http, older
          // browsers). The text is selectable on screen either way, so
          // this is not worth an error banner.
        }
      }}
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

/**
 * No `signedIn` prop and no useAuth() call here on purpose.
 *
 * It only ever drove one cosmetic sentence, and reading auth context for
 * it coupled both report views to AuthProvider -- which is real coupling
 * for no real benefit, and it broke every report test, none of which have
 * a provider because none of them are about auth.
 *
 * The 401 from the endpoint is the authoritative answer to "is this
 * person signed in", and it arrives exactly when it matters. Until then
 * the panel states the free allowance, which is true either way.
 */
export function BulletRewritePanel({ resume, jdText = null }) {
  const jobs = (resume?.work || []).filter((j) => highlightsOf(j).length > 0);
  const [selected, setSelected] = useState(0);
  const rw = useBulletRewrite();

  if (jobs.length === 0) return null;

  const job = jobs[Math.min(selected, jobs.length - 1)];
  const bullets = highlightsOf(job);
  const busy = rw.status === "loading";

  return (
    <section className="rewrite-panel" aria-labelledby="rewrite-heading">
      <div className="rewrite-header">
        <h3 id="rewrite-heading">
          <Sparkles size={16} aria-hidden="true" /> Rewrite these bullets with AI
        </h3>
        {rw.limit != null && rw.used != null && (
          <p className="rewrite-allowance" role="status">
            {rw.used} of {rw.limit} rewrites used
          </p>
        )}
      </div>

      <p className="rewrite-lede">
        {jdText
          ? "Rewrites are tailored to the job description above, using its wording only where your experience genuinely matches it."
          : "Each bullet is rewritten as an action verb, the specific scope of what you did, and the outcome it produced."}{" "}
        <strong>Numbers are never invented</strong> — where a bullet has none, you'll be asked for the
        one that's missing rather than handed a made-up figure.
      </p>

      {jobs.length > 1 && (
        <div className="rewrite-roles" role="group" aria-label="Choose a role to rewrite">
          {jobs.map((j, i) => (
            <button
              key={`${j.name}-${j.position}-${i}`}
              type="button"
              className={`rewrite-role-btn ${i === selected ? "active" : ""}`}
              aria-pressed={i === selected}
              onClick={() => {
                setSelected(i);
                rw.reset();
              }}
            >
              {roleLabel(j, i)}
            </button>
          ))}
        </div>
      )}

      {rw.status !== "done" && (
        <ul className="rewrite-originals">
          {bullets.map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      )}

      {rw.status === "done" && (
        <ol className="rewrite-results">
          {rw.bullets.map((b, i) => (
            <li key={i} className={b.needs_metric ? "needs-metric" : ""}>
              <p className="rewrite-before">{b.original}</p>
              <div className="rewrite-after">
                <p>{b.rewritten}</p>
                <CopyButton text={b.rewritten} />
              </div>
              {b.needs_metric && (
                <p className="rewrite-hint">
                  <HelpCircle size={13} aria-hidden="true" />
                  <span>
                    <strong>Add a number to finish this one.</strong>{" "}
                    {b.metric_hint || "What changed as a result — how much, how many, or how much faster?"}
                  </span>
                </p>
              )}
            </li>
          ))}
        </ol>
      )}

      {rw.needsAuth && (
        <p className="rewrite-signin">
          <Link to="/login">Sign in</Link> to use AI rewrites. The free plan includes 3 a month.
        </p>
      )}
      {rw.error && (
        <div className="error-box" role="alert">
          {rw.error}
        </div>
      )}

      <div className="rewrite-actions">
        <button
          type="button"
          className="btn-primary"
          disabled={busy}
          onClick={() =>
            rw.rewrite({
              bullets,
              roleTitle: job.position,
              company: job.name,
              jdText,
            })
          }
        >
          {busy
            ? "Rewriting…"
            : rw.status === "done"
              ? "Rewrite again"
              : `Rewrite ${bullets.length} bullet${bullets.length === 1 ? "" : "s"}`}
        </button>
        {!rw.needsAuth && rw.status !== "done" && (
          <span className="rewrite-note">Free accounts include 3 rewrites a month.</span>
        )}
      </div>

      <LimitReachedDialog detail={rw.limitDetail} onClose={rw.dismissLimit} />
    </section>
  );
}
