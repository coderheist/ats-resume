import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { CalendarClock, X } from "lucide-react";
import { formatResetAt, formatResetCountdown } from "../lib/usageLimit";

/**
 * The popup shown the moment a scan is refused for having spent the
 * month's allowance.
 *
 * A modal rather than another inline error box on purpose: this isn't a
 * failure the user can fix by retrying, so it needs to interrupt and
 * answer the only two questions they have -- when do I get more, and
 * how do I get more now. The ErrorBox stays for genuine faults.
 *
 * Focus moves to the dialog on open and returns to whatever was focused
 * before on close, Escape dismisses, and the backdrop is click-to-close,
 * so it behaves like a dialog for keyboard and screen-reader users too.
 */
export function LimitReachedDialog({ detail, onClose }) {
  const dialogRef = useRef(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement;
    dialogRef.current?.focus();

    function onKeyDown(e) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  if (!detail) return null;

  const resetAt = formatResetAt(detail.resets_at);
  const countdown = formatResetCountdown(detail.resets_at);

  return (
    <div className="limit-dialog-backdrop" onClick={onClose}>
      <div
        className="limit-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="limit-dialog-title"
        aria-describedby="limit-dialog-body"
        tabIndex={-1}
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="limit-dialog-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>

        <h2 id="limit-dialog-title">You've used all your scans this month</h2>

        <p id="limit-dialog-body" className="limit-dialog-body">
          {detail.limit != null
            ? `You've run all ${detail.limit} scans included in your current plan.`
            : "Your monthly scan allowance is used up."}{" "}
          Pick up again when it resets, or upgrade for unlimited scans right away.
        </p>

        {resetAt && (
          <div className="limit-dialog-reset">
            <CalendarClock size={16} />
            <div>
              <strong>Resets {countdown}</strong>
              <span>{resetAt} · your local time</span>
            </div>
          </div>
        )}

        <div className="limit-dialog-actions">
          <Link to="/pricing" className="btn-primary" onClick={onClose}>
            See plans
          </Link>
          <button className="btn-outline" style={{ width: "auto" }} onClick={onClose}>
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
