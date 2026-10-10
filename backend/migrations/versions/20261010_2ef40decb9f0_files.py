"""files

Files: uploaded inputs and stored results.

Revision ID: 2ef40decb9f0
Revises: e24fac249df6
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2ef40decb9f0"
down_revision: str | Sequence[str] | None = "e24fac249df6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('input', 'result')", name=op.f("ck_files_kind_allowed")),
        sa.CheckConstraint(
            "status IN ('pending', 'available')", name=op.f("ck_files_status_allowed")
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 255", name=op.f("ck_files_display_name_length")
        ),
        sa.CheckConstraint("size_bytes >= 0", name=op.f("ck_files_size_not_negative")),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_files_organisation_id_organisations"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_files")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_files_storage_key")),
    )
    op.create_index(
        "ix_files_expires_at_pending",
        "files",
        ["expires_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_files_organisation_id", "files", ["organisation_id"], unique=False)


def downgrade() -> None:
    # Forward-only in production (DATABASE.md assumption A9); kept for local use, not tested.
    op.drop_index("ix_files_organisation_id", table_name="files")
    op.drop_index(
        "ix_files_expires_at_pending",
        table_name="files",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_table("files")
