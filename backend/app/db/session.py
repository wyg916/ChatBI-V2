from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    # A streaming request validates identity/conversation before handing work
    # to a background session.  Size the metadata pool for the supported
    # 20-request release load so authentication does not queue behind query
    # persistence while still keeping an explicit finite bound.
    return {"pool_pre_ping": True, "pool_size": 20, "max_overflow": 20, "pool_timeout": 10}


settings = get_settings()
engine = create_engine(settings.database_url, **_engine_options(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
