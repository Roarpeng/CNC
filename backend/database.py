import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 默认兼容本地 SQLite，生产可通过 DATABASE_URL 切换 PostgreSQL。
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cloudcam.db")

if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def ensure_jobs_columns() -> None:
    """Best-effort runtime migration for existing local databases."""
    required = {
        "stage": "VARCHAR",
        "progress": "INTEGER DEFAULT 0",
        "error_code": "VARCHAR",
        "error_message": "VARCHAR",
        "updated_at": "TIMESTAMP",
    }

    with engine.begin() as conn:
        inspector = inspect(conn)
        if "jobs" not in inspector.get_table_names():
            return

        existing = {col["name"] for col in inspector.get_columns("jobs")}
        for name, ddl in required.items():
            if name in existing:
                continue
            try:
                conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {name} {ddl}"))
            except Exception:
                # Ignore additive migration errors to avoid blocking startup.
                pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
