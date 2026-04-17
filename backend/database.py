import os as _os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base

# On Vercel, DATABASE_URL is set automatically by the Postgres integration.
# Locally, fall back to SQLite.
_DATABASE_URL = _os.environ.get("DATABASE_URL", "")

if _DATABASE_URL:
    # Neon / Vercel Postgres uses "postgres://" — SQLAlchemy needs "postgresql://"
    if _DATABASE_URL.startswith("postgres://"):
        _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    engine = create_engine(_DATABASE_URL, pool_pre_ping=True)
else:
    _DB_PATH = _os.path.join(_os.path.dirname(__file__), "event_intel.db")
    engine = create_engine(
        f"sqlite:///{_DB_PATH}",
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate(engine)


def _migrate(engine):
    """Add columns introduced after initial schema (safe for both SQLite & Postgres)."""
    new_cols = [
        ("instagram_handle", "VARCHAR"),
        ("tiktok_handle", "VARCHAR"),
        ("youtube_handle", "VARCHAR"),
        ("website", "VARCHAR"),
    ]
    with engine.connect() as conn:
        for col, col_type in new_cols:
            try:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE participants ADD COLUMN {col} {col_type}"
                    )
                )
                conn.commit()
            except Exception:
                pass  # column already exists


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
