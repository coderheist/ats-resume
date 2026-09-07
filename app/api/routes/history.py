from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth.dependencies import AuthenticatedUser, get_current_user
from app.core.services.resume_store import list_history
from app.core.services.user_service import get_or_create_user
from app.db.session import get_db

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
def get_history(auth_user: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """Requires a valid Firebase ID token. Every saved scan for this
    user's resumes, most recent first -- see services/resume_store.py."""
    user = get_or_create_user(db, auth_user)
    return {"history": list_history(db, user)}
