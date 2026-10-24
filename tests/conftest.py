"""Every test gets a fresh disposable PostgreSQL database, never a living world."""

import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

from genesis_society.config import Laws
from genesis_society.storage import Store
from genesis_society.world import initialize


@pytest.fixture
def store():
    admin_url = os.environ.get(
        "SOCIETY_TEST_ADMIN_URL", "postgresql://society:local-demo-only@localhost:55433/postgres"
    )
    name = "society_test_" + uuid4().hex
    parsed = urlsplit(admin_url)
    url = urlunsplit(parsed._replace(path="/" + name))
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    s = Store(url.replace("postgresql://", "postgresql+psycopg://", 1))
    s.database_url = url
    try:
        config = Config("alembic.ini")
        config.attributes["database_url"] = str(s.engine.url.render_as_string(hide_password=False))
        command.upgrade(config, "head")
        initialize(
            s,
            Laws(
                founders=2,
                founder_window_seconds=0,
                founder_age_min_days=30,
                founder_age_max_days=30,
            ),
        )
        yield s
    finally:
        s.engine.dispose()
        assert name.startswith("society_test_")
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture
def actors(store):
    return list(store.snapshot()["residents"])
