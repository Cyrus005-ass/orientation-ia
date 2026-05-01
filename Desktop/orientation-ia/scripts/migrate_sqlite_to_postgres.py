from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

try:
    import psycopg2
except Exception:
    psycopg2 = None


def _connect_sqlite(path: Path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _connect_postgres(url: str):
    if psycopg2 is None:
        raise RuntimeError('psycopg2-binary requis pour la migration Postgres')
    return psycopg2.connect(url)


def migrate_audit(sqlite_path: Path, database_url: str) -> int:
    src = _connect_sqlite(sqlite_path)
    dst = _connect_postgres(database_url)
    try:
        dst.autocommit = False
        with dst.cursor() as cur:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    date TEXT NOT NULL,
                    "user" TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip TEXT NOT NULL
                )
                '''
            )
            rows = src.execute('SELECT date, "user", action, ip FROM audit_log ORDER BY id').fetchall()
            inserted = 0
            for row in rows:
                cur.execute(
                    'INSERT INTO audit_log(date, "user", action, ip) VALUES (%s, %s, %s, %s)',
                    (row['date'], row['user'], row['action'], row['ip']),
                )
                inserted += 1
        dst.commit()
        return inserted
    except Exception:
        dst.rollback()
        raise
    finally:
        src.close()
        dst.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Migrate audit log from SQLite to Postgres')
    parser.add_argument('--sqlite', default=os.getenv('SQLITE_PATH', 'knowledge/live/audit.db'))
    parser.add_argument('--database-url', default=os.getenv('DATABASE_URL', ''))
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit('DATABASE_URL requis')

    count = migrate_audit(Path(args.sqlite), args.database_url)
    print(f'Migration terminee: {count} lignes importees')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
