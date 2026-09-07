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
