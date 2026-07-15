from datetime import datetime

from yt_clipper.domain.video import (
    DownloadJob,
    DownloadStatus,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)


def test_download_job_state_transitions() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")

    job.mark_running()
    assert job.status == DownloadStatus.RUNNING

    job.mark_failed("failed")
    assert job.status == DownloadStatus.FAILED
    assert job.error_message == "failed"

    job.mark_completed("downloads/video.mp4")
    assert job.status == DownloadStatus.COMPLETED
    assert job.output_path == "downloads/video.mp4"
    assert job.error_message is None


def test_apply_metadata_sets_youtube_fields() -> None:
    job = DownloadJob(source_url="https://youtu.be/abc")
    before = job.updated_at

    job.apply_metadata(
        VideoMetadata(
            video_id="abc",
            title="Un titulo",
            description="Una descripcion",
            tags=["perro", "gato"],
        )
    )

    assert job.video_title == "Un titulo"
    assert job.video_description == "Una descripcion"
    assert job.youtube_tags == ["perro", "gato"]
    assert job.updated_at >= before


def test_apply_tiktok_caption_sets_fields_and_timestamp() -> None:
    job = DownloadJob(source_url="https://youtu.be/abc")

    job.apply_tiktok_caption(TikTokCaption(caption="Mira esto", hashtags=["#viral"]))

    assert job.tiktok_caption == "Mira esto"
    assert job.tiktok_hashtags == ["#viral"]
    assert isinstance(job.tiktok_generated_at, datetime)


def test_video_search_result_holds_fields() -> None:
    result = VideoSearchResult(
        video_id="abc",
        title="Titulo",
        url="https://www.youtube.com/watch?v=abc",
        duration_seconds=12.0,
        channel="Canal",
        thumbnail_url="https://i.ytimg.com/abc.jpg",
    )

    assert result.video_id == "abc"
    assert result.url.endswith("v=abc")
