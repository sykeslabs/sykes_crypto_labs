"""Applies a migration SQL file directly via a Postgres connection.

Optional convenience for local development. Requires DATABASE_URL to be set
in .env (Supabase dashboard -> Project Settings -> Database -> Connection
string). If you'd rather not add that credential, just paste the SQL file
contents into the Supabase SQL Editor instead.

Usage:
    python scripts/apply_migration.py migrations/0001_init.sql
"""

import sys
from pathlib import Path

import psycopg2

from app.config import get_settings


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/apply_migration.py <path_to_migration.sql>")
        return 1

    sql_path = Path(sys.argv[1])
    if not sql_path.exists():
        print(f"File not found: {sql_path}")
        return 1

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set in .env. Either set it, or apply this SQL "
              "manually via the Supabase SQL Editor.")
        return 1

    sql = sql_path.read_text(encoding="utf-8")

    with psycopg2.connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()

    print(f"Applied migration: {sql_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
