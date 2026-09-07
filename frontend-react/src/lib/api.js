// In dev, Vite's proxy (see vite.config.js) forwards /score, /resume,
// etc. straight to the FastAPI backend on :8000, so this can stay
// relative (empty base) by default. Set VITE_API_BASE_URL to point at a
// different backend (e.g. a deployed one) for the production build.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  /**
   * `detail` carries FastAPI's error body when it was an object rather
   * than a string -- currently the 429 from the scoring routes, which
   * ships the usage numbers and the reset timestamp the limit dialog
   * needs (see app/api/routes/scan.py's _enforce_entitlement). Callers
   * that only want something to print keep using `.message`.
   */
  constructor(message, status, detail = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Turn a non-OK response into an ApiError. Shared by every request
 * helper below so they can't drift on how an error body is unwrapped:
 * a `detail` string is the message as-is, a `detail` object keeps its
 * `message` readable and hands the rest to the caller, and anything
 * else falls back to the raw JSON (or statusText for non-JSON bodies).
 */
async function _toApiError(res) {
  let detail = null;
  let message = res.statusText;
  try {
    const data = await res.json();
    detail = data.detail ?? null;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object" && typeof detail.message === "string") message = detail.message;
    else message = JSON.stringify(detail ?? data);
  } catch {
    // response wasn't JSON -- keep statusText
  }
  return new ApiError(message, res.status, detail);
}

// A module-level "token getter" rather than threading auth through
// every call site: AuthProvider (lib/authContext.jsx) registers this
// once, on mount, with a function that returns the current Firebase ID
// token (or null when signed out / not configured) -- every request
// below calls it fresh each time, so a token refresh or sign-out is
// picked up on the very next request without every hook/component that
// calls apiPost needing to know auth exists at all.
let _getIdToken = async () => null;

export function setAuthTokenProvider(fn) {
  _getIdToken = fn;
}

async function _authHeaders() {
  const token = await _getIdToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiPost(path, body) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(await _authHeaders()) },
      body: JSON.stringify(body),
    });
  } catch (networkErr) {
    throw new ApiError(
      `Couldn't reach the API at ${path}. Is the backend running? (${networkErr.message})`,
      0
    );
  }

  if (!res.ok) throw await _toApiError(res);

  return res.json();
}

export async function apiGet(path) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { headers: await _authHeaders() });
  } catch (networkErr) {
    throw new ApiError(`Couldn't reach the API at ${path}. (${networkErr.message})`, 0);
  }
  if (!res.ok) throw await _toApiError(res);
  return res.json();
}

/**
 * Multipart/form-data POST -- the one request shape that isn't plain
 * JSON (POST /resume/parse-file: `file: UploadFile = File(...)`, optional
 * `tier: str | None = Form(None)`, see app/api/routes/resume.py). Kept
 * separate from apiPost rather than adding a body-type branch to it --
 * the two request shapes are different enough that hiding the
 * distinction would just move the complexity into a conditional inside
 * apiPost instead of removing it.
 */
export async function apiPostFile(path, file, extraFields = {}) {
  const formData = new FormData();
  formData.append("file", file);
  for (const [key, value] of Object.entries(extraFields)) {
    if (value !== undefined && value !== null) formData.append(key, value);
  }

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { method: "POST", body: formData, headers: await _authHeaders() });
  } catch (networkErr) {
    throw new ApiError(`Couldn't reach the API at ${path}. Is the backend running? (${networkErr.message})`, 0);
  }

  if (!res.ok) throw await _toApiError(res);

  return res.json();
}
