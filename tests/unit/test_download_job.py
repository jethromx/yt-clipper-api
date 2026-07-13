from yt_clipper.domain.video import DownloadJob, DownloadStatus


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
