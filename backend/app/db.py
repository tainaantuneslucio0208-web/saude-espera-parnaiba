import ssl
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from .config import get_settings


def connection_kwargs():
    s = get_settings()
    kw: dict = {
        "host": s["mysql_host"],
        "port": s["mysql_port"],
        "user": s["mysql_user"],
        "password": s["mysql_password"],
        "database": s["mysql_database"],
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
    }
    if s.get("mysql_ssl_ca"):
        kw["ssl"] = ssl.create_default_context(cafile=s["mysql_ssl_ca"])
    elif s.get("mysql_ssl"):
        kw["ssl"] = ssl.create_default_context()
    return kw


@contextmanager
def get_conn():
    conn = pymysql.connect(**connection_kwargs())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
