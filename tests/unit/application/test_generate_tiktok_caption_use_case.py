from uuid import uuid4

import pytest

from yt_clipper.application.use_cases import GenerateTikTokCaptionUseCase
from yt_clipper.domain.exceptions import CaptionNotAvailableError, DomainError
from yt_clipper.domain.video import DownloadJob, TikTokCaption, VideoMetadata


class FakeRepository:
    def __init__(self, job: DownloadJob | None = None) -> None:
        self.jobs = {job.id: job} if job else {}
        self.updated = []

    def add(self, job):
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def update(self, job):
        self.updated.append(job)
        self.jobs[job.id] = job
        return job


class FakeGenerator:
    def __init__(self) -> None:
        self.seen: VideoMetadata | None = None
        self.seen_model: str | None = None

    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption:
        self.seen = metadata
        self.seen_model = model
        return TikTokCaption(caption="Mira esto", hashtags=["#viral", "#perros"])


def _completed_job() -> DownloadJob:
    job = DownloadJob(source_url="https://youtu.be/abc")
    job.apply_metadata(VideoMetadata(video_id="abc", title="Titulo", tags=["x"]))
    job.mark_completed("out.mp4")
    return job


def test_generate_caption_success() -> None:
    job = _completed_job()
    generator = FakeGenerator()
    use_case = GenerateTikTokCaptionUseCase(FakeRepository(job), generator)

    result = use_case.execute(job.id)

    assert result.tiktok_caption == "Mira esto"
    assert result.tiktok_hashtags == ["#viral", "#perros"]
    assert generator.seen is not None and generator.seen.title == "Titulo"


def test_generate_caption_missing_job() -> None:
    with pytest.raises(DomainError):
        GenerateTikTokCaptionUseCase(FakeRepository(), FakeGenerator()).execute(uuid4())


def test_generate_caption_requires_metadata() -> None:
    job = DownloadJob(source_url="https://youtu.be/abc")  # no metadata, not completed
    with pytest.raises(CaptionNotAvailableError):
        GenerateTikTokCaptionUseCase(FakeRepository(job), FakeGenerator()).execute(job.id)


def test_generate_caption_passes_model() -> None:
    job = _completed_job()
    generator = FakeGenerator()
    use_case = GenerateTikTokCaptionUseCase(FakeRepository(job), generator)

    use_case.execute(job.id, model="claude-sonnet-5")

    assert generator.seen_model == "claude-sonnet-5"
