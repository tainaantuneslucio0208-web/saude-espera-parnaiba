import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache
def get_settings():
    origins = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:8000",
    )
    ssl_flag = os.getenv("MYSQL_SSL", "").strip().lower() in ("1", "true", "yes", "on")
    return {
        "mysql_host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "mysql_port": int(os.getenv("MYSQL_PORT", "3307")),
        "mysql_user": os.getenv("MYSQL_USER", "saude"),
        "mysql_password": os.getenv("MYSQL_PASSWORD", "saude123"),
        "mysql_database": os.getenv("MYSQL_DATABASE", "saude_parnaiba"),
        "mysql_ssl": ssl_flag,
        "mysql_ssl_ca": os.getenv("MYSQL_SSL_CA", "").strip() or None,
        "cors_origins": [o.strip() for o in origins.split(",") if o.strip()],
    }
