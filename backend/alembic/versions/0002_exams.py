"""exams + exam_pdfs tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("exam_id", sa.String(64), nullable=False, unique=True),
        sa.Column("course", sa.String(255), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("rubric_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_exams_exam_id", "exams", ["exam_id"], unique=True)

    op.create_table(
        "exam_pdfs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exam_fk",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("student_id", sa.String(64), nullable=True),
        sa.Column("question_id", sa.String(64), nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_exam_pdfs_exam_fk", "exam_pdfs", ["exam_fk"])
    op.create_index("ix_exam_pdfs_student_id", "exam_pdfs", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_exam_pdfs_student_id", table_name="exam_pdfs")
    op.drop_index("ix_exam_pdfs_exam_fk", table_name="exam_pdfs")
    op.drop_table("exam_pdfs")
    op.drop_index("ix_exams_exam_id", table_name="exams")
    op.drop_table("exams")
