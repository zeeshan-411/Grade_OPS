"""plagiarism_pairs table

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plagiarism_pairs",
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
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column("student_a", sa.String(64), nullable=False),
        sa.Column("student_b", sa.String(64), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_fk", "question_id", "student_a", "student_b",
            name="uq_plagiarism_pair",
        ),
    )
    op.create_index("ix_plagiarism_pairs_exam_fk", "plagiarism_pairs", ["exam_fk"])
    op.create_index("ix_plagiarism_pairs_run_fk", "plagiarism_pairs", ["run_fk"])


def downgrade() -> None:
    op.drop_index("ix_plagiarism_pairs_run_fk", table_name="plagiarism_pairs")
    op.drop_index("ix_plagiarism_pairs_exam_fk", table_name="plagiarism_pairs")
    op.drop_table("plagiarism_pairs")
