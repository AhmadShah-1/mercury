"""Add tenant constraints and AI usage accounting.

Revision ID: 3ca94f7cb56f
Revises: c981d9eb4d2d
Create Date: 2026-09-26 17:03:48
"""

import sqlalchemy as sa
from alembic import op

revision = "3ca94f7cb56f"
down_revision = "c981d9eb4d2d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ai_usage", sa.Column("embedding_tokens", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "ai_usage",
        sa.Column("embedding_rate", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    op.add_column(
        "ai_usage",
        sa.Column("reserved_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
    )
    for name in ("embedding_tokens", "embedding_rate", "reserved_usd"):
        op.alter_column("ai_usage", name, server_default=None)

    op.create_unique_constraint("uq_gmail_account_owner", "gmail_accounts", ["id", "user_id"])
    op.create_unique_constraint("uq_thread_owner", "email_threads", ["id", "user_id"])
    op.create_unique_constraint(
        "uq_thread_owner_account", "email_threads", ["id", "user_id", "gmail_account_id"]
    )
    op.create_unique_constraint(
        "uq_bucket_owner_account", "buckets", ["id", "user_id", "gmail_account_id"]
    )

    replacements = (
        ("ai_usage", "ai_usage_thread_id_fkey"),
        ("bucket_assignments", "bucket_assignments_bucket_id_fkey"),
        ("bucket_assignments", "bucket_assignments_thread_id_fkey"),
        ("buckets", "buckets_gmail_account_id_fkey"),
        ("email_threads", "email_threads_gmail_account_id_fkey"),
        ("gmail_label_mappings", "gmail_label_mappings_bucket_id_fkey"),
        ("message_references", "message_references_gmail_account_id_fkey"),
        ("message_references", "message_references_thread_id_fkey"),
        ("processing_runs", "processing_runs_gmail_account_id_fkey"),
        ("sender_rules", "sender_rules_bucket_id_fkey"),
        ("thread_analyses", "thread_analyses_thread_id_fkey"),
        ("thread_embeddings", "thread_embeddings_thread_id_fkey"),
    )
    for table, name in replacements:
        op.drop_constraint(name, table, type_="foreignkey")

    op.create_foreign_key(
        "fk_ai_usage_thread_owner",
        "ai_usage",
        "email_threads",
        ["thread_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_assignment_thread_owner",
        "bucket_assignments",
        "email_threads",
        ["thread_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_assignment_bucket_owner",
        "bucket_assignments",
        "buckets",
        ["bucket_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_bucket_account_owner",
        "buckets",
        "gmail_accounts",
        ["gmail_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_thread_account_owner",
        "email_threads",
        "gmail_accounts",
        ["gmail_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_label_mapping_bucket_owner",
        "gmail_label_mappings",
        "buckets",
        ["bucket_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_message_thread_owner",
        "message_references",
        "email_threads",
        ["thread_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_run_account_owner",
        "processing_runs",
        "gmail_accounts",
        ["gmail_account_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_sender_rule_bucket_owner",
        "sender_rules",
        "buckets",
        ["bucket_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_analysis_thread_owner",
        "thread_analyses",
        "email_threads",
        ["thread_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_embedding_thread_owner",
        "thread_embeddings",
        "email_threads",
        ["thread_id", "user_id"],
        ["id", "user_id"],
        ondelete="CASCADE",
    )


def downgrade():
    for table, name in (
        ("thread_embeddings", "fk_embedding_thread_owner"),
        ("thread_analyses", "fk_analysis_thread_owner"),
        ("sender_rules", "fk_sender_rule_bucket_owner"),
        ("processing_runs", "fk_run_account_owner"),
        ("message_references", "fk_message_thread_owner"),
        ("gmail_label_mappings", "fk_label_mapping_bucket_owner"),
        ("email_threads", "fk_thread_account_owner"),
        ("buckets", "fk_bucket_account_owner"),
        ("bucket_assignments", "fk_assignment_bucket_owner"),
        ("bucket_assignments", "fk_assignment_thread_owner"),
        ("ai_usage", "fk_ai_usage_thread_owner"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")

    op.create_foreign_key(
        "ai_usage_thread_id_fkey",
        "ai_usage",
        "email_threads",
        ["thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "bucket_assignments_bucket_id_fkey",
        "bucket_assignments",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "bucket_assignments_thread_id_fkey",
        "bucket_assignments",
        "email_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "buckets_gmail_account_id_fkey",
        "buckets",
        "gmail_accounts",
        ["gmail_account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "email_threads_gmail_account_id_fkey",
        "email_threads",
        "gmail_accounts",
        ["gmail_account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "gmail_label_mappings_bucket_id_fkey",
        "gmail_label_mappings",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "message_references_gmail_account_id_fkey",
        "message_references",
        "gmail_accounts",
        ["gmail_account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "message_references_thread_id_fkey",
        "message_references",
        "email_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "processing_runs_gmail_account_id_fkey",
        "processing_runs",
        "gmail_accounts",
        ["gmail_account_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "sender_rules_bucket_id_fkey",
        "sender_rules",
        "buckets",
        ["bucket_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "thread_analyses_thread_id_fkey",
        "thread_analyses",
        "email_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "thread_embeddings_thread_id_fkey",
        "thread_embeddings",
        "email_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_bucket_owner_account", "buckets", type_="unique")
    op.drop_constraint("uq_thread_owner_account", "email_threads", type_="unique")
    op.drop_constraint("uq_thread_owner", "email_threads", type_="unique")
    op.drop_constraint("uq_gmail_account_owner", "gmail_accounts", type_="unique")
    op.drop_column("ai_usage", "reserved_usd")
    op.drop_column("ai_usage", "embedding_rate")
    op.drop_column("ai_usage", "embedding_tokens")
