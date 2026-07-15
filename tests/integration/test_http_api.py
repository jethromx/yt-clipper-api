from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from yt_clipper.application.use_cases import CreateDownloadCommand
from yt_clipper.domain.exceptions import (
    CaptionGeneratorUnavailableError,
    DomainError,
    EmptySearchQueryError,
)
from yt_clipper.domain.video import (
    DownloadJob,
    DownloadStatus,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)
from yt_clipper.interfaces.http.dependencies import (
    configured_storage_dir,
    get_create_download_batch_use_case,
    get_create_download_use_case,
    get_delete_download_use_case,
    get_generate_caption_use_case,
    get_get_download_use_case,
    get_search_use_case,
)
from yt_clipper.main import create_app


class FakeCreateDownloadUseCase:
    def __init__(self) -> None:
        self.job: DownloadJob | None = None

    def execute(self, command: CreateDownloadCommand) -> DownloadJob:
        self.job = DownloadJob(source_url=command.source_url)
        return self.job


class FakeGetDownloadUseCase:
    def __init__(self, job: DownloadJob | None) -> None:
        self.job = job

    def execute(self, job_id: UUID) -> DownloadJob | None:
        return self.job if self.job and self.job.id == job_id else None


class FailingCreateDownloadUseCase:
    def execute(self, command: CreateDownloadCommand) -> DownloadJob:
        raise DomainError("bad request")


def test_download_requires_api_key() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/downloads",
        json={"source_url": "https://www.youtube.com/watch?v=abc123"},
    )

    assert response.status_code == 401


def test_create_download_returns_accepted_job() -> None:
    app = create_app()
    fake_use_case = FakeCreateDownloadUseCase()
    app.dependency_overrides[get_create_download_use_case] = lambda: fake_use_case
    client = TestClient(app)

    response = client.post(
        "/api/v1/downloads",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={
            "source_url": "https://www.youtube.com/watch?v=abc123",
            "start_seconds": 1,
            "end_seconds": 2,
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_create_download_returns_400_for_domain_error() -> None:
    app = create_app()
    app.dependency_overrides[get_create_download_use_case] = lambda: FailingCreateDownloadUseCase()
    client = TestClient(app)

    response = client.post(
        "/api/v1/downloads",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={"source_url": "https://www.youtube.com/watch?v=abc123"},
    )

    assert response.status_code == 400


def test_create_download_requires_complete_clip_bounds() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/downloads",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={"source_url": "https://www.youtube.com/watch?v=abc123", "start_seconds": 1},
    )

    assert response.status_code == 422


def test_get_download_returns_404_for_missing_job() -> None:
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(None)
    client = TestClient(app)

    response = client.get(
        "/api/v1/downloads/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": "Bearer dev-secret-change-me"},
    )

    assert response.status_code == 404


