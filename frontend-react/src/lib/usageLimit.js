/**
 * One place that knows what "you're out of scans" looks like on the
 * wire and how the reset moment is worded.
 *
 * The backend sends the reset instant as an explicit-UTC ISO string
 * (app/core/services/entitlement_service.py's iso_utc) precisely so the
 * browser can render it in the viewer's own timezone -- a user in IST
 * being told their allowance returns "at 00:00 UTC" would be reading
 * about 5:30 the next morning, which is not what they asked. Everything
 * below therefore formats in local time and says so.
 */

/**
 * The 429 body the scoring routes send when the monthly allowance is
 * spent, or null for any other failure. Callers use the null case to
 * mean "this is an ordinary error, show it the ordinary way".
 */
export function scanLimitDetail(err) {
  if (!err || err.status !== 429) return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  return detail.error === "scan_limit_reached" ? detail : null;
}

/** e.g. "1 October 2026, 5:30 am" in the viewer's timezone. */
export function formatResetAt(iso) {
  if (!iso) return null;
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  return when.toLocaleString(undefined, {
    day: "numeric", month: "long", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

/**
 * "in 12 days" / "tomorrow" / "in 3 hours" -- the part people actually
 * act on. Days are counted between calendar dates rather than by
 * dividing the millisecond gap, so a reset at 00:00 tomorrow reads as
 * "tomorrow" at 11pm tonight instead of "in 0 days".
 */
export function formatResetCountdown(iso, now = new Date()) {
  if (!iso) return null;
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  if (when <= now) return "shortly";

  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const days = Math.round((startOfDay(when) - startOfDay(now)) / 86400000);
  if (days >= 2) return `in ${days} days`;
  if (days === 1) return "tomorrow";

  const hours = Math.floor((when - now) / 3600000);
  if (hours >= 2) return `in ${hours} hours`;
  if (hours === 1) return "in an hour";
  return "in under an hour";
}

/** The full sentence shared by the dialog and the usage banners. */
export function resetSentence(iso) {
  const at = formatResetAt(iso);
  if (!at) return null;
  const countdown = formatResetCountdown(iso);
  return countdown ? `Resets ${countdown} — ${at} (your local time).` : `Resets ${at} (your local time).`;
}
