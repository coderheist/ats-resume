import { useCallback, useState } from "react";
import { apiPost } from "../../lib/api";
import { scanLimitDetail } from "../../lib/usageLimit";

/**
 * Two independent backend computations (readiness score vs. ranked
 * suggestions -- see suggestion_engine.py) shown as one result. The
 * suggestions call failing shouldn't take down the whole report: it has
 * its own error state, separate from the main one, so a suggestions
 * outage still leaves the score visible.
 */
export function useStandaloneReport() {
  const [data, setData] = useState(null);
  const [suggestions, setSuggestions] = useState(null);
  const [suggestionsError, setSuggestionsError] = useState(null);
  const [status, setStatus] = useState("idle");
  const [error, setError] = useState(null);
  // See useFullReport: a spent monthly allowance is a dialog, not an
  // inline error, so it needs its own piece of state.
  const [limitDetail, setLimitDetail] = useState(null);

  const run = useCallback(async (resume) => {
    setStatus("loading");
    setError(null);
    setLimitDetail(null);
    setSuggestions(null);
    setSuggestionsError(null);

    try {
      const result = await apiPost("/score/standalone", { resume });
      setData(result);
      setStatus("success");
    } catch (err) {
      setError(err.message);
      setLimitDetail(scanLimitDetail(err));
      setStatus("error");
      return;
    }

    try {
      const suggResult = await apiPost("/score/suggestions", { resume });
      setSuggestions(suggResult.suggestions.map((s) => s.message));
    } catch (err) {
      setSuggestionsError(err.message);
    }
  }, []);

  const dismissLimit = useCallback(() => setLimitDetail(null), []);

  const reset = useCallback(() => {
    setData(null);
    setSuggestions(null);
    setSuggestionsError(null);
    setStatus("idle");
    setError(null);
    setLimitDetail(null);
  }, []);

  return { data, suggestions, suggestionsError, status, error, limitDetail, dismissLimit, run, reset };
}
