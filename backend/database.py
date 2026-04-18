import os as _os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from models import Base

_DATABASE_URL = _os.environ.get("DATABASE_URL", "")

if _DATABASE_URL:
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
    """Safe additive migrations for both SQLite & Postgres."""
    col_migrations = [
        ("participants", "instagram_handle", "VARCHAR"),
        ("participants", "tiktok_handle",    "VARCHAR"),
        ("participants", "youtube_handle",   "VARCHAR"),
        ("participants", "website",          "VARCHAR"),
        ("events",       "workspace_id",     "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in col_migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # column already exists

        # Ensure a default workspace (id=1) exists and legacy events are assigned to it
        try:
            row = conn.execute(text("SELECT id FROM workspaces WHERE id = 1")).fetchone()
            if not row:
                conn.execute(text(
                    "INSERT INTO workspaces (id, name, pin) VALUES (1, 'Default', NULL)"
                ))
                conn.commit()
        except Exception:
            pass

        try:
            conn.execute(text(
                "UPDATE events SET workspace_id = 1 WHERE workspace_id IS NULL"
            ))
            conn.commit()
        except Exception:
            pass

        # Migrate old global luma_token → ws_1:luma_token
        try:
            old = conn.execute(text(
                "SELECT value FROM settings WHERE key = 'luma_token'"
            )).fetchone()
            new = conn.execute(text(
                "SELECT value FROM settings WHERE key = 'ws_1:luma_token'"
            )).fetchone()
            if old and old[0] and not (new and new[0]):
                conn.execute(text(
                    "INSERT INTO settings (key, value) VALUES ('ws_1:luma_token', :v)"
                ), {"v": old[0]})
                conn.commit()
        except Exception:
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
