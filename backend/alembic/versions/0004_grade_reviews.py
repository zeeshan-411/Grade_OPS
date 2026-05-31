"""grade_reviews table

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    review_action = postgresql.ENUM("APPROVE", "OVERRIDE", "FLAG", name="review_action")
    review_action.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "grade_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_grade_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("student_grades.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question_id", sa.String(64), nullable=False),
        sa.Column(
            "reviewed_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "action",
            postgresql.ENUM(
                "APPROVE", "OVERRIDE", "FLAG",
                name="review_action",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("override_score", sa.Float, nullable=True),
        sa.Column("comment", sa.String(2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "student_grade_id", "question_id", name="uq_review_per_question"
        ),
    )
    op.create_index(
        "ix_grade_reviews_student_grade_id", "grade_reviews", ["student_grade_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grade_reviews_student_grade_id", table_name="grade_reviews")
    op.drop_table("grade_reviews")
    postgresql.ENUM(name="review_action").drop(op.get_bind(), checkfirst=True)
