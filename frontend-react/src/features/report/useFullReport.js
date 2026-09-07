import { useCallback, useState } from "react";
import { apiPost } from "../../lib/api";

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

  const run = useCallback(async (resume, jdText) => {
    setStatus("loading");
    setError(null);
    try {
      const result = await apiPost("/score/full-report", { resume, jd_text: jdText });
      setData(result);
      setStatus("success");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }, []);

  const reset = useCallback(() => {
    setData(null);
    setStatus("idle");
    setError(null);
  }, []);

  return { data, status, error, run, reset };
}
