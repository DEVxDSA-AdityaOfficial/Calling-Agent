from datetime import timedelta

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User, UserSession, utcnow
from .security import hash_token, new_token

COOKIE_NAME = "ca_session"


def start_session(db: Session, user: User, response: Response) -> None:
    settings = get_settings()
    token = new_token()
    db.add(UserSession(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + timedelta(days=settings.session_days)))
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def end_session(db: Session, request: Request, response: Response) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if session:
            db.delete(session)
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME)
    if token:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == hash_token(token)))
        if session:
            expires = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=utcnow().tzinfo)
            if expires > utcnow():
                return session.user
            db.delete(session)
            db.commit()
    raise HTTPException(401, "Not signed in")