def test_download_file_returns_completed_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "video.mp4"
    output_path.write_text("content")
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    job.mark_completed(str(output_path))
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(job)
    client = TestClient(app)

    response = client.get(
        f"/api/v1/downloads/{job.id}/file",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 200
    assert response.content == b"content"
    assert response.headers["content-disposition"] == 'attachment; filename="video.mp4"'


def test_download_file_returns_conflict_when_not_complete() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(job)
    client = TestClient(app)

    response = client.get(
        f"/api/v1/downloads/{job.id}/file",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 409


def test_download_file_resolves_relative_output_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "relative.mp4"
    output_path.write_text("content")
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    job.status = DownloadStatus.COMPLETED
    job.output_path = "relative.mp4"
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(job)
    app.dependency_overrides[configured_storage_dir] = lambda: tmp_path
    client = TestClient(app)

    response = client.get(
        f"/api/v1/downloads/{job.id}/file",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 200


def test_download_file_returns_404_when_file_is_missing() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    job.mark_completed("missing.mp4")
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(job)
    client = TestClient(app)

    response = client.get(
        f"/api/v1/downloads/{job.id}/file",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 404


def test_health_and_ready_are_public() -> None:
    client = TestClient(create_app())

    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 204


def test_get_download_rejects_unknown_uuid() -> None:
    app = create_app()
    app.dependency_overrides[get_get_download_use_case] = lambda: FakeGetDownloadUseCase(None)
    client = TestClient(app)

    response = client.get(
        f"/api/v1/downloads/{uuid4()}",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 404


class FakeSearchUseCase:
    def execute(self, query: str, limit: int) -> list[VideoSearchResult]:
        return [
            VideoSearchResult(
                video_id="abc",
                title="Perro",
                url="https://www.youtube.com/watch?v=abc",
                duration_seconds=10.0,
                channel="Canal",
                thumbnail_url="https://i.ytimg.com/abc.jpg",
            )
        ]


class FailingSearchUseCase:
    def execute(self, query: str, limit: int) -> list[VideoSearchResult]:
        raise EmptySearchQueryError("empty")


class FakeBatchUseCase:
    def execute(self, source_urls: list[str]) -> list[DownloadJob]:
        return [DownloadJob(source_url=url) for url in source_urls]


class FakeCaptionUseCase:
    def execute(self, job_id: UUID, model: str | None = None) -> DownloadJob:
        job = DownloadJob(source_url="https://youtu.be/abc")
        job.apply_metadata(VideoMetadata(video_id="abc", title="T"))
        job.mark_completed("out.mp4")
        job.apply_tiktok_caption(TikTokCaption(caption="Mira", hashtags=["#viral"]))
        return job


class UnavailableCaptionUseCase:
    def execute(self, job_id: UUID, model: str | None = None) -> DownloadJob:
        raise CaptionGeneratorUnavailableError("configura la key")


def test_search_returns_results() -> None:
    app = create_app()
    app.dependency_overrides[get_search_use_case] = lambda: FakeSearchUseCase()
    client = TestClient(app)

    response = client.get(
        "/api/v1/search",
        params={"q": "perros", "limit": 5},
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["video_id"] == "abc"


def test_search_requires_query() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/search",
        params={"q": ""},
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 400


def test_batch_creates_jobs() -> None:
    app = create_app()
    app.dependency_overrides[get_create_download_batch_use_case] = lambda: FakeBatchUseCase()
    client = TestClient(app)

    response = client.post(
        "/api/v1/downloads/batch",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={
            "source_urls": [
                "https://www.youtube.com/watch?v=a",
                "https://www.youtube.com/watch?v=b",
            ]
        },
    )

    assert response.status_code == 202
    assert len(response.json()["jobs"]) == 2


def test_generate_tiktok_caption_success() -> None:
    app = create_app()
    app.dependency_overrides[get_generate_caption_use_case] = lambda: FakeCaptionUseCase()
    client = TestClient(app)

    response = client.post(
        f"/api/v1/downloads/{uuid4()}/tiktok",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 200
    assert response.json()["tiktok_caption"] == "Mira"


def test_generate_tiktok_caption_unavailable_returns_503() -> None:
    app = create_app()
    app.dependency_overrides[get_generate_caption_use_case] = lambda: UnavailableCaptionUseCase()
    client = TestClient(app)

    response = client.post(
        f"/api/v1/downloads/{uuid4()}/tiktok",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 503


class RecordingCaptionUseCase:
    def __init__(self) -> None:
        self.model = "unset"

    def execute(self, job_id, model=None):  # type: ignore[no-untyped-def]
        self.model = model
        job = DownloadJob(source_url="https://youtu.be/abc")
        job.apply_metadata(VideoMetadata(video_id="abc", title="T"))
        job.mark_completed("out.mp4")
        job.apply_tiktok_caption(TikTokCaption(caption="Mira", hashtags=["#viral"]))
        return job


class RecordingDeleteUseCase:
    def __init__(self) -> None:
        self.deleted: list = []

    def execute(self, job_id) -> None:  # type: ignore[no-untyped-def]
        self.deleted.append(job_id)


def test_models_endpoint_lists_allowlist() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/models", headers={"X-API-Key": "dev-secret-change-me"})

    assert response.status_code == 200
    body = response.json()
    assert body["default"] in body["models"]
    assert "claude-haiku-4-5" in body["models"]


def test_tiktok_accepts_valid_model() -> None:
    app = create_app()
    use_case = RecordingCaptionUseCase()
    app.dependency_overrides[get_generate_caption_use_case] = lambda: use_case
    client = TestClient(app)

    response = client.post(
        f"/api/v1/downloads/{uuid4()}/tiktok",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={"model": "claude-sonnet-5"},
    )

    assert response.status_code == 200
    assert use_case.model == "claude-sonnet-5"


def test_tiktok_rejects_unknown_model() -> None:
    client = TestClient(create_app())

    response = client.post(
        f"/api/v1/downloads/{uuid4()}/tiktok",
        headers={"X-API-Key": "dev-secret-change-me"},
        json={"model": "gpt-4"},
    )

    assert response.status_code == 400


def test_delete_download_returns_204() -> None:
    app = create_app()
    use_case = RecordingDeleteUseCase()
    app.dependency_overrides[get_delete_download_use_case] = lambda: use_case
    client = TestClient(app)

    response = client.delete(
        f"/api/v1/downloads/{uuid4()}",
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 204
    assert len(use_case.deleted) == 1
