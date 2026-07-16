from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    CreateDownloadCommand,
    CreateDownloadUseCase,
    DeleteDownloadUseCase,
    GenerateTikTokCaptionUseCase,
    GetDownloadUseCase,
    GetSearchSuggestionsUseCase,
    SearchVideosUseCase,
)
from yt_clipper.config import Settings, get_settings
from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
    CaptionNotAvailableError,
    DomainError,
    TrendsError,
    TrendsUnavailableError,
)
from yt_clipper.domain.video import DownloadStatus
from yt_clipper.interfaces.http.dependencies import (
    configured_storage_dir,
    get_create_download_batch_use_case,
    get_create_download_use_case,
    get_delete_download_use_case,
    get_generate_caption_use_case,
    get_get_download_use_case,
    get_search_use_case,
    get_suggestions_use_case,
    require_api_key,
)
from yt_clipper.interfaces.http.schemas import (
    BatchDownloadRequest,
    BatchDownloadResponse,
    CreateDownloadRequest,
    DownloadJobResponse,
    GenerateCaptionRequest,
    ModelsResponse,
    SearchResponse,
    SearchResultResponse,
    SuggestionResponse,
    SuggestionsResponse,
)

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


@router.get("/search", response_model=SearchResponse)
def search_videos(
    q: str = Query(...),
    limit: int = Query(default=20, ge=1, le=50),
    max_duration_seconds: int | None = Query(default=None, ge=1),
    use_case: SearchVideosUseCase = Depends(get_search_use_case),
) -> SearchResponse:
    try:
        results = use_case.execute(q, limit, max_duration_seconds=max_duration_seconds)
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SearchResponse(results=[SearchResultResponse.from_domain(r) for r in results])


@router.get("/models", response_model=ModelsResponse)
def list_models(settings: Settings = Depends(get_settings)) -> ModelsResponse:
    return ModelsResponse(
        models=list(settings.anthropic_allowed_models),
        default=settings.anthropic_model,
    )


@router.get("/suggestions", response_model=SuggestionsResponse)
def list_suggestions(
    region: str | None = Query(default=None),
    limit: int = Query(default=15, ge=1, le=30),
    use_case: GetSearchSuggestionsUseCase = Depends(get_suggestions_use_case),
    settings: Settings = Depends(get_settings),
) -> SuggestionsResponse:
    region_value = region or settings.trends_region
    try:
        suggestions = use_case.execute(region_value, limit)
    except TrendsUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except TrendsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SuggestionsResponse(
        suggestions=[SuggestionResponse(text=s.text, kind=s.kind) for s in suggestions]
    )


@router.post(
    "/downloads/batch",
    response_model=BatchDownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_download_batch(
    request: BatchDownloadRequest,
    use_case: CreateDownloadBatchUseCase = Depends(get_create_download_batch_use_case),
) -> BatchDownloadResponse:
    try:
        jobs = use_case.execute([str(url) for url in request.source_urls])
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return BatchDownloadResponse(jobs=[DownloadJobResponse.from_domain(job) for job in jobs])


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


@router.delete("/downloads/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_download(
    job_id: UUID,
    use_case: DeleteDownloadUseCase = Depends(get_delete_download_use_case),
) -> Response:
    use_case.execute(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/downloads/{job_id}/tiktok", response_model=DownloadJobResponse)
def generate_tiktok_caption(
    job_id: UUID,
    request: GenerateCaptionRequest | None = None,
    use_case: GenerateTikTokCaptionUseCase = Depends(get_generate_caption_use_case),
    settings: Settings = Depends(get_settings),
) -> DownloadJobResponse:
    model = request.model if request else None
    if model is not None and model not in settings.anthropic_allowed_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported model: {model}",
        )
    try:
        job = use_case.execute(job_id, model=model)
    except CaptionGeneratorUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except CaptionNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except CaptionGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DownloadJobResponse.from_domain(job)


health_router = APIRouter()


@health_router.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/ready", include_in_schema=False)
def ready() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
