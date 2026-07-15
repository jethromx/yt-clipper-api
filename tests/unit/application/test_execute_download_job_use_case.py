from pathlib import Path
from uuid import UUID, uuid4

import pytest

from yt_clipper.application.ports import DownloadResult
from yt_clipper.application.use_cases import ExecuteDownloadJobUseCase, GetDownloadUseCase
from yt_clipper.domain.exceptions import DomainError
from yt_clipper.domain.video import ClipRange, DownloadJob, VideoMetadata


class FakeRepository:
    def __init__(self, job: DownloadJob | None = None) -> None:
        self.jobs: dict[UUID, DownloadJob] = {}
        self.updated: list[DownloadJob] = []
        if job is not None:
            self.jobs[job.id] = job

    def add(self, job: DownloadJob) -> DownloadJob:
        self.jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def update(self, job: DownloadJob) -> DownloadJob:
        self.updated.append(job)
        self.jobs[job.id] = job
        return job


class FakeVideoProvider:
    def __init__(
        self,
        path: Path,
        raises: Exception | None = None,
        metadata: VideoMetadata | None = None,
    ) -> None:
        self.path = path
        self.raises = raises
        self.metadata = metadata or VideoMetadata(video_id="abc", title="Titulo")

    def download_best(self, source_url: str, output_dir: Path) -> DownloadResult:
        if self.raises is not None:
            raise self.raises
        return DownloadResult(path=self.path, metadata=self.metadata)


class FakeMediaProcessor:
    def clip(self, input_path: Path, clip_range: ClipRange, output_path: Path) -> Path:
        return output_path


class FakeStorage:
    def __init__(self, cleanup_raises: Exception | None = None) -> None:
        self.cleaned: list[UUID] = []
        self.cleanup_raises = cleanup_raises

    def prepare_download_path(self, job: DownloadJob) -> Path:
        return Path("downloads") / str(job.id)

    def prepare_clip_path(self, job: DownloadJob, source_path: Path) -> Path:
        return Path("downloads") / str(job.id) / f"clip{source_path.suffix}"

    def cleanup_download_path(self, job: DownloadJob) -> None:
        if self.cleanup_raises is not None:
            raise self.cleanup_raises
        self.cleaned.append(job.id)

    def resolve(self, relative_path: str) -> Path:
        return Path(relative_path)


def test_get_download_returns_job() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")

    result = GetDownloadUseCase(FakeRepository(job)).execute(job.id)

    assert result == job


def test_execute_download_job_marks_full_video_completed() -> None:
    downloaded_path = Path("downloads/video.mp4")
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    use_case = ExecuteDownloadJobUseCase(
        FakeRepository(job),
        FakeVideoProvider(downloaded_path),
        FakeMediaProcessor(),
        FakeStorage(),
    )

    result = use_case.execute(job.id)

    assert result.output_path == str(downloaded_path)
    assert result.error_message is None


def test_execute_download_job_clips_when_range_is_present() -> None:
    job = DownloadJob(
        source_url="https://www.youtube.com/watch?v=abc123",
        clip_range=ClipRange(1, 3),
    )
    use_case = ExecuteDownloadJobUseCase(
        FakeRepository(job),
        FakeVideoProvider(Path("downloads/video.mp4")),
        FakeMediaProcessor(),
        FakeStorage(),
    )

    result = use_case.execute(job.id)

    assert result.output_path == f"downloads/{job.id}/clip.mp4"


def test_execute_download_job_applies_metadata() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    provider = FakeVideoProvider(
        Path("downloads/video.mp4"),
        metadata=VideoMetadata(video_id="abc", title="Titulo real", description="Desc", tags=["x"]),
    )
    use_case = ExecuteDownloadJobUseCase(
        FakeRepository(job), provider, FakeMediaProcessor(), FakeStorage()
    )

    result = use_case.execute(job.id)

    assert result.video_title == "Titulo real"
    assert result.video_description == "Desc"
    assert result.youtube_tags == ["x"]


def test_execute_download_job_marks_failed_and_reraises() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    repository = FakeRepository(job)
    storage = FakeStorage()
    use_case = ExecuteDownloadJobUseCase(
        repository,
        FakeVideoProvider(Path("downloads/video.mp4"), raises=RuntimeError("download failed")),
        FakeMediaProcessor(),
        storage,
    )

    with pytest.raises(RuntimeError, match="download failed"):
        use_case.execute(job.id)

    assert repository.get(job.id).error_message == "download failed"  # type: ignore[union-attr]
    assert storage.cleaned == [job.id]


def test_execute_download_job_preserves_download_error_when_cleanup_fails() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    repository = FakeRepository(job)
    use_case = ExecuteDownloadJobUseCase(
        repository,
        FakeVideoProvider(Path("downloads/video.mp4"), raises=RuntimeError("download failed")),
        FakeMediaProcessor(),
        FakeStorage(cleanup_raises=RuntimeError("cleanup failed")),
    )

    with pytest.raises(RuntimeError, match="download failed"):
        use_case.execute(job.id)

    assert repository.get(job.id).error_message == "download failed"  # type: ignore[union-attr]


def test_execute_download_job_raises_when_job_is_missing() -> None:
    use_case = ExecuteDownloadJobUseCase(
        FakeRepository(),
        FakeVideoProvider(Path("downloads/video.mp4")),
        FakeMediaProcessor(),
        FakeStorage(),
    )

    with pytest.raises(DomainError):
        use_case.execute(uuid4())
