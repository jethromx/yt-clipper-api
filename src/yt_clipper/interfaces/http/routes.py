from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse

from yt_clipper.application.use_cases import (
    CreateDownloadCommand,
    CreateDownloadUseCase,
    GetDownloadUseCase,
)
from yt_clipper.domain.exceptions import DomainError
from yt_clipper.domain.video import DownloadStatus
from yt_clipper.interfaces.http.dependencies import (
    configured_storage_dir,
    get_create_download_use_case,
    get_get_download_use_case,
    require_api_key,
)
from yt_clipper.interfaces.http.schemas import CreateDownloadRequest, DownloadJobResponse

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_api_key)])


@router.post("/downloads", response_model=DownloadJobResponse, status_code=status.HTTP_202_ACCEPTED)
def create_download(
    request: CreateDownloadRequest,
    use_case: CreateDownloadUseCase = Depends(get_create_download_use_case),
) -> DownloadJobResponse:
    try:
        job = use_case.execute(
            CreateDownloadCommand(
                source_url=str(request.source_url),
                start_seconds=request.start_seconds,
                end_seconds=request.end_seconds,
            )
        )
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return DownloadJobResponse.from_domain(job)


@router.get("/downloads/{job_id}", response_model=DownloadJobResponse)
def get_download(
    job_id: UUID,
    use_case: GetDownloadUseCase = Depends(get_get_download_use_case),
) -> DownloadJobResponse:
    job = use_case.execute(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download job not found")
    return DownloadJobResponse.from_domain(job)


@router.get("/downloads/{job_id}/file", response_class=FileResponse)
def download_file(
    job_id: UUID,
    use_case: GetDownloadUseCase = Depends(get_get_download_use_case),
    storage_dir: Path = Depends(configured_storage_dir),
) -> FileResponse:
    job = use_case.execute(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Download job not found")
    if job.status != DownloadStatus.COMPLETED or not job.output_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Download is not completed",
        )
    path = Path(job.output_path)
    if not path.is_absolute():
        path = storage_dir / path
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Output file not found")
    return FileResponse(path, filename=path.name)


health_router = APIRouter()


@health_router.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready", include_in_schema=False)
def ready() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
