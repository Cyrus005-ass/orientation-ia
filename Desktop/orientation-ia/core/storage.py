from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    import psycopg2
except Exception:  # pragma: no cover
    psycopg2 = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def is_postgres() -> bool:
    return database_url().startswith(("postgres://", "postgresql://"))


@contextmanager
def connect():
    url = database_url()
    if url and is_postgres():
        if psycopg2 is None:
            raise RuntimeError("psycopg2-binary manquant pour DATABASE_URL Postgres")
        conn = psycopg2.connect(url)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
        return

    path = os.getenv("SQLITE_PATH") or str(Path("knowledge/live/audit.db"))
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_audit_schema() -> None:
    with connect() as conn:
        cur = conn.cursor()
        if is_postgres():
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    \"user\" TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip TEXT NOT NULL
                )
                """
            )
        else:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    \"user\" TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip TEXT NOT NULL
                )
                """
            )


def write_audit(user: str, action: str, ip: str) -> None:
    init_audit_schema()
    with connect() as conn:
        sql = (
            'INSERT INTO audit_log(date, \"user\", action, ip) VALUES (%s, %s, %s, %s)'
            if is_postgres()
            else 'INSERT INTO audit_log(date, \"user\", action, ip) VALUES (?, ?, ?, ?)'
        )
        conn.cursor().execute(sql, (utc_now(), user, action, ip))
