"""
Persists resumes and scan results for signed-in users -- Phase 4 of the
architecture plan. The models (Resume, ScanResult) already existed in
db/models.py; nothing before this module ever wrote to them.

Anonymous use is untouched: this is only ever called when a real User
row exists (an authenticated request), matching the same
"accounts are additive, not required" shape as entitlement_service.py.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Resume, ScanResult, User
from app.schemas.json_resume import JsonResume


def save_resume(db: Session, user: User, resume: JsonResume) -> Resume:
    row = Resume(user_id=user.id, data=resume.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def save_scan_result(db: Session, resume_id: str, mode: str, jd_text: str | None, final_score: float, breakdown: dict) -> ScanResult:
    row = ScanResult(
        resume_id=resume_id, mode=mode, jd_text=jd_text,
        final_score=final_score, breakdown=breakdown,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_history(db: Session, user: User) -> list[dict]:
    """Every scan result across every resume this user has saved, most
    recent first -- flattened into plain dicts (not ORM objects) since
    this is purely a read path for the API response, not something a
    caller needs to mutate and save back."""
    resumes = db.query(Resume).filter(Resume.user_id == user.id).all()
    resume_ids = {r.id: r for r in resumes}
    if not resume_ids:
        return []

    scans = (
        db.query(ScanResult)
        .filter(ScanResult.resume_id.in_(resume_ids.keys()))
        .order_by(ScanResult.created_at.desc())
        .all()
    )
    return [
        {
            "scan_id": s.id,
            "resume_id": s.resume_id,
            "resume_name": (resume_ids[s.resume_id].data or {}).get("basics", {}).get("name"),
            "mode": s.mode,
            "jd_text": s.jd_text,
            "final_score": s.final_score,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in scans
    ]
