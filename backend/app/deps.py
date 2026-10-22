from fastapi import Depends
from sqlalchemy.orm import Session

from .auth import current_user
from .db import get_db
from .models import User
from .providers import retell_for_user
from .retell_client import RetellClient


def get_retell(user: User = Depends(current_user), db: Session = Depends(get_db)) -> RetellClient:
    return retell_for_user(db, user)
