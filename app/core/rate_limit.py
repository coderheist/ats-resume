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

Behind a reverse proxy, the peer address this sees is the PROXY, not the
caller -- see `_client_key` for why that turns the limit into a shared
ceiling for the entire user base, and what TRUSTED_PROXY_HOPS does about
it.

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

# How many reverse proxies sit in front of this app. 0 (the default)
# means "nothing trusted in front" and keeps the old behavior of reading
# the peer address directly.
#
# This has to be a count rather than a boolean, and it has to default to
# 0, because X-Forwarded-For is caller-supplied text. Trusting it
# unconditionally would let anyone rotate the header per request and
# never be limited at all, which is strictly worse than the problem
# being fixed -- so the trust boundary is stated by the operator, who is
# the only party that knows the real topology. See `_client_key`.
#
# Set this to the number of proxies that append to X-Forwarded-For
# before a request reaches this process: 1 behind a single load
# balancer (Render, Railway, Fly, an ALB, an nginx ingress), 2 behind a
# CDN in front of that load balancer.
DEFAULT_TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        limit: int = DEFAULT_LIMIT,
        window_seconds: int = DEFAULT_WINDOW_SECONDS,
        trusted_proxy_hops: int = DEFAULT_TRUSTED_PROXY_HOPS,
    ):
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self.trusted_proxy_hops = max(0, trusted_proxy_hops)
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    def _client_key(self, request: Request) -> str:
        """The address to count this request against.

        `request.client.host` is the immediate peer. Deployed directly,
        that is the caller and everything works. Deployed the way
        docs/DEPLOYMENT.md describes -- behind a load balancer
        terminating TLS -- it is the load balancer, and the same string
        for every request the app will ever see. The per-IP dict then
        holds exactly one bucket, and the limit stops being per-caller
        and becomes a global ceiling shared by the whole user base: at
        the default 60/60s, the 61st request from anyone in a minute
        429s a user who has made one request. That failure is easy to
        misread as a traffic spike rather than a bug, because the limiter
        is behaving exactly as written.

        When TRUSTED_PROXY_HOPS is set, the real caller is recovered
        from X-Forwarded-For instead. The header reads
        `<client>, <proxy1>, ...`, with each proxy appending the peer IT
        received from, so with N trusted proxies the caller sits N
        entries from the right -- index `len(chain) - N`. Counting from
        the right is what makes a spoofed header harmless: a client that
        sends `X-Forwarded-For: 1.2.3.4` to a single trusted proxy
        produces `1.2.3.4, <real client>`, and index 2-1=1 still selects
        the real address the proxy observed. Taking the leftmost entry --
        the obvious-looking implementation -- would select the attacker's
        own text and hand out an unlimited quota to anyone who reads this
        file.

        Falls back to the peer address whenever the header is absent or
        empty, so a health checker or a direct hit that bypasses the
        proxy is still counted rather than sharing an "unknown" bucket.
        """
        peer = request.client.host if request.client else "unknown"
        if self.trusted_proxy_hops == 0:
            return peer

        chain = [part.strip() for part in request.headers.get("X-Forwarded-For", "").split(",") if part.strip()]
        if not chain:
            return peer
        return chain[max(0, len(chain) - self.trusted_proxy_hops)]

    def _sweep_idle_clients(self, now: float) -> None:
        """Drop buckets whose last request has aged out of the window.

        Without this the dict is append-only: every distinct address ever
        seen keeps an entry for the process's lifetime, including the
        empty deques left behind after their timestamps expire. That is
        unbounded growth driven entirely by external input -- a slow leak
        under normal traffic, and a fast one under a scan that walks
        source addresses. Nothing else ever removes a key, since dispatch
        only prunes timestamps within a bucket it is already handling.

        Swept at most once per window rather than per request: the cost is
        proportional to the number of tracked addresses, and doing it on
        every request would add that walk to the hot path for no
        additional benefit.
        """
        if now - self._last_sweep < self.window_seconds:
            return
        self._last_sweep = now
        cutoff = now - self.window_seconds
        for key in [k for k, window in self._requests.items() if not window or window[-1] <= cutoff]:
            del self._requests[key]

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(RATE_LIMITED_PREFIXES):
            return await call_next(request)

        client_ip = self._client_key(request)
        now = time.monotonic()
        self._sweep_idle_clients(now)
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
