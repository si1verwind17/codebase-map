import psycopg

from .config import db_dsn


def connect() -> psycopg.Connection:
    """One short-lived connection per unit of work; services keep their SQL local."""
    return psycopg.connect(db_dsn(), autocommit=False)
