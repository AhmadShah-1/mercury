from sqlalchemy import text

from mercury.extensions import db


def test_queue_schema_command_is_idempotent(app):
    runner = app.test_cli_runner()
    first = runner.invoke(args=["queue-schema"])
    second = runner.invoke(args=["queue-schema"])
    assert first.exit_code == 0 and second.exit_code == 0, (first.output, second.output)
    assert "already installed" in second.output
    with app.app_context():
        assert db.session.scalar(text("SELECT to_regclass('public.procrastinate_jobs')::text"))


def test_seed_demo_refuses_real_gmail(app, monkeypatch):
    monkeypatch.setitem(app.config, "MAIL_MODE", "gmail")
    result = app.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code != 0
    assert "synthetic mailbox" in result.output
