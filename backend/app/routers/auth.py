from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, end_session, start_session
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, SignupIn, UserOut
from ..security import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Same work for unknown emails so response time doesn't reveal which accounts exist.
_DUMMY_HASH = hash_password("timing-equaliser")


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(data: SignupIn, response: Response, db: Session = Depends(get_db)):
    if not get_settings().allow_signup:
        raise HTTPException(403, "Sign-ups are disabled.")
    email = data.email.lower()
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(409, "An account with this email already exists.")
    user = User(email=email, name=data.name.strip(), password_hash=hash_password(data.password))
    db.add(user)
    db.commit()
    start_session(db, user, response)
    return user


@router.post("/login", response_model=UserOut)
def login(data: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    password_ok = verify_password(data.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(401, "Incorrect email or password.")
    start_session(db, user, response)
    return user


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    end_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
