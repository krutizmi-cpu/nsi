from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL
from models import Base


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        path = Path(url.replace("sqlite:///", "", 1))
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _sqlite_table_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(r[1]) for r in rows}


def _ensure_sqlite_columns_nsi_items() -> None:
    """Добавление колонок к существующей SQLite-таблице без Alembic."""
    if not str(engine.url).startswith("sqlite"):
        return
    alters: list[tuple[str, str]] = [
        ("vat_rate_percent", "REAL"),
        ("length_mm", "REAL"),
        ("width_mm", "REAL"),
        ("height_mm", "REAL"),
        ("weight_kg", "REAL"),
        ("volume_m3", "REAL"),
        ("dimensions_source", "TEXT"),
        ("supplier_page_url", "TEXT"),
        ("supplier_parser_id", "TEXT"),
    ]
    with engine.begin() as conn:
        existing = _sqlite_table_columns(conn, "nsi_items")
        if not existing:
            return
        for col, coltype in alters:
            if col not in existing:
                conn.execute(text(f"ALTER TABLE nsi_items ADD COLUMN {col} {coltype}"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_sqlite_columns_nsi_items()
