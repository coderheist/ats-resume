from app.core.llm.token_pricing import _infer_provider_from_model, record_llm_usage
from app.db.models import Base, UsageLog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.db.session as session_module


def test_infer_provider_from_model():
    assert _infer_provider_from_model("claude-sonnet-5") == "claude"
    assert _infer_provider_from_model("gemini-3.6-flash") == "gemini"
    assert _infer_provider_from_model("gpt-oss-120b") == "groq"


def test_record_llm_usage_writes_a_row(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(session_module, "SessionLocal", TestSessionLocal)

    record_llm_usage(
        "claude-sonnet-5",
        {"input_tokens": 500, "output_tokens": 120},
        provider="claude",
    )

    db = TestSessionLocal()
    try:
        rows = db.query(UsageLog).filter(UsageLog.action == "llm_call").all()
        assert len(rows) == 1
        assert rows[0].provider == "claude"
        assert rows[0].input_tokens == 500
        assert rows[0].cost_usd is not None and rows[0].cost_usd > 0
    finally:
        db.close()


def test_record_llm_usage_never_raises_on_unknown_model():
    # calculate_cost() raises ValueError for a model not in MODEL_RATES --
    # record_llm_usage must swallow that, never break the caller over an
    # observability side effect.
    record_llm_usage("some-model-that-does-not-exist", {"input_tokens": 10, "output_tokens": 5}, provider="claude")


def test_record_llm_usage_never_raises_when_db_unavailable(monkeypatch):
    def _boom():
        raise RuntimeError("DB is down")
    monkeypatch.setattr(session_module, "SessionLocal", _boom)
    record_llm_usage("claude-sonnet-5", {"input_tokens": 10, "output_tokens": 5}, provider="claude")
