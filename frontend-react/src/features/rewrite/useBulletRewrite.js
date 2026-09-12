import { useState } from "react";
import { ApiError, apiPost } from "../../lib/api";

/**
 * Calls POST /resume/rewrite-bullets for one role's bullets.
 *
 * Three failure modes are kept distinct because the user can act on each
 * one differently, and collapsing them into a single error string is how
 * a person ends up staring at "something went wrong" with no idea whether
 * to sign in, wait, or retry:
 *
 *   - 401  -> `needsAuth`. Rewrites always require an account (scoring
 *             does not), so this is the expected state for a signed-out
 *             visitor, not an error to apologise for.
 *   - 429  -> `limitDetail`, handed straight to LimitReachedDialog, which
 *             reads the allowance and reset time out of the body.
 *   - else -> `error`, a plain message.
 *
 * Allowance counters come back on the success response so the panel can
 * show "4 of 100 used" without a follow-up /auth/me round trip after
 * every single rewrite.
 */
export function useBulletRewrite() {
  const [state, setState] = useState({
    status: "idle", // "idle" | "loading" | "done" | "error"
    bullets: null,
    used: null,
    limit: null,
    error: null,
    limitDetail: null,
    needsAuth: false,
  });

  async function rewrite({ bullets, roleTitle, company, jdText }) {
    setState((s) => ({ ...s, status: "loading", error: null, limitDetail: null, needsAuth: false }));
    try {
      const data = await apiPost("/resume/rewrite-bullets", {
        bullets,
        role_title: roleTitle || null,
        company: company || null,
        jd_text: jdText || null,
      });
      setState({
        status: "done",
        bullets: data.bullets,
        used: data.rewrites_used,
        limit: data.rewrites_limit,
        error: null,
        limitDetail: null,
        needsAuth: false,
      });
    } catch (err) {
      const isApi = err instanceof ApiError;
      setState((s) => ({
        ...s,
        status: "error",
        needsAuth: isApi && err.status === 401,
        // The 429 body is an object carrying used/limit/resets_at; a
        // string detail means the route refused for some other reason.
        limitDetail: isApi && err.status === 429 && typeof err.detail === "object" ? err.detail : null,
        error: isApi && (err.status === 401 || err.status === 429) ? null : err.message,
      }));
    }
  }

  function reset() {
    setState({
      status: "idle", bullets: null, used: null, limit: null,
      error: null, limitDetail: null, needsAuth: false,
    });
  }

  function dismissLimit() {
    setState((s) => ({ ...s, limitDetail: null }));
  }

  return { ...state, rewrite, reset, dismissLimit };
}
