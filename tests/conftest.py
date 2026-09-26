from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import text

from mercury import create_app
from mercury.extensions import db

# Concurrent local runs may point at a separate disposable database on the same test server.
TEST_DATABASE_URL = os.environ.get(
    "MERCURY_TEST_DATABASE_URL",
    "postgresql+psycopg://mercury:mercury_test@localhost:55433/mercury_test",
)
if "localhost:55433/" not in TEST_DATABASE_URL and "127.0.0.1:55433/" not in TEST_DATABASE_URL:
    raise RuntimeError("Tests only run against the disposable test database on port 55433")


@pytest.fixture(scope="session")
def app():
    application = create_app(
        {
            "APP_ENV": "testing",
            "TESTING": True,
            "DEBUG": False,
            "SQLALCHEMY_DATABASE_URI": TEST_DATABASE_URL,
            "SERVER_NAME": "localhost",
        }
    )
    yield application
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(autouse=True)
def clean_database(app):
    with app.app_context():
        db.session.remove()
        table_names = [table.name for table in db.metadata.sorted_tables]
        # Queue rows reference truncated accounts, so each test also starts with an empty queue.
        table_names += db.session.scalars(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename LIKE 'procrastinate\\_%'"
            )
        ).all()
        quoted = ", ".join(f'"{name}"' for name in table_names)
        if quoted:
            db.session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
            db.session.commit()
    yield
    with app.app_context():
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(response) -> str:
    match = re.search(rb'name="csrf_token"[^>]*value="([^"]+)"', response.data)
    assert match, response.data.decode(errors="replace")
    return match.group(1).decode()


@pytest.fixture
def login(client):
    def perform(email: str = "alex@example.invalid"):
        page = client.get("/auth/dev")
        response = client.post(
            "/auth/dev",
            data={"email": email, "csrf_token": csrf_token(page)},
            follow_redirects=False,
        )
        assert response.status_code == 302
        return response

    return perform


@pytest.fixture
def connected(client, login):
    login()
    page = client.get("/auth/gmail/connect")
    response = client.post(
        "/auth/gmail/start",
        data={
            "accept_disclosure": "y",
            "ai_consent": "y",
            "csrf_token": csrf_token(page),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    return response
