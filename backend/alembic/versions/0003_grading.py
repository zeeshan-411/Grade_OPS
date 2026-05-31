"""grading_runs + student_grades tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    run_status = postgresql.ENUM(
        "PENDING", "RUNNING", "DONE", "FAILED", name="run_status"
    )
    run_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "grading_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exam_fk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "started_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING", "RUNNING", "DONE", "FAILED",
                name="run_status",
                create_type=False,
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_msg", sa.String(2000), nullable=True),
        sa.Column("n_students", sa.Integer, nullable=True),
        sa.Column("n_pdfs", sa.Integer, nullable=True),
    )
    op.create_index("ix_grading_runs_exam_fk", "grading_runs", ["exam_fk"])

    op.create_table(
        "student_grades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exam_fk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_fk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("grading_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("student_id", sa.String(64), nullable=False),
        sa.Column("total_score", sa.Float, nullable=False),
        sa.Column("max_possible", sa.Float, nullable=False),
        sa.Column("needs_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("verified", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("flags", postgresql.JSONB, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_student_grades_exam_fk", "student_grades", ["exam_fk"])
    op.create_index("ix_student_grades_run_fk", "student_grades", ["run_fk"])
    op.create_index("ix_student_grades_student_id", "student_grades", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_student_grades_student_id", table_name="student_grades")
    op.drop_index("ix_student_grades_run_fk", table_name="student_grades")
    op.drop_index("ix_student_grades_exam_fk", table_name="student_grades")
    op.drop_table("student_grades")
    op.drop_index("ix_grading_runs_exam_fk", table_name="grading_runs")
    op.drop_table("grading_runs")
    postgresql.ENUM(name="run_status").drop(op.get_bind(), checkfirst=True)
