from fastapi.testclient import TestClient

from app.main import app

RESUME = {"basics": {"name": "Jordan Alvarez"}}


def test_rate_limit_allows_requests_under_the_limit():
    client = TestClient(app)
    for _ in range(5):
        resp = client.post("/score/standalone", json={"resume": RESUME})
        assert resp.status_code == 200


def test_rate_limit_blocks_after_exceeding_the_limit(monkeypatch):
    # Rebuild the app with a tiny limit for this test rather than firing
    # 60 real requests -- same middleware, just a lower ceiling so the
    # test is fast and the behavior being verified is unambiguous.
    from app.core.rate_limit import RateLimitMiddleware
    from fastapi import FastAPI
    from app.api.routes import scan

    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, limit=3, window_seconds=60)
    test_app.include_router(scan.router)
    client = TestClient(test_app)

    for i in range(3):
        resp = client.post("/score/standalone", json={"resume": RESUME})
        assert resp.status_code == 200, f"request {i + 1} should succeed"

    blocked = client.post("/score/standalone", json={"resume": RESUME})
    assert blocked.status_code == 429
    assert "Too many requests" in blocked.json()["detail"]


def test_rate_limit_does_not_apply_to_unrelated_paths():
    from app.core.rate_limit import RateLimitMiddleware
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, limit=1, window_seconds=60)

    @test_app.get("/health")
    def health():
        return {"status": "ok"}

    client = TestClient(test_app)
    # Limit is 1, but /health isn't in RATE_LIMITED_PREFIXES -- every call
    # should succeed regardless of how many.
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_rate_limit_state_is_keyed_by_client_ip():
    """TestClient can't easily simulate multiple distinct client IPs over
    HTTP, so this verifies the actual mechanism directly: after requests
    from one client, the middleware's internal window is keyed under
    that one IP with the right count -- proving isolation is structural
    (a dict keyed by IP), not just asserted by a docstring."""
    from app.core.rate_limit import RateLimitMiddleware
    from fastapi import FastAPI
    from app.api.routes import scan

    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, limit=10, window_seconds=60)
    test_app.include_router(scan.router)
    client = TestClient(test_app)

    for _ in range(3):
        client.post("/score/standalone", json={"resume": RESUME})

    middleware_instance = test_app.middleware_stack
    # Walk to the RateLimitMiddleware instance to inspect its real state
    # rather than re-deriving the wrapping logic here.
    node = middleware_instance
    found = None
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    found = node
    assert found is not None, "RateLimitMiddleware instance not found in the stack"
    assert len(found._requests) == 1  # exactly one IP key
    ip_key = next(iter(found._requests))
    assert len(found._requests[ip_key]) == 3  # exactly the 3 requests made
# --------------------------------------------------------------------
# Proxy-awareness (TRUSTED_PROXY_HOPS)
# --------------------------------------------------------------------
#
# Behind a load balancer every request arrives from the same peer, so the
# per-IP dict collapses to a single bucket and the limit becomes a global
# ceiling shared by every user. These pin both halves of the fix: the
# header is honored only when an operator declares how many proxies to
# trust, and honoring it must not hand out an unlimited quota to anyone
# who sets the header themselves.


def _limited_app(limit=3, hops=0):
    from app.core.rate_limit import RateLimitMiddleware
    from fastapi import FastAPI
    from app.api.routes import scan

    test_app = FastAPI()
    test_app.add_middleware(
        RateLimitMiddleware, limit=limit, window_seconds=60, trusted_proxy_hops=hops,
    )
    test_app.include_router(scan.router)
    return test_app


def _limiter_of(test_app):
    from app.core.rate_limit import RateLimitMiddleware

    node = test_app.middleware_stack
    while node is not None and not isinstance(node, RateLimitMiddleware):
        node = getattr(node, "app", None)
    assert node is not None, "RateLimitMiddleware instance not found in the stack"
    return node


def test_forwarded_for_is_ignored_when_no_proxies_are_trusted():
    """Default posture: X-Forwarded-For is caller-supplied text, so with
    TRUSTED_PROXY_HOPS unset it must not influence the bucket at all --
    otherwise a directly-exposed deployment could be bypassed by anyone
    rotating the header."""
    test_app = _limited_app(limit=3, hops=0)
    client = TestClient(test_app)

    for i in range(3):
        resp = client.post("/score/standalone", json={"resume": RESUME},
                           headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert resp.status_code == 200, f"request {i + 1} should succeed"

    blocked = client.post("/score/standalone", json={"resume": RESUME},
                          headers={"X-Forwarded-For": "10.0.0.99"})
    assert blocked.status_code == 429
    assert len(_limiter_of(test_app)._requests) == 1  # one bucket: the peer


def test_trusted_proxy_keys_each_forwarded_client_separately():
    """The actual production fix: one busy caller must not exhaust the
    allowance of everyone else arriving through the same load balancer."""
    test_app = _limited_app(limit=3, hops=1)
    client = TestClient(test_app)

    for _ in range(3):
        assert client.post("/score/standalone", json={"resume": RESUME},
                           headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 200

    # That caller is now at its ceiling...
    assert client.post("/score/standalone", json={"resume": RESUME},
                       headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 429
    # ...but a different caller through the same proxy is unaffected.
    assert client.post("/score/standalone", json={"resume": RESUME},
                       headers={"X-Forwarded-For": "198.51.100.4"}).status_code == 200

    assert set(_limiter_of(test_app)._requests) == {"203.0.113.7", "198.51.100.4"}


def test_spoofed_forwarded_for_cannot_escape_the_limit():
    """A caller that sets its own X-Forwarded-For reaches a single trusted
    proxy, which appends the address it actually observed -- so the real
    client is the rightmost entry and the spoofed prefix is inert. If this
    counted the leftmost entry instead, varying it per request would give
    an attacker an unbounded quota."""
    test_app = _limited_app(limit=3, hops=1)
    client = TestClient(test_app)

    def spoof(fake):  # proxy appends the real observed client after the forged value
        return client.post("/score/standalone", json={"resume": RESUME},
                           headers={"X-Forwarded-For": f"{fake}, 203.0.113.7"})

    for i in range(3):
        assert spoof(f"1.2.3.{i}").status_code == 200

    assert spoof("1.2.3.250").status_code == 429  # still the same real client
    assert set(_limiter_of(test_app)._requests) == {"203.0.113.7"}


def test_idle_client_buckets_are_swept_rather_than_accumulating():
    """Nothing else removes a key, so without the sweep the dict grows
    once per distinct address seen and never shrinks -- unbounded growth
    driven by external input."""
    import time

    from app.core.rate_limit import RateLimitMiddleware

    limiter = RateLimitMiddleware(app=None, limit=10, window_seconds=60)
    now = time.monotonic()

    limiter._requests["1.1.1.1"].append(now - 3600)  # long expired
    limiter._requests["2.2.2.2"].append(now)         # current
    limiter._requests["3.3.3.3"]                     # empty leftover

    limiter._last_sweep = now - 61  # due for a sweep
    limiter._sweep_idle_clients(now)

    assert set(limiter._requests) == {"2.2.2.2"}
