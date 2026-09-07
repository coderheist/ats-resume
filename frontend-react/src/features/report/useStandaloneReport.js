import { useCallback, useState } from "react";
import { apiPost } from "../../lib/api";

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

  const run = useCallback(async (resume) => {
    setStatus("loading");
    setError(null);
    setSuggestions(null);
    setSuggestionsError(null);

    try {
      const result = await apiPost("/score/standalone", { resume });
      setData(result);
      setStatus("success");
    } catch (err) {
      setError(err.message);
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

  const reset = useCallback(() => {
    setData(null);
    setSuggestions(null);
    setSuggestionsError(null);
    setStatus("idle");
    setError(null);
  }, []);

  return { data, suggestions, suggestionsError, status, error, run, reset };
}
