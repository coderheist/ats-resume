import { useCallback, useState } from "react";
import { apiPost } from "../../lib/api";
import { scanLimitDetail } from "../../lib/usageLimit";

/**
 * status: "idle" | "loading" | "success" | "error"
 * Not auto-run on mount -- the caller triggers run(resume, jdText)
 * explicitly (e.g. on a button click), so loading state is always tied
 * to a real user action, not an implicit effect.
 */
export function useFullReport() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState(null);
  // Kept separate from `error` because it isn't rendered the same way:
  // a spent allowance opens the limit dialog, everything else is an
  // inline error box (see LimitReachedDialog's docstring).
  const [limitDetail, setLimitDetail] = useState(null);

  const run = useCallback(async (resume, jdText) => {
    setStatus("loading");
    setError(null);
    setLimitDetail(null);
    try {
      const result = await apiPost("/score/full-report", { resume, jd_text: jdText });
      setData(result);
      setStatus("success");
    } catch (err) {
      setError(err.message);
      setLimitDetail(scanLimitDetail(err));
      setStatus("error");
    }
  }, []);

  const dismissLimit = useCallback(() => setLimitDetail(null), []);

  const reset = useCallback(() => {
    setData(null);
    setStatus("idle");
    setError(null);
    setLimitDetail(null);
  }, []);

  return { data, status, error, limitDetail, dismissLimit, run, reset };
}
