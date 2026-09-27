"""Add crates (non-destructive groups of buckets), favorites, and the default Misc crate.

Revision ID: 5d1e8c3a9f42
Revises: 7b2e4c91d0a3
Create Date: 2026-09-27 12:00:00
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "5d1e8c3a9f42"
down_revision = "7b2e4c91d0a3"
branch_labels = None
depends_on = None

# Mirrors mercury.buckets.crates.MISC_MAX_MEMBERS at the time of this migration.
MISC_MAX_MEMBERS = 15


def upgrade():
    op.create_table(
        "crates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("gmail_account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["gmail_account_id", "user_id"],
            ["gmail_accounts.id", "gmail_accounts.user_id"],
            name="fk_crate_account_owner",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("gmail_account_id", "name", name="uq_crate_account_name"),
        sa.UniqueConstraint("id", "user_id", "gmail_account_id", name="uq_crate_owner_account"),
    )
    op.create_index("ix_crates_user_id", "crates", ["user_id"])
    op.create_index(
        "uq_crate_account_misc",
        "crates",
        ["gmail_account_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'misc'"),
    )

    op.add_column("buckets", sa.Column("crate_id", UUID(as_uuid=True), nullable=True))
    op.add_column("buckets", sa.Column("crate_origin", sa.String(8), nullable=True))
    op.add_column(
        "buckets",
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("buckets", "favorite", server_default=None)
    op.create_index("ix_buckets_crate_id", "buckets", ["crate_id"])
    op.create_foreign_key(
        "fk_bucket_crate_owner",
        "buckets",
        "crates",
        ["crate_id", "user_id", "gmail_account_id"],
        ["id", "user_id", "gmail_account_id"],
    )

    # Every existing account gets its Misc crate.
    op.execute(
        "INSERT INTO crates (id, user_id, gmail_account_id, name, kind, favorite, "
        "created_at, updated_at) "
        "SELECT gen_random_uuid(), user_id, id, 'Misc', 'misc', false, now(), now() "
        "FROM gmail_accounts"
    )
    # Buckets the user made, or built with the retired merge, are theirs to place.
    op.execute(
        "UPDATE buckets SET crate_origin = 'user' WHERE origin = 'user' OR merged_at IS NOT NULL"
    )
    # Mercury's own small suggestions go into Misc; the rest are judged and left where they are.
    op.execute(
        sa.text(
            "UPDATE buckets AS b SET crate_id = c.id, crate_origin = 'auto' "
            "FROM crates AS c "
            "WHERE c.gmail_account_id = b.gmail_account_id AND c.kind = 'misc' "
            "AND b.origin = 'suggested' AND NOT b.archived AND b.crate_origin IS NULL "
            "AND (SELECT count(*) FROM bucket_assignments AS a WHERE a.bucket_id = b.id) < :limit"
        ).bindparams(limit=MISC_MAX_MEMBERS)
    )
    op.execute(
        "UPDATE buckets SET crate_origin = 'auto' "
        "WHERE origin = 'suggested' AND NOT archived AND crate_origin IS NULL"
    )


def downgrade():
    op.drop_constraint("fk_bucket_crate_owner", "buckets", type_="foreignkey")
    op.drop_index("ix_buckets_crate_id", table_name="buckets")
    op.drop_column("buckets", "favorite")
    op.drop_column("buckets", "crate_origin")
    op.drop_column("buckets", "crate_id")
    op.drop_index("uq_crate_account_misc", table_name="crates")
    op.drop_index("ix_crates_user_id", table_name="crates")
    op.drop_table("crates")
