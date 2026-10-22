from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(target_engine=None) -> None:
    """Bring the schema to the latest Alembic revision (migrations/versions)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    from . import models  # noqa: F401  (register tables)

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    with (target_engine or engine).begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")


def init_db() -> None:
    if _settings.auto_migrate:
        run_migrations()
