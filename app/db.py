"""Thin psycopg3 connection helper. No ORM — the schema is simple enough
that raw SQL is clearer and easier for a small team to audit/extend."""
import contextlib
import psycopg
from psycopg.rows import dict_row
from app.config import config


@contextlib.contextmanager
def get_conn():
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextlib.contextmanager
def get_cursor():
    with get_conn() as conn:
        with conn.cursor() as cur:
            yield cur, conn
