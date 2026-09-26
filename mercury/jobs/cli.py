"""Procrastinate CLI entry point; configuration is loaded through the Flask factory."""

from mercury import create_app
from mercury.jobs.queue import create_queue_app
from mercury.jobs.tasks import bind_flask_app

flask_app = create_app()
bind_flask_app(flask_app)
app = create_queue_app(flask_app.config["SQLALCHEMY_DATABASE_URI"], worker=True)
