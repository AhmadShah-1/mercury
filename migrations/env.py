from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config
fileConfig(config.config_file_name)
config.set_main_option(
    "sqlalchemy.url", str(current_app.extensions["migrate"].db.engine.url).replace("%", "%%")
)
target_db = current_app.extensions["migrate"].db


def get_metadata():
    return target_db.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Procrastinate owns and migrates its own tables independently."""
    if type_ == "table" and name.startswith("procrastinate_"):
        return False
    table = getattr(obj, "table", None)
    return not (reflected and table is not None and table.name.startswith("procrastinate_"))


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=get_metadata(),
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with target_db.engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=get_metadata(),
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
