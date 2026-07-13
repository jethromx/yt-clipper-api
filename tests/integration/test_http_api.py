from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from yt_clipper.application.use_cases import CreateDownloadCommand
from yt_clipper.domain.exceptions import DomainError
from yt_clipper.domain.video import DownloadJob, DownloadStatus
from yt_clipper.interfaces.http.dependencies import (
    configured_storage_dir,
    get_create_download_use_case,
    get_get_download_use_case,
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
