import sqlalchemy as sa
from alembic import op

revision = "0001_create_download_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "download_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=True),
        sa.Column("end_seconds", sa.Float(), nullable=True),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_download_jobs_status", "download_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_download_jobs_status", table_name="download_jobs")
    op.drop_table("download_jobs")
