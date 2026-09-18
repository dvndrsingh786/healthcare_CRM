from functools import lru_cache

from sqlalchemy import URL, create_engine

from app.config import get_settings


def database_url(database_name=None):
    settings = get_settings()
    # URL.create handles special characters in the password for us.
    return URL.create(
        drivername="postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=database_name or settings.db_name,
    )


def make_engine(url):
    return create_engine(
        url,
        pool_pre_ping=True,  # check a saved connection still works before using it
        # Every session works in UTC, so now() and timestamps are never ambiguous.
        connect_args={"options": "-c timezone=UTC"},
    )


# @lru_cache means the whole app shares one engine (one connection pool).
@lru_cache
def get_engine():
    return make_engine(database_url())
