from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import procrastinate

from mercury.jobs.tasks import build_blueprint


def queue_dsn(sqlalchemy_url: str) -> str:
    parsed = urlsplit(sqlalchemy_url)
    return urlunsplit(("postgresql", parsed.netloc, parsed.path, parsed.query, ""))


def create_queue_app(database_url: str, *, worker: bool = False) -> procrastinate.App:
    dsn = queue_dsn(database_url)
    connector = (
        procrastinate.PsycopgConnector(conninfo=dsn, min_size=1, max_size=2)
        if worker
        else procrastinate.SyncPsycopgConnector(conninfo=dsn, min_size=1, max_size=2)
    )
    app = procrastinate.App(connector=connector)
    app.add_tasks_from(build_blueprint(), namespace="mercury")
    return app
