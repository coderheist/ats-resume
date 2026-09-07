"""Suite-wide fixtures.

Only one thing lives here so far, and it exists because of a genuine
cross-test coupling rather than convenience: RateLimitMiddleware keeps
its per-IP counters in memory on a single middleware instance attached
to the one shared `app` object (see app/core/rate_limit.py's "known
limitation" note). Every test in the suite therefore hits it as the same
client IP, and its 60-requests-per-60-seconds window is consumed
cumulatively across the whole run -- so a test that fires a lot of
scoring requests can push a completely unrelated test past the ceiling
and make it fail with a 429 it never provoked.

That was previously invisible only because no single test made many
requests. Raising the free tier's monthly allowance to 10 (the
entitlement tests have to exhaust it to test exhaustion) made the suite
cross the limit and fail in a way that had nothing to do with what those
tests assert. Clearing the window before each test makes the suite
order-independent, which it should have been regardless.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import RateLimitMiddleware
from app.main import app


def _find_rate_limiter() -> RateLimitMiddleware | None:
    """The live middleware instance, not a fresh one: Starlette builds
    the stack lazily on the first request, so build it here if that
    hasn't happened yet and keep the same object the app will use --
    resetting a throwaway copy would silently do nothing."""
    if app.middleware_stack is None:
        app.middleware_stack = app.build_middleware_stack()

    node = app.middleware_stack
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    return node


@pytest.fixture(autouse=True)
def reset_rate_limit_window():
    limiter = _find_rate_limiter()
    if limiter is not None:
        limiter._requests.clear()
    yield
