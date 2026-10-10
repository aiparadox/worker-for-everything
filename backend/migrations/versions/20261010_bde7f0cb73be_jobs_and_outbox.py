"""jobs and outbox

Jobs: jobs, job_attempts, job_files and the outbox.

Revision ID: bde7f0cb73be
Revises: 2ef40decb9f0
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "bde7f0cb73be"
down_revision: str | Sequence[str] | None = "2ef40decb9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("type_version", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_file_id", sa.Uuid(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("progress", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "cancel_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("request_hash", sa.LargeBinary(), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sweep_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "last_enqueued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retrying', 'succeeded', 'failed', 'cancelled')",
            name=op.f("ck_jobs_status_allowed"),
        ),
        sa.CheckConstraint("trace_id ~ '^[0-9a-f]{32}$'", name=op.f("ck_jobs_trace_id_format")),
        sa.CheckConstraint(
            "NOT (result IS NOT NULL AND result_file_id IS NOT NULL)",
            name=op.f("ck_jobs_one_result"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_jobs_attempts_not_negative")),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 255",
            name=op.f("ck_jobs_idempotency_key_length"),
        ),
        sa.CheckConstraint("max_attempts >= 1", name=op.f("ck_jobs_max_attempts_positive")),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_jobs_progress_range")),
        sa.CheckConstraint("sweep_count >= 0", name=op.f("ck_jobs_sweep_count_not_negative")),
        sa.ForeignKeyConstraint(
            ["api_key_id"],
            ["api_keys.id"],
            name=op.f("fk_jobs_api_key_id_api_keys"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"],
            ["organisations.id"],
            name=op.f("fk_jobs_organisation_id_organisations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["result_file_id"],
            ["files.id"],
            name=op.f("fk_jobs_result_file_id_files"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        postgresql_with={
            "fillfactor": "80",
            "autovacuum_vacuum_scale_factor": "0.02",
            "autovacuum_vacuum_threshold": "1000",
            "autovacuum_analyze_scale_factor": "0.01",
        },
    )
    op.create_index("ix_jobs_api_key_id", "jobs", ["api_key_id"], unique=False)
    op.create_index(
        "ix_jobs_id_running",
        "jobs",
        ["id"],
        unique=False,
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_jobs_organisation_id_active",
        "jobs",
        ["organisation_id"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'retrying', 'running')"),
    )
    op.create_index(
        "ix_jobs_organisation_id_id_desc",
        "jobs",
        ["organisation_id", sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index(
        "ix_jobs_organisation_id_status_id_desc",
        "jobs",
        ["organisation_id", "status", sa.literal_column("id DESC")],
        unique=False,
    )
    op.create_index("ix_jobs_result_file_id", "jobs", ["result_file_id"], unique=False)
    op.create_index(
        "ix_jobs_run_at_waiting",
        "jobs",
        ["run_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'retrying')"),
    )
    op.create_index(
        "uq_jobs_organisation_id_idempotency_key",
        "jobs",
        ["organisation_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('succeeded', 'retryable_error', 'permanent_error', 'timeout', 'lease_lost')",
            name=op.f("ck_job_attempts_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "attempt_number >= 1", name=op.f("ck_job_attempts_attempt_number_positive")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_attempts_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_job_attempts")),
        sa.UniqueConstraint(
            "job_id", "attempt_number", name=op.f("uq_job_attempts_job_id_attempt_number")
        ),
        postgresql_with={
            "autovacuum_vacuum_scale_factor": "0.02",
            "autovacuum_vacuum_threshold": "1000",
            "autovacuum_analyze_scale_factor": "0.01",
        },
    )
    op.create_table(
        "job_files",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["files.id"], name=op.f("fk_job_files_file_id_files"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_files_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("job_id", "file_id", name=op.f("pk_job_files")),
    )
    op.create_index("ix_job_files_file_id", "job_files", ["file_id"], unique=False)
    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("routing_key", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("publish_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "reason IN ('submit', 'retry', 'recovery', 'sweep')",
            name=op.f("ck_outbox_reason_allowed"),
        ),
        sa.CheckConstraint(
            "publish_attempts >= 0", name=op.f("ck_outbox_publish_attempts_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_outbox_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox")),
        postgresql_with={
            "autovacuum_vacuum_scale_factor": "0.02",
            "autovacuum_vacuum_threshold": "1000",
            "autovacuum_analyze_scale_factor": "0.01",
        },
    )
    op.create_index("ix_outbox_job_id", "outbox", ["job_id"], unique=False)
    op.create_index(
        "ix_outbox_run_at_id_unpublished",
        "outbox",
        ["run_at", "id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL"),
    )


def downgrade() -> None:
    # Forward-only in production (DATABASE.md assumption A9); kept for local use, not tested.
    op.drop_index(
        "ix_outbox_run_at_id_unpublished",
        table_name="outbox",
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.drop_index("ix_outbox_job_id", table_name="outbox")
    op.drop_table("outbox")
    op.drop_index("ix_job_files_file_id", table_name="job_files")
    op.drop_table("job_files")
    op.drop_table("job_attempts")
    op.drop_index(
        "uq_jobs_organisation_id_idempotency_key",
        table_name="jobs",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(
        "ix_jobs_run_at_waiting",
        table_name="jobs",
        postgresql_where=sa.text("status IN ('queued', 'retrying')"),
    )
    op.drop_index("ix_jobs_result_file_id", table_name="jobs")
    op.drop_index("ix_jobs_organisation_id_status_id_desc", table_name="jobs")
    op.drop_index("ix_jobs_organisation_id_id_desc", table_name="jobs")
    op.drop_index(
        "ix_jobs_organisation_id_active",
        table_name="jobs",
        postgresql_where=sa.text("status IN ('queued', 'retrying', 'running')"),
    )
    op.drop_index(
        "ix_jobs_id_running", table_name="jobs", postgresql_where=sa.text("status = 'running'")
    )
    op.drop_index("ix_jobs_api_key_id", table_name="jobs")
    op.drop_table("jobs")
