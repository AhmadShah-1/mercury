"""Add Mercury-maintained bucket meaning, lineage, and organization timestamps.

Revision ID: 7b2e4c91d0a3
Revises: 3ca94f7cb56f
Create Date: 2026-09-27 04:10:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "7b2e4c91d0a3"
down_revision = "3ca94f7cb56f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("buckets", sa.Column("ai_name", sa.String(80), nullable=True))
    op.add_column("buckets", sa.Column("ai_purpose", sa.String(240), nullable=True))
    op.add_column("buckets", sa.Column("ai_named_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "buckets",
        sa.Column("named_member_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "buckets",
        sa.Column("meaning_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("buckets", sa.Column("renamed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "buckets",
        sa.Column("reviewed_member_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("buckets", sa.Column("split_from_id", UUID(as_uuid=True), nullable=True))
    op.add_column("buckets", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_bucket_split_from",
        "buckets",
        "buckets",
        ["split_from_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for name in ("named_member_count", "meaning_stale", "reviewed_member_count"):
        op.alter_column("buckets", name, server_default=None)

    # Existing suggestions were named by Mercury, so their current text is the original meaning.
    # Renamed suggestions keep the AI text they started from; the user's text stays as `name`.
    op.execute(
        "UPDATE buckets SET ai_name = name, ai_purpose = purpose, ai_named_at = created_at "
        "WHERE origin = 'suggested'"
    )
    op.execute("UPDATE buckets SET renamed_at = updated_at WHERE user_confirmed")

    op.add_column(
        "gmail_accounts",
        sa.Column("last_organized_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("gmail_accounts", "last_organized_at")
    op.drop_constraint("fk_bucket_split_from", "buckets", type_="foreignkey")
    for name in (
        "merged_at",
        "split_from_id",
        "reviewed_member_count",
        "renamed_at",
        "meaning_stale",
        "named_member_count",
        "ai_named_at",
        "ai_purpose",
        "ai_name",
    ):
        op.drop_column("buckets", name)
