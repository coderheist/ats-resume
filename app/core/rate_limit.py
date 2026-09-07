"""
Basic per-IP rate limiting -- Phase 10 of the architecture plan. Nothing
before this bounded request volume on any endpoint at all.

Deliberately a small, transparent in-memory fixed-window counter rather
than a new dependency (e.g. slowapi) -- the actual requirement here is
simple (bound requests per IP per window), and a library adds a
dependency + its own config surface for something this app can implement
directly in ~40 lines, consistent with this project's general
"don't add a dependency for something simple enough to own outright"
approach elsewhere (see e.g. RequirementRow's plain-label approach vs.
Radix, or the embeddings TF-IDF fix over swapping to a new library).

Known limitation, stated plainly: this is per-process, in-memory state.
It resets on restart and does NOT coordinate across multiple worker
processes/replicas -- fine for a single-process deployment (this app's
current default), but running multiple uvicorn workers or replicas
behind a load balancer means each one enforces its own independent
limit, effectively multiplying the real ceiling by the worker count.
Moving to Redis (or any shared store) for the counter is what's needed
before scaling horizontally, and worth doing before that day comes
rather than being surprised by it.

Only applied to the compute/LLM-adjacent paths (parsing, scoring, bias
audit, voice) -- /health, /billing/tiers, /auth/me, /history are cheap,
mostly-DB-only reads and aren't worth throttling the same way.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

RATE_LIMITED_PREFIXES = ("/resume/", "/score/", "/bias-audit/", "/voice/")

# requests per window, per IP -- generous enough not to bother normal
# usage, low enough to blunt an accidental retry loop or a scripted
# abuse attempt. Configurable since "generous enough" depends on real
# traffic patterns this app doesn't have yet.
DEFAULT_LIMIT = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))
DEFAULT_WINDOW_SECONDS = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = DEFAULT_LIMIT, window_seconds: int = DEFAULT_WINDOW_SECONDS):
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(RATE_LIMITED_PREFIXES):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = self._requests[client_ip]

        while window and window[0] <= now - self.window_seconds:
            window.popleft()

        if len(window) >= self.limit:
            return JSONResponse(
                status_code=429,
                content={"detail": f"Too many requests -- limit is {self.limit} per {self.window_seconds}s. Please slow down and try again shortly."},
            )

        window.append(now)
        return await call_next(request)
