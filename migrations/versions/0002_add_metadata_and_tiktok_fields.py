import sqlalchemy as sa
from alembic import op

revision = "0002_add_metadata_and_tiktok_fields"
down_revision = "0001_create_download_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("download_jobs", sa.Column("video_title", sa.Text(), nullable=True))
    op.add_column("download_jobs", sa.Column("video_description", sa.Text(), nullable=True))
    op.add_column("download_jobs", sa.Column("youtube_tags", sa.JSON(), nullable=True))
    op.add_column("download_jobs", sa.Column("tiktok_caption", sa.Text(), nullable=True))
    op.add_column("download_jobs", sa.Column("tiktok_hashtags", sa.JSON(), nullable=True))
    op.add_column(
        "download_jobs",
        sa.Column("tiktok_generated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("download_jobs", "tiktok_generated_at")
    op.drop_column("download_jobs", "tiktok_hashtags")
    op.drop_column("download_jobs", "tiktok_caption")
    op.drop_column("download_jobs", "youtube_tags")
    op.drop_column("download_jobs", "video_description")
    op.drop_column("download_jobs", "video_title")
