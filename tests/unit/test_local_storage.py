from pathlib import Path

from yt_clipper.domain.video import ClipRange, DownloadJob
from yt_clipper.infrastructure.storage.local import LocalFileStorage


def test_local_storage_prepares_download_and_clip_paths(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    job = DownloadJob(
        source_url="https://www.youtube.com/watch?v=abc123",
        clip_range=ClipRange(1, 2),
    )

    download_path = storage.prepare_download_path(job)
    clip_path = storage.prepare_clip_path(job, download_path / "video.webm")

    assert download_path == tmp_path / str(job.id)
    assert download_path.exists()
    assert clip_path == tmp_path / str(job.id) / "clip.webm"
    assert storage.resolve("relative.mp4") == tmp_path / "relative.mp4"


def test_local_storage_cleans_download_path(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    download_path = storage.prepare_download_path(job)
    (download_path / "partial.mp4").write_text("content")

    storage.cleanup_download_path(job)

    assert not download_path.exists()


def test_local_storage_resolves_absolute_path(tmp_path: Path) -> None:
    storage = LocalFileStorage(tmp_path)
    absolute_path = tmp_path / "video.mp4"

    assert storage.resolve(str(absolute_path)) == absolute_path
