import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.pool
from dotenv import load_dotenv

load_dotenv()

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=int(os.environ.get("DB_POOL_MAX", "5")),
            dsn=os.environ["DATABASE_URL"],
        )
    return _pool


@contextmanager
def connection():
    """Borrow a connection from the pool and always return it.

    Any uncommitted transaction is rolled back before the connection goes
    back to the pool, so a failed query can't poison the next request.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        try:
            if not conn.closed:
                conn.rollback()
        finally:
            pool.putconn(conn, close=conn.closed)


def query(sql, params=(), one=False):
    with connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone() if one else cur.fetchall()


def apply_schema(conn):
    """Create tables and indexes if they don't exist yet."""
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        with conn.cursor() as cur:
            cur.execute(f.read())
    conn.commit()
