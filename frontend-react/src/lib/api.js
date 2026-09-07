// In dev, Vite's proxy (see vite.config.js) forwards /score, /resume,
// etc. straight to the FastAPI backend on :8000, so this can stay
// relative (empty base) by default. Set VITE_API_BASE_URL to point at a
// different backend (e.g. a deployed one) for the production build.
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
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

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ? JSON.stringify(data.detail) : JSON.stringify(data);
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new ApiError(detail, res.status);
  }

  return res.json();
}

export async function apiGet(path) {
  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, { headers: await _authHeaders() });
  } catch (networkErr) {
    throw new ApiError(`Couldn't reach the API at ${path}. (${networkErr.message})`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ? JSON.stringify(data.detail) : JSON.stringify(data);
    } catch {
      // not JSON -- keep statusText
    }
    throw new ApiError(detail, res.status);
  }
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

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ? JSON.stringify(data.detail) : JSON.stringify(data);
    } catch {
      // not JSON -- keep statusText
    }
    throw new ApiError(detail, res.status);
  }

  return res.json();
}
