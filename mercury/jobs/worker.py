from __future__ import annotations

from mercury import create_app
from mercury.jobs.queue import create_queue_app
from mercury.jobs.tasks import bind_flask_app


def main() -> None:
    flask_app = create_app()
    bind_flask_app(flask_app)
    queue_app = create_queue_app(flask_app.config["SQLALCHEMY_DATABASE_URI"], worker=True)
    with flask_app.app_context():
        queue_app.run_worker(concurrency=flask_app.config["WORKER_CONCURRENCY"])


if __name__ == "__main__":
    main()
