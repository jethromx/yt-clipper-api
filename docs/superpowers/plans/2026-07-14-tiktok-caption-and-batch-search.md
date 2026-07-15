# TikTok Caption + Batch Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir (A) captura de metadata de YouTube al descargar + generación de caption/hashtags TikTok con Claude, y (B) búsqueda de videos con yt-dlp + selección múltiple + descarga en lote encolada.

**Architecture:** Backend FastAPI hexagonal (`domain`/`application`/`infrastructure`/`interfaces/http`): se extienden entidades y puertos, se añaden casos de uso y adaptadores (yt-dlp search, Anthropic), y endpoints nuevos. Frontend React por capas (`domain`/`application`/`infrastructure`): tipos, cliente API, coordinador y UI.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, Celery, yt-dlp, Anthropic SDK, pytest. Frontend: React 18 + TypeScript + Vite + Vitest + Testing Library.

**Convención de comandos backend:** ejecutar desde `yt-clipper-api/` con el venv: `.venv/bin/python -m pytest ...`. Frontend desde `yt-clipper-studio/`: `npm run test ...`.

---

## Parte 1 — Backend (`yt-clipper-api`)

### Task 1: Dominio — value objects y campos nuevos

**Files:**
- Modify: `src/yt_clipper/domain/video.py`
- Modify: `src/yt_clipper/domain/exceptions.py`
- Test: `tests/unit/test_download_job.py`

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `tests/unit/test_download_job.py`:

```python
from datetime import datetime

from yt_clipper.domain.video import (
    DownloadJob,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)


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
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/test_download_job.py -q`
Expected: FAIL (ImportError: cannot import name `TikTokCaption`).

- [ ] **Step 3: Implementar en el dominio**

En `src/yt_clipper/domain/video.py`, reemplazar la clase `VideoMetadata` y añadir los value objects, y extender `DownloadJob`:

```python
@dataclass(frozen=True, slots=True)
class VideoMetadata:
    video_id: str
    title: str
    duration_seconds: float | None = None
    webpage_url: str | None = None
    description: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TikTokCaption:
    caption: str
    hashtags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class VideoSearchResult:
    video_id: str
    title: str
    url: str
    duration_seconds: float | None = None
    channel: str | None = None
    thumbnail_url: str | None = None
```

En la dataclass `DownloadJob`, añadir estos campos después de `error_message`:

```python
    video_title: str | None = None
    video_description: str | None = None
    youtube_tags: list[str] = field(default_factory=list)
    tiktok_caption: str | None = None
    tiktok_hashtags: list[str] = field(default_factory=list)
    tiktok_generated_at: datetime | None = None
```

Y añadir estos métodos a `DownloadJob`:

```python
    def apply_metadata(self, metadata: VideoMetadata) -> None:
        self.video_title = metadata.title
        self.video_description = metadata.description
        self.youtube_tags = list(metadata.tags)
        self.updated_at = datetime.now(UTC)

    def apply_tiktok_caption(self, caption: TikTokCaption) -> None:
        self.tiktok_caption = caption.caption
        self.tiktok_hashtags = list(caption.hashtags)
        self.tiktok_generated_at = datetime.now(UTC)
        self.updated_at = datetime.now(UTC)
```

- [ ] **Step 4: Añadir excepciones de dominio**

En `src/yt_clipper/domain/exceptions.py` añadir:

```python
class CaptionNotAvailableError(DomainError):
    """Raised when a job has no metadata to generate a caption from."""


class CaptionGeneratorUnavailableError(DomainError):
    """Raised when no AI caption generator is configured."""


class CaptionGenerationError(DomainError):
    """Raised when the AI provider fails to generate a caption."""


class EmptySearchQueryError(DomainError):
    """Raised when a search query is empty."""


class EmptyBatchError(DomainError):
    """Raised when a batch download request has no URLs."""


class BatchTooLargeError(DomainError):
    """Raised when a batch download request exceeds the allowed size."""
```

- [ ] **Step 5: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/test_download_job.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/yt_clipper/domain tests/unit/test_download_job.py
git commit -m "feat(domain): add metadata, tiktok caption and search value objects"
```

---

### Task 2: Puertos — CaptionGenerator, DownloadResult y firma de VideoProvider

**Files:**
- Modify: `src/yt_clipper/application/ports.py`

- [ ] **Step 1: Editar los puertos**

Reemplazar el contenido de `src/yt_clipper/application/ports.py` por:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from yt_clipper.domain.video import (
    ClipRange,
    DownloadJob,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    path: Path
    metadata: VideoMetadata


class DownloadJobRepository(Protocol):
    def add(self, job: DownloadJob) -> DownloadJob: ...

    def get(self, job_id: UUID) -> DownloadJob | None: ...

    def update(self, job: DownloadJob) -> DownloadJob: ...


class JobQueue(Protocol):
    def enqueue_download(self, job_id: UUID) -> None: ...


class VideoProvider(Protocol):
    def get_metadata(self, source_url: str) -> VideoMetadata: ...

    def download_best(self, source_url: str, output_dir: Path) -> DownloadResult: ...

    def search(self, query: str, limit: int) -> list[VideoSearchResult]: ...


class CaptionGenerator(Protocol):
    def generate(self, metadata: VideoMetadata) -> TikTokCaption: ...


class MediaProcessor(Protocol):
    def clip(self, input_path: Path, clip_range: ClipRange, output_path: Path) -> Path: ...


class FileStorage(Protocol):
    def prepare_download_path(self, job: DownloadJob) -> Path: ...

    def prepare_clip_path(self, job: DownloadJob, source_path: Path) -> Path: ...

    def cleanup_download_path(self, job: DownloadJob) -> None: ...

    def resolve(self, relative_path: str) -> Path: ...
```

- [ ] **Step 2: Verificar que compila (mypy)**

Run: `.venv/bin/python -m mypy`
Expected: puede reportar errores en `use_cases.py`/`ytdlp_provider.py` que resolveremos en las siguientes tasks. Confirmar que `ports.py` en sí no tiene errores de sintaxis/imports.

- [ ] **Step 3: Commit**

```bash
git add src/yt_clipper/application/ports.py
git commit -m "feat(ports): add CaptionGenerator, DownloadResult and search to VideoProvider"
```

---

### Task 3: Provider yt-dlp — metadata en download + search

**Files:**
- Modify: `src/yt_clipper/infrastructure/youtube/ytdlp_provider.py`
- Test: `tests/unit/test_ytdlp_provider.py`

- [ ] **Step 1: Escribir tests que fallan**

Revisar `tests/unit/test_ytdlp_provider.py` para conocer el patrón de mock actual. Añadir estos tests (ajustar el import del monkeypatch al patrón existente del archivo, que parchea `YoutubeDL`):

```python
from yt_clipper.application.ports import DownloadResult
from yt_clipper.domain.video import VideoSearchResult


def test_metadata_from_info_captures_description_and_tags() -> None:
    provider = YtDlpVideoProvider(socket_timeout_seconds=5)

    metadata = provider._metadata_from_info(
        {
            "id": "abc",
            "title": "Titulo",
            "duration": 10,
            "webpage_url": "https://youtu.be/abc",
            "description": "Desc",
            "tags": ["a", "b"],
        }
    )

    assert metadata.description == "Desc"
    assert metadata.tags == ["a", "b"]


def test_search_maps_entries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeYoutubeDL:
        def __init__(self, options):  # type: ignore[no-untyped-def]
            self.options = options

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

        def extract_info(self, query, download):  # type: ignore[no-untyped-def]
            assert query == "ytsearch2:perros"
            assert download is False
            return {
                "entries": [
                    {
                        "id": "abc",
                        "title": "Perro 1",
                        "duration": 12,
                        "channel": "Canal",
                        "thumbnails": [{"url": "https://i.ytimg.com/abc.jpg"}],
                    },
                    {"id": None, "title": "descartado"},
                ]
            }

    monkeypatch.setattr(
        "yt_clipper.infrastructure.youtube.ytdlp_provider.YoutubeDL", FakeYoutubeDL
    )
    provider = YtDlpVideoProvider(socket_timeout_seconds=5)

    results = provider.search("perros", limit=2)

    assert results == [
        VideoSearchResult(
            video_id="abc",
            title="Perro 1",
            url="https://www.youtube.com/watch?v=abc",
            duration_seconds=12,
            channel="Canal",
            thumbnail_url="https://i.ytimg.com/abc.jpg",
        )
    ]
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/test_ytdlp_provider.py -q`
Expected: FAIL (`search` no existe / `DownloadResult` no importable desde provider).

- [ ] **Step 3: Implementar en el provider**

En `src/yt_clipper/infrastructure/youtube/ytdlp_provider.py`:

1. Añadir imports:

```python
from yt_clipper.application.ports import DownloadResult
from yt_clipper.domain.video import VideoMetadata, VideoSearchResult
```

2. Reemplazar `download_best` para capturar metadata en la misma llamada:

```python
    def download_best(self, source_url: str, output_dir: Path) -> DownloadResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(title).120s-%(id)s.%(ext)s")
        options = {
            **self._base_options(),
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": output_template,
            "restrictfilenames": True,
            "noplaylist": True,
        }
        before = set(output_dir.iterdir())
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source_url, download=True)
        created_files = [
            path for path in output_dir.iterdir() if path not in before and path.is_file()
        ]
        if not created_files:
            raise RuntimeError("yt-dlp finished without creating an output file")
        newest = max(created_files, key=lambda path: path.stat().st_mtime)
        return DownloadResult(path=newest, metadata=self._metadata_from_info(info))
```

3. Extender `_metadata_from_info` para capturar `description` y `tags`:

```python
    @staticmethod
    def _metadata_from_info(info: dict[str, Any] | None) -> VideoMetadata:
        if not info:
            raise RuntimeError("yt-dlp did not return metadata")
        tags = info.get("tags") or []
        return VideoMetadata(
            video_id=str(info.get("id") or ""),
            title=str(info.get("title") or "untitled"),
            duration_seconds=info.get("duration"),
            webpage_url=info.get("webpage_url"),
            description=info.get("description"),
            tags=[str(tag) for tag in tags],
        )
```

4. Añadir el método `search`:

```python
    def search(self, query: str, limit: int) -> list[VideoSearchResult]:
        options = {
            **self._base_options(),
            "extract_flat": "in_playlist",
            "skip_download": True,
            "noplaylist": True,
        }
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(f"ytsearch{limit}:{query}", download=False)
        entries = (info or {}).get("entries") or []
        results: list[VideoSearchResult] = []
        for entry in entries:
            video_id = entry.get("id")
            if not video_id:
                continue
            results.append(
                VideoSearchResult(
                    video_id=str(video_id),
                    title=str(entry.get("title") or "untitled"),
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    duration_seconds=entry.get("duration"),
                    channel=entry.get("channel") or entry.get("uploader"),
                    thumbnail_url=self._first_thumbnail(entry),
                )
            )
        return results

    @staticmethod
    def _first_thumbnail(entry: dict[str, Any]) -> str | None:
        thumbnails = entry.get("thumbnails") or []
        if thumbnails:
            return thumbnails[-1].get("url")
        thumbnail = entry.get("thumbnail")
        return str(thumbnail) if thumbnail else None
```

Nota: en el test, `thumbnails[-1]` es el único elemento, por lo que devuelve `https://i.ytimg.com/abc.jpg`.

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/test_ytdlp_provider.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/infrastructure/youtube/ytdlp_provider.py tests/unit/test_ytdlp_provider.py
git commit -m "feat(ytdlp): capture metadata on download and add search"
```

---

### Task 4: Use case de descarga aplica metadata (+ actualizar fakes)

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_execute_download_job_use_case.py`

- [ ] **Step 1: Actualizar el fake y añadir test que falla**

En `tests/unit/application/test_execute_download_job_use_case.py`:

1. Actualizar `FakeVideoProvider` para devolver `DownloadResult`:

```python
from yt_clipper.application.ports import DownloadResult
from yt_clipper.domain.video import VideoMetadata


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
```

2. Añadir un test nuevo:

```python
def test_execute_download_job_applies_metadata() -> None:
    job = DownloadJob(source_url="https://www.youtube.com/watch?v=abc123")
    provider = FakeVideoProvider(
        Path("downloads/video.mp4"),
        metadata=VideoMetadata(
            video_id="abc", title="Titulo real", description="Desc", tags=["x"]
        ),
    )
    use_case = ExecuteDownloadJobUseCase(
        FakeRepository(job), provider, FakeMediaProcessor(), FakeStorage()
    )

    result = use_case.execute(job.id)

    assert result.video_title == "Titulo real"
    assert result.video_description == "Desc"
    assert result.youtube_tags == ["x"]
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/application/test_execute_download_job_use_case.py -q`
Expected: FAIL (el use case aún usa el Path directo y no aplica metadata).

- [ ] **Step 3: Implementar en el use case**

En `src/yt_clipper/application/use_cases.py`, dentro de `ExecuteDownloadJobUseCase.execute`, reemplazar el bloque `try`:

```python
        try:
            result = self.video_provider.download_best(
                job.source_url,
                self.storage.prepare_download_path(job),
            )
            job.apply_metadata(result.metadata)
            output_path = self._clip_if_needed(job, result.path)
            job.mark_completed(str(output_path))
        except Exception as exc:
            job.mark_failed(str(exc))
            with suppress(Exception):
                self.storage.cleanup_download_path(job)
            self.repository.update(job)
            raise
```

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/application/test_execute_download_job_use_case.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_execute_download_job_use_case.py
git commit -m "feat(usecase): apply youtube metadata to completed jobs"
```

---

### Task 5: Use cases de search y batch

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_search_and_batch_use_cases.py` (crear)

- [ ] **Step 1: Escribir tests que fallan**

Crear `tests/unit/application/test_search_and_batch_use_cases.py`:

```python
from uuid import UUID

import pytest

from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    SearchVideosUseCase,
)
from yt_clipper.domain.exceptions import (
    BatchTooLargeError,
    EmptyBatchError,
    EmptySearchQueryError,
)
from yt_clipper.domain.video import DownloadJob, VideoSearchResult


class FakeRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, DownloadJob] = {}

    def add(self, job: DownloadJob) -> DownloadJob:
        self.jobs[job.id] = job
        return job

    def get(self, job_id: UUID) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def update(self, job: DownloadJob) -> DownloadJob:
        self.jobs[job.id] = job
        return job


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[UUID] = []

    def enqueue_download(self, job_id: UUID) -> None:
        self.enqueued.append(job_id)


class FakeSearchProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[VideoSearchResult]:
        self.calls.append((query, limit))
        return [VideoSearchResult(video_id="abc", title="t", url="u")]


def test_search_clamps_limit_and_delegates() -> None:
    provider = FakeSearchProvider()
    use_case = SearchVideosUseCase(provider)

    results = use_case.execute("perros", limit=999)

    assert provider.calls == [("perros", 50)]
    assert len(results) == 1


def test_search_rejects_empty_query() -> None:
    with pytest.raises(EmptySearchQueryError):
        SearchVideosUseCase(FakeSearchProvider()).execute("   ", limit=10)


def test_batch_creates_and_enqueues_jobs() -> None:
    repository = FakeRepository()
    queue = FakeQueue()
    use_case = CreateDownloadBatchUseCase(repository, queue)

    jobs = use_case.execute(["https://youtu.be/a", "https://youtu.be/b"])

    assert len(jobs) == 2
    assert len(queue.enqueued) == 2
    assert all(job.clip_range is None for job in jobs)


def test_batch_rejects_empty_list() -> None:
    with pytest.raises(EmptyBatchError):
        CreateDownloadBatchUseCase(FakeRepository(), FakeQueue()).execute([])


def test_batch_rejects_oversized_list() -> None:
    urls = [f"https://youtu.be/{i}" for i in range(51)]
    with pytest.raises(BatchTooLargeError):
        CreateDownloadBatchUseCase(FakeRepository(), FakeQueue()).execute(urls)
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/application/test_search_and_batch_use_cases.py -q`
Expected: FAIL (ImportError de los use cases nuevos).

- [ ] **Step 3: Implementar los use cases**

En `src/yt_clipper/application/use_cases.py`:

1. Ampliar imports:

```python
from yt_clipper.application.ports import (
    CaptionGenerator,
    DownloadJobRepository,
    FileStorage,
    JobQueue,
    MediaProcessor,
    VideoProvider,
)
from yt_clipper.domain.exceptions import (
    BatchTooLargeError,
    CaptionNotAvailableError,
    DomainError,
    EmptyBatchError,
    EmptySearchQueryError,
    InvalidClipRangeError,
)
from yt_clipper.domain.video import (
    ClipRange,
    DownloadJob,
    DownloadStatus,
    TikTokCaption,
    VideoMetadata,
    VideoSearchResult,
)
```

2. Añadir constante y use cases al final del archivo:

```python
MAX_BATCH_SIZE = 50
MAX_SEARCH_LIMIT = 50


class SearchVideosUseCase:
    def __init__(self, video_provider: VideoProvider) -> None:
        self.video_provider = video_provider

    def execute(self, query: str, limit: int) -> list[VideoSearchResult]:
        if not query.strip():
            raise EmptySearchQueryError("query must not be empty")
        bounded = max(1, min(limit, MAX_SEARCH_LIMIT))
        return self.video_provider.search(query.strip(), bounded)


class CreateDownloadBatchUseCase:
    def __init__(self, repository: DownloadJobRepository, queue: JobQueue) -> None:
        self.repository = repository
        self.queue = queue

    def execute(self, source_urls: list[str]) -> list[DownloadJob]:
        if not source_urls:
            raise EmptyBatchError("source_urls must not be empty")
        if len(source_urls) > MAX_BATCH_SIZE:
            raise BatchTooLargeError(f"batch exceeds {MAX_BATCH_SIZE} items")
        jobs: list[DownloadJob] = []
        for source_url in source_urls:
            job = DownloadJob(source_url=source_url)
            self.repository.add(job)
            self.queue.enqueue_download(job.id)
            jobs.append(job)
        return jobs
```

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/application/test_search_and_batch_use_cases.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_search_and_batch_use_cases.py
git commit -m "feat(usecase): add search and batch download use cases"
```

---

### Task 6: Use case de generación de caption TikTok

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_generate_tiktok_caption_use_case.py` (crear)

- [ ] **Step 1: Escribir tests que fallan**

Crear `tests/unit/application/test_generate_tiktok_caption_use_case.py`:

```python
from uuid import uuid4

import pytest

from yt_clipper.application.use_cases import GenerateTikTokCaptionUseCase
from yt_clipper.domain.exceptions import CaptionNotAvailableError, DomainError
from yt_clipper.domain.video import DownloadJob, TikTokCaption, VideoMetadata


class FakeRepository:
    def __init__(self, job: DownloadJob | None = None) -> None:
        self.jobs = {job.id: job} if job else {}
        self.updated = []

    def add(self, job): self.jobs[job.id] = job; return job  # noqa: E704
    def get(self, job_id): return self.jobs.get(job_id)  # noqa: E704

    def update(self, job):
        self.updated.append(job)
        self.jobs[job.id] = job
        return job


class FakeGenerator:
    def __init__(self) -> None:
        self.seen: VideoMetadata | None = None

    def generate(self, metadata: VideoMetadata) -> TikTokCaption:
        self.seen = metadata
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
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/application/test_generate_tiktok_caption_use_case.py -q`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implementar el use case**

Añadir al final de `src/yt_clipper/application/use_cases.py`:

```python
class GenerateTikTokCaptionUseCase:
    def __init__(
        self,
        repository: DownloadJobRepository,
        generator: CaptionGenerator,
    ) -> None:
        self.repository = repository
        self.generator = generator

    def execute(self, job_id: UUID) -> DownloadJob:
        job = self.repository.get(job_id)
        if job is None:
            raise DomainError(f"download job not found: {job_id}")
        if job.status != DownloadStatus.COMPLETED or not job.video_title:
            raise CaptionNotAvailableError(
                "caption requires a completed job with video metadata"
            )
        title = job.video_title  # narrowed to str by the guard above
        metadata = VideoMetadata(
            video_id="",
            title=title,
            description=job.video_description,
            tags=list(job.youtube_tags),
        )
        caption = self.generator.generate(metadata)
        job.apply_tiktok_caption(caption)
        self.repository.update(job)
        return job
```

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/application/test_generate_tiktok_caption_use_case.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_generate_tiktok_caption_use_case.py
git commit -m "feat(usecase): add tiktok caption generation use case"
```

---

### Task 7: Config y dependencia anthropic

**Files:**
- Modify: `src/yt_clipper/config.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Añadir test que falla**

Añadir a `tests/unit/test_config.py`:

```python
def test_settings_expose_anthropic_defaults() -> None:
    from yt_clipper.config import Settings

    settings = Settings()

    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-haiku-4-5"
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -q`
Expected: FAIL (AttributeError).

- [ ] **Step 3: Implementar**

En `src/yt_clipper/config.py`, dentro de `Settings`, añadir después de `celery_task_always_eager`:

```python
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-4-5"
```

En `pyproject.toml`, añadir a `dependencies` (lista principal):

```toml
    "anthropic>=0.40.0",
```

- [ ] **Step 4: Instalar dependencia**

Run: `.venv/bin/python -m pip install -e '.[dev]'`
Expected: instala `anthropic` sin errores.

- [ ] **Step 5: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/yt_clipper/config.py pyproject.toml
git commit -m "feat(config): add anthropic settings and dependency"
```

---

### Task 8: Adaptadores de caption (Anthropic + Unavailable)

**Files:**
- Create: `src/yt_clipper/infrastructure/ai/__init__.py`
- Create: `src/yt_clipper/infrastructure/ai/anthropic_caption.py`
- Test: `tests/unit/test_anthropic_caption.py` (crear)

- [ ] **Step 1: Escribir tests que fallan**

Crear `tests/unit/test_anthropic_caption.py`:

```python
import pytest

from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
)
from yt_clipper.domain.video import VideoMetadata
from yt_clipper.infrastructure.ai.anthropic_caption import (
    AnthropicCaptionGenerator,
    UnavailableCaptionGenerator,
)


class _Block:
    def __init__(self, name, data):  # type: ignore[no-untyped-def]
        self.type = "tool_use"
        self.name = name
        self.input = data


class _Response:
    def __init__(self, blocks):  # type: ignore[no-untyped-def]
        self.content = blocks


class FakeMessages:
    def __init__(self, response=None, raises=None):  # type: ignore[no-untyped-def]
        self._response = response
        self._raises = raises
        self.kwargs = None

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        if self._raises:
            raise self._raises
        return self._response


class FakeClient:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self.messages = messages


def _metadata() -> VideoMetadata:
    return VideoMetadata(video_id="abc", title="Titulo", description="Desc", tags=["x"])


def test_unavailable_generator_raises() -> None:
    with pytest.raises(CaptionGeneratorUnavailableError):
        UnavailableCaptionGenerator().generate(_metadata())


def test_anthropic_generator_parses_tool_use() -> None:
    response = _Response(
        [
            _Block(
                "emit_tiktok_caption",
                {"caption": "Mira esto ", "hashtags": ["viral", "#viral", "perros"]},
            )
        ]
    )
    client = FakeClient(FakeMessages(response=response))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    caption = generator.generate(_metadata())

    assert caption.caption == "Mira esto"
    assert caption.hashtags == ["#viral", "#perros"]


def test_anthropic_generator_wraps_sdk_errors() -> None:
    client = FakeClient(FakeMessages(raises=RuntimeError("boom")))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    with pytest.raises(CaptionGenerationError):
        generator.generate(_metadata())


def test_anthropic_generator_errors_when_no_tool_use() -> None:
    client = FakeClient(FakeMessages(response=_Response([])))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    with pytest.raises(CaptionGenerationError):
        generator.generate(_metadata())
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/test_anthropic_caption.py -q`
Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementar los adaptadores**

Crear `src/yt_clipper/infrastructure/ai/__init__.py` vacío.

Crear `src/yt_clipper/infrastructure/ai/anthropic_caption.py`:

```python
from __future__ import annotations

from typing import Any

from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
)
from yt_clipper.domain.video import TikTokCaption, VideoMetadata

_TOOL_NAME = "emit_tiktok_caption"
_MAX_CAPTION_CHARS = 150
_MAX_HASHTAGS = 8
_MAX_DESCRIPTION_CHARS = 1000

_SYSTEM_PROMPT = (
    "Eres un experto en marketing de TikTok. Escribes descripciones cortas, "
    "con gancho, en espanol neutro, y hashtags relevantes. Responde SIEMPRE "
    "usando la herramienta emit_tiktok_caption."
)

_TOOL = {
    "name": _TOOL_NAME,
    "description": "Devuelve la descripcion corta y los hashtags para TikTok.",
    "input_schema": {
        "type": "object",
        "properties": {
            "caption": {
                "type": "string",
                "description": "Descripcion corta en espanol, maximo 150 caracteres.",
            },
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entre 6 y 8 hashtags en espanol.",
            },
        },
        "required": ["caption", "hashtags"],
    },
}


class UnavailableCaptionGenerator:
    def generate(self, metadata: VideoMetadata) -> TikTokCaption:
        raise CaptionGeneratorUnavailableError(
            "Configura ANTHROPIC_API_KEY para generar captions de TikTok"
        )


class AnthropicCaptionGenerator:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        if client is not None:
            self._client = client
        else:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, metadata: VideoMetadata) -> TikTokCaption:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": self._build_prompt(metadata)}],
            )
        except Exception as exc:  # SDK/red
            raise CaptionGenerationError(str(exc)) from exc

        payload = self._extract_tool_input(response)
        caption = str(payload.get("caption") or "").strip()[:_MAX_CAPTION_CHARS]
        hashtags = self._normalize_hashtags(payload.get("hashtags") or [])
        if not caption:
            raise CaptionGenerationError("El proveedor no devolvio caption")
        return TikTokCaption(caption=caption, hashtags=hashtags)

    @staticmethod
    def _build_prompt(metadata: VideoMetadata) -> str:
        description = (metadata.description or "")[:_MAX_DESCRIPTION_CHARS]
        tags = ", ".join(metadata.tags[:20])
        return (
            "Genera una descripcion corta y hashtags para TikTok a partir de este "
            f"video de YouTube.\nTitulo: {metadata.title}\n"
            f"Descripcion: {description}\nTags: {tags}"
        )

    @staticmethod
    def _extract_tool_input(response: Any) -> dict[str, Any]:
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "tool_use" and block.name == _TOOL_NAME:
                return dict(block.input)
        raise CaptionGenerationError("El proveedor no uso la herramienta esperada")

    @staticmethod
    def _normalize_hashtags(raw: list[Any]) -> list[str]:
        seen: list[str] = []
        for item in raw:
            tag = str(item).strip().replace(" ", "")
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = f"#{tag}"
            if tag.lower() not in {existing.lower() for existing in seen}:
                seen.append(tag)
            if len(seen) >= _MAX_HASHTAGS:
                break
        return seen
```

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/test_anthropic_caption.py -q`
Expected: PASS (nota: en `test_anthropic_generator_parses_tool_use`, "viral" y "#viral" colapsan a uno solo → `["#viral", "#perros"]`).

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/infrastructure/ai tests/unit/test_anthropic_caption.py
git commit -m "feat(ai): add anthropic and unavailable caption generators"
```

---

### Task 9: Persistencia — columnas, mapping y migración

**Files:**
- Modify: `src/yt_clipper/infrastructure/persistence/models.py`
- Modify: `src/yt_clipper/infrastructure/persistence/repositories.py`
- Create: `migrations/versions/0002_add_metadata_and_tiktok_fields.py`
- Test: `tests/unit/test_repository.py`

- [ ] **Step 1: Añadir test que falla**

Revisar `tests/unit/test_repository.py` para el patrón de sesión in-memory. Añadir un test de round-trip de los campos nuevos (ajustar el fixture de sesión al existente en el archivo):

```python
from yt_clipper.domain.video import TikTokCaption, VideoMetadata


def test_repository_round_trips_metadata_and_tiktok(session) -> None:  # type: ignore[no-untyped-def]
    from yt_clipper.domain.video import DownloadJob
    from yt_clipper.infrastructure.persistence.repositories import (
        SqlAlchemyDownloadJobRepository,
    )

    repo = SqlAlchemyDownloadJobRepository(session)
    job = DownloadJob(source_url="https://youtu.be/abc")
    job.apply_metadata(VideoMetadata(video_id="abc", title="T", description="D", tags=["a"]))
    job.apply_tiktok_caption(TikTokCaption(caption="C", hashtags=["#a"]))
    repo.add(job)

    loaded = repo.get(job.id)

    assert loaded is not None
    assert loaded.video_title == "T"
    assert loaded.youtube_tags == ["a"]
    assert loaded.tiktok_caption == "C"
    assert loaded.tiktok_hashtags == ["#a"]
    assert loaded.tiktok_generated_at is not None
```

Nota: si `tests/unit/test_repository.py` no tiene un fixture `session`, replicar el patrón de creación de sesión/tabla ya usado en ese archivo (crea el engine sqlite en memoria y `Base.metadata.create_all`).

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/unit/test_repository.py -q`
Expected: FAIL (columnas/atributos inexistentes).

- [ ] **Step 3: Añadir columnas al modelo**

En `src/yt_clipper/infrastructure/persistence/models.py`, actualizar imports y añadir columnas:

```python
from sqlalchemy import JSON, DateTime, Float, String, Text
```

Dentro de `DownloadJobRecord`, tras `error_message`:

```python
    video_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    youtube_tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tiktok_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    tiktok_hashtags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    tiktok_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 4: Mapear en el repositorio**

En `src/yt_clipper/infrastructure/persistence/repositories.py`:

En `_sync_record`, añadir tras `record.error_message = job.error_message`:

```python
        record.video_title = job.video_title
        record.video_description = job.video_description
        record.youtube_tags = list(job.youtube_tags)
        record.tiktok_caption = job.tiktok_caption
        record.tiktok_hashtags = list(job.tiktok_hashtags)
        record.tiktok_generated_at = job.tiktok_generated_at
```

En `_to_domain`, extender el constructor de `DownloadJob`:

```python
        return DownloadJob(
            id=UUID(record.id),
            source_url=record.source_url,
            clip_range=clip_range,
            status=DownloadStatus(record.status),
            output_path=record.output_path,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
            video_title=record.video_title,
            video_description=record.video_description,
            youtube_tags=list(record.youtube_tags or []),
            tiktok_caption=record.tiktok_caption,
            tiktok_hashtags=list(record.tiktok_hashtags or []),
            tiktok_generated_at=record.tiktok_generated_at,
        )
```

- [ ] **Step 5: Crear la migración Alembic**

Crear `migrations/versions/0002_add_metadata_and_tiktok_fields.py`:

```python
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
```

- [ ] **Step 6: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/unit/test_repository.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/yt_clipper/infrastructure/persistence migrations/versions/0002_add_metadata_and_tiktok_fields.py tests/unit/test_repository.py
git commit -m "feat(persistence): persist metadata and tiktok caption fields"
```

---

### Task 10: Schemas HTTP

**Files:**
- Modify: `src/yt_clipper/interfaces/http/schemas.py`

- [ ] **Step 1: Extender DownloadJobResponse y añadir schemas nuevos**

Reemplazar `src/yt_clipper/interfaces/http/schemas.py` por:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

from yt_clipper.domain.video import DownloadJob, DownloadStatus, VideoSearchResult


class CreateDownloadRequest(BaseModel):
    source_url: HttpUrl
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_clip_bounds(self) -> "CreateDownloadRequest":
        if (self.start_seconds is None) != (self.end_seconds is None):
            raise ValueError("start_seconds and end_seconds must be provided together")
        return self


class DownloadJobResponse(BaseModel):
    id: UUID
    source_url: str
    status: DownloadStatus
    start_seconds: float | None
    end_seconds: float | None
    output_path: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    video_title: str | None
    video_description: str | None
    youtube_tags: list[str]
    tiktok_caption: str | None
    tiktok_hashtags: list[str]
    tiktok_generated_at: datetime | None

    @classmethod
    def from_domain(cls, job: DownloadJob) -> "DownloadJobResponse":
        return cls(
            id=job.id,
            source_url=job.source_url,
            status=job.status,
            start_seconds=job.clip_range.start_seconds if job.clip_range else None,
            end_seconds=job.clip_range.end_seconds if job.clip_range else None,
            output_path=job.output_path,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
            video_title=job.video_title,
            video_description=job.video_description,
            youtube_tags=list(job.youtube_tags),
            tiktok_caption=job.tiktok_caption,
            tiktok_hashtags=list(job.tiktok_hashtags),
            tiktok_generated_at=job.tiktok_generated_at,
        )


class BatchDownloadRequest(BaseModel):
    source_urls: list[HttpUrl] = Field(min_length=1, max_length=50)


class BatchDownloadResponse(BaseModel):
    jobs: list[DownloadJobResponse]


class SearchResultResponse(BaseModel):
    video_id: str
    title: str
    url: str
    duration_seconds: float | None
    channel: str | None
    thumbnail_url: str | None

    @classmethod
    def from_domain(cls, result: VideoSearchResult) -> "SearchResultResponse":
        return cls(
            video_id=result.video_id,
            title=result.title,
            url=result.url,
            duration_seconds=result.duration_seconds,
            channel=result.channel,
            thumbnail_url=result.thumbnail_url,
        )


class SearchResponse(BaseModel):
    results: list[SearchResultResponse]
```

- [ ] **Step 2: Verificar imports/tipos**

Run: `.venv/bin/python -m mypy`
Expected: sin errores nuevos en `schemas.py` (puede haber pendientes en `routes.py`/`dependencies.py` hasta la Task 12).

- [ ] **Step 3: Commit**

```bash
git add src/yt_clipper/interfaces/http/schemas.py
git commit -m "feat(schemas): extend job response and add search/batch schemas"
```

---

### Task 11: Dependencias HTTP (wiring de use cases nuevos)

**Files:**
- Modify: `src/yt_clipper/interfaces/http/dependencies.py`

- [ ] **Step 1: Añadir factorías de dependencia**

En `src/yt_clipper/interfaces/http/dependencies.py`:

1. Ampliar imports:

```python
from yt_clipper.application.ports import CaptionGenerator
from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    CreateDownloadUseCase,
    GenerateTikTokCaptionUseCase,
    GetDownloadUseCase,
    SearchVideosUseCase,
)
from yt_clipper.infrastructure.ai.anthropic_caption import (
    AnthropicCaptionGenerator,
    UnavailableCaptionGenerator,
)
from yt_clipper.infrastructure.youtube.ytdlp_provider import YtDlpVideoProvider
```

2. Añadir factorías:

```python
def get_video_provider(settings: Settings = Depends(get_settings)) -> YtDlpVideoProvider:
    return YtDlpVideoProvider(settings.ytdlp_socket_timeout_seconds)


def get_search_use_case(
    provider: YtDlpVideoProvider = Depends(get_video_provider),
) -> SearchVideosUseCase:
    return SearchVideosUseCase(provider)


def get_create_download_batch_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
) -> CreateDownloadBatchUseCase:
    return CreateDownloadBatchUseCase(repository, CeleryJobQueue())


def get_caption_generator(settings: Settings = Depends(get_settings)) -> CaptionGenerator:
    if not settings.anthropic_api_key:
        return UnavailableCaptionGenerator()
    return AnthropicCaptionGenerator(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
    )


def get_generate_caption_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
    generator: CaptionGenerator = Depends(get_caption_generator),
) -> GenerateTikTokCaptionUseCase:
    return GenerateTikTokCaptionUseCase(repository, generator)
```

- [ ] **Step 2: Verificar tipos**

Run: `.venv/bin/python -m mypy`
Expected: sin errores en `dependencies.py`.

- [ ] **Step 3: Commit**

```bash
git add src/yt_clipper/interfaces/http/dependencies.py
git commit -m "feat(http): wire search, batch and caption dependencies"
```

---

### Task 12: Rutas HTTP nuevas (+ tests de integración)

**Files:**
- Modify: `src/yt_clipper/interfaces/http/routes.py`
- Test: `tests/integration/test_http_api.py`

- [ ] **Step 1: Escribir tests de integración que fallan**

Añadir a `tests/integration/test_http_api.py` (usa `dependency_overrides` como los tests existentes):

```python
from yt_clipper.domain.exceptions import CaptionGeneratorUnavailableError, EmptySearchQueryError
from yt_clipper.domain.video import TikTokCaption, VideoMetadata, VideoSearchResult
from yt_clipper.interfaces.http.dependencies import (
    get_create_download_batch_use_case,
    get_generate_caption_use_case,
    get_search_use_case,
)


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
    def execute(self, job_id: UUID) -> DownloadJob:
        job = DownloadJob(source_url="https://youtu.be/abc")
        job.apply_metadata(VideoMetadata(video_id="abc", title="T"))
        job.mark_completed("out.mp4")
        job.apply_tiktok_caption(TikTokCaption(caption="Mira", hashtags=["#viral"]))
        return job


class UnavailableCaptionUseCase:
    def execute(self, job_id: UUID) -> DownloadJob:
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
        json={"source_urls": [
            "https://www.youtube.com/watch?v=a",
            "https://www.youtube.com/watch?v=b",
        ]},
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
```

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `.venv/bin/python -m pytest tests/integration/test_http_api.py -q`
Expected: FAIL (404 en rutas nuevas / imports inexistentes).

- [ ] **Step 3: Implementar las rutas**

En `src/yt_clipper/interfaces/http/routes.py`:

1. Ampliar imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from yt_clipper.application.use_cases import (
    CreateDownloadBatchUseCase,
    CreateDownloadCommand,
    CreateDownloadUseCase,
    GenerateTikTokCaptionUseCase,
    GetDownloadUseCase,
    SearchVideosUseCase,
)
from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
    CaptionNotAvailableError,
    DomainError,
)
from yt_clipper.interfaces.http.dependencies import (
    configured_storage_dir,
    get_create_download_batch_use_case,
    get_create_download_use_case,
    get_generate_caption_use_case,
    get_get_download_use_case,
    get_search_use_case,
    require_api_key,
)
from yt_clipper.interfaces.http.schemas import (
    BatchDownloadRequest,
    BatchDownloadResponse,
    CreateDownloadRequest,
    DownloadJobResponse,
    SearchResponse,
    SearchResultResponse,
)
```

2. Añadir rutas dentro del `router` (con prefijo `/api/v1`), tras `create_download`:

```python
@router.get("/search", response_model=SearchResponse)
def search_videos(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, ge=1, le=50),
    use_case: SearchVideosUseCase = Depends(get_search_use_case),
) -> SearchResponse:
    try:
        results = use_case.execute(q, limit)
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SearchResponse(results=[SearchResultResponse.from_domain(r) for r in results])


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


@router.post("/downloads/{job_id}/tiktok", response_model=DownloadJobResponse)
def generate_tiktok_caption(
    job_id: UUID,
    use_case: GenerateTikTokCaptionUseCase = Depends(get_generate_caption_use_case),
) -> DownloadJobResponse:
    try:
        job = use_case.execute(job_id)
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
```

Importante: la ruta `GET /search` debe declararse **antes** de `GET /downloads/{job_id}` (ya lo está, en distinto path) — no hay colisión porque los paths difieren. La ruta `/downloads/batch` debe declararse **antes** de `/downloads/{job_id}` para que "batch" no se interprete como un `job_id`. Colocar `create_download_batch` inmediatamente después de `create_download` y antes de `get_download`.

- [ ] **Step 4: Ejecutar tests**

Run: `.venv/bin/python -m pytest tests/integration/test_http_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yt_clipper/interfaces/http/routes.py tests/integration/test_http_api.py
git commit -m "feat(http): add search, batch and tiktok caption endpoints"
```

---

### Task 13: Verificación backend completa

- [ ] **Step 1: Suite completa + calidad**

Run:
```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```
Expected: todo PASS, cobertura ≥ 85%. Corregir lint/format/tipos que aparezcan (p. ej. `ruff format .` para autoformatear) y volver a ejecutar.

- [ ] **Step 2: Documentar variables en `.env.example`**

Añadir a `yt-clipper-api/.env.example` (si no existe la clave):

```dotenv
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-haiku-4-5
```

Nota: el usuario debe crear/editar `.env` manualmente (los archivos `.env` están bloqueados para las herramientas de edición en esta sesión).

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document anthropic env vars"
```

---

## Parte 2 — Frontend (`yt-clipper-studio`)

Comandos desde `yt-clipper-studio/`.

### Task 14: Tipos de dominio

**Files:**
- Modify: `src/domain/models.ts`

- [ ] **Step 1: Extender tipos**

En `src/domain/models.ts`:

1. En `BackendDownloadJob` añadir (tras `updated_at`):

```typescript
  video_title?: string | null
  video_description?: string | null
  youtube_tags?: string[] | null
  tiktok_caption?: string | null
  tiktok_hashtags?: string[] | null
  tiktok_generated_at?: string | null
```

2. En `PortfolioDownload` añadir (tras `updatedAt`):

```typescript
  videoTitle?: string
  videoDescription?: string
  youtubeTags?: string[]
  tiktokCaption?: string
  tiktokHashtags?: string[]
  tiktokGeneratedAt?: string
```

3. Añadir tipos nuevos al final:

```typescript
export interface VideoSearchResult {
  videoId: string
  title: string
  url: string
  durationSeconds?: number
  channel?: string
  thumbnailUrl?: string
}

export interface BackendSearchResult {
  video_id: string
  title: string
  url: string
  duration_seconds?: number | null
  channel?: string | null
  thumbnail_url?: string | null
}
```

- [ ] **Step 2: Verificar compilación de tipos**

Run: `npm run build`
Expected: TypeScript compila (puede fallar por usos aún no implementados; si falla solo por eso, continuar — se resuelve en tasks siguientes). Si compila, PASS.

- [ ] **Step 3: Commit**

```bash
git add src/domain/models.ts
git commit -m "feat(models): add metadata, tiktok and search types"
```

---

### Task 15: Cliente API — search, batch y caption

**Files:**
- Modify: `src/infrastructure/api/downloadApi.ts`
- Test: `src/infrastructure/api/downloadApi.test.ts`

- [ ] **Step 1: Escribir tests que fallan**

Revisar `downloadApi.test.ts` para el patrón de mock de `fetch`. Añadir:

```typescript
it('searchVideos maps backend results', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      results: [
        {
          video_id: 'abc',
          title: 'Perro',
          url: 'https://www.youtube.com/watch?v=abc',
          duration_seconds: 10,
          channel: 'Canal',
          thumbnail_url: 'https://i.ytimg.com/abc.jpg',
        },
      ],
    }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  const results = await client.searchVideos('perros', 5)

  expect(results[0]).toEqual({
    videoId: 'abc',
    title: 'Perro',
    url: 'https://www.youtube.com/watch?v=abc',
    durationSeconds: 10,
    channel: 'Canal',
    thumbnailUrl: 'https://i.ytimg.com/abc.jpg',
  })
  const [url] = fetchMock.mock.calls[0]
  expect(url).toContain('/api/v1/search?q=perros&limit=5')
})

it('createDownloadBatch posts urls and returns jobs', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ jobs: [{ id: '1', source_url: 'u', status: 'queued', created_at: 'x', updated_at: 'x' }] }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  const jobs = await client.createDownloadBatch(['https://youtu.be/a'])

  expect(jobs).toHaveLength(1)
  const [, init] = fetchMock.mock.calls[0]
  expect(JSON.parse(init.body)).toEqual({ source_urls: ['https://youtu.be/a'] })
})

it('generateTikTokCaption posts to the tiktok endpoint', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ id: '1', source_url: 'u', status: 'completed', created_at: 'x', updated_at: 'x', tiktok_caption: 'Mira', tiktok_hashtags: ['#viral'] }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  const job = await client.generateTikTokCaption('1')

  expect(job.tiktok_caption).toBe('Mira')
  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('http://api/api/v1/downloads/1/tiktok')
  expect(init.method).toBe('POST')
})
```

Nota: asegurar `import { vi } from 'vitest'` si el archivo no lo importa ya.

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `npm run test -- src/infrastructure/api/downloadApi.test.ts`
Expected: FAIL (métodos inexistentes).

- [ ] **Step 3: Implementar los métodos**

En `src/infrastructure/api/downloadApi.ts`:

1. Ampliar imports:

```typescript
import type {
  BackendDownloadJob,
  BackendSearchResult,
  CreateDownloadInput,
  VideoSearchResult,
} from '../../domain/models'
```

2. Añadir métodos a la clase `DownloadApiClient`:

```typescript
  async searchVideos(query: string, limit = 20): Promise<VideoSearchResult[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    const response = await fetch(`${this.baseUrl}/api/v1/search?${params.toString()}`, {
      headers: this.headers(),
    })
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await this.getErrorDetail(response)}`)
    }
    const body = (await response.json()) as { results: BackendSearchResult[] }
    return body.results.map((result) => ({
      videoId: result.video_id,
      title: result.title,
      url: result.url,
      durationSeconds: result.duration_seconds ?? undefined,
      channel: result.channel ?? undefined,
      thumbnailUrl: result.thumbnail_url ?? undefined,
    }))
  }

  async createDownloadBatch(sourceUrls: string[]): Promise<BackendDownloadJob[]> {
    const response = await fetch(`${this.baseUrl}/api/v1/downloads/batch`, {
      method: 'POST',
      headers: this.headers(),
      body: JSON.stringify({ source_urls: sourceUrls }),
    })
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await this.getErrorDetail(response)}`)
    }
    const body = (await response.json()) as { jobs: BackendDownloadJob[] }
    return body.jobs
  }

  async generateTikTokCaption(jobId: string): Promise<BackendDownloadJob> {
    const response = await fetch(`${this.baseUrl}/api/v1/downloads/${jobId}/tiktok`, {
      method: 'POST',
      headers: this.headers(),
    })
    return this.parseResponse(response)
  }
```

- [ ] **Step 4: Ejecutar tests**

Run: `npm run test -- src/infrastructure/api/downloadApi.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/infrastructure/api/downloadApi.ts src/infrastructure/api/downloadApi.test.ts
git commit -m "feat(api): add search, batch and tiktok caption client methods"
```

---

### Task 16: Coordinador — mapeo de campos, batch y refresh de caption

**Files:**
- Modify: `src/application/downloadCoordinator.ts`
- Test: `src/application/downloadCoordinator.test.ts`

- [ ] **Step 1: Escribir tests que fallan**

Añadir a `src/application/downloadCoordinator.test.ts`:

```typescript
import { createBatchDownloads, applyCaptionToPortfolio } from './downloadCoordinator'

it('createBatchDownloads adds one download per job as full kind', async () => {
  const repo = new InMemoryPortfolioRepository()
  const portfolio = {
    id: 'p1', name: 'X', createdAt: 'x', updatedAt: 'x', downloads: [],
  }
  repo.save(portfolio)
  const api = {
    createDownloadBatch: async (urls: string[]) =>
      urls.map((u, i) => ({ id: String(i), source_url: u, status: 'queued', created_at: 'x', updated_at: 'x' })),
  }

  const created = await createBatchDownloads('p1', ['https://a', 'https://b'], repo, api as never)

  expect(created).toHaveLength(2)
  expect(repo.getById('p1')!.downloads).toHaveLength(2)
  expect(repo.getById('p1')!.downloads[0].kind).toBe('full')
})

it('applyCaptionToPortfolio updates the matching download', () => {
  const repo = new InMemoryPortfolioRepository()
  const download = {
    id: 'd1', jobId: 'j1', sourceUrl: 'u', kind: 'full' as const, status: 'completed' as const,
    createdAt: 'x', updatedAt: 'x',
  }
  repo.save({ id: 'p1', name: 'X', createdAt: 'x', updatedAt: 'x', downloads: [download] })
  const job = {
    id: 'j1', source_url: 'u', status: 'completed' as const, created_at: 'x', updated_at: 'y',
    tiktok_caption: 'Mira', tiktok_hashtags: ['#viral'],
  }

  applyCaptionToPortfolio('p1', 'j1', job, repo)

  expect(repo.getById('p1')!.downloads[0].tiktokCaption).toBe('Mira')
  expect(repo.getById('p1')!.downloads[0].tiktokHashtags).toEqual(['#viral'])
})
```

Asegurar el import de `InMemoryPortfolioRepository` (desde `../test/fakes`) según el patrón del archivo.

- [ ] **Step 2: Ejecutar para ver que falla**

Run: `npm run test -- src/application/downloadCoordinator.test.ts`
Expected: FAIL (funciones inexistentes).

- [ ] **Step 3: Implementar en el coordinador**

En `src/application/downloadCoordinator.ts`:

1. Ampliar la interfaz `DownloadApi`:

```typescript
export interface DownloadApi {
  createDownload(input: CreateDownloadInput): Promise<BackendDownloadJob>
  getDownload(jobId: string): Promise<BackendDownloadJob>
  createDownloadBatch(sourceUrls: string[]): Promise<BackendDownloadJob[]>
}
```

2. Extender `mapBackendJob` para incluir los campos nuevos (añadir dentro del objeto retornado):

```typescript
    videoTitle: job.video_title ?? undefined,
    videoDescription: job.video_description ?? undefined,
    youtubeTags: job.youtube_tags ?? undefined,
    tiktokCaption: job.tiktok_caption ?? undefined,
    tiktokHashtags: job.tiktok_hashtags ?? undefined,
    tiktokGeneratedAt: job.tiktok_generated_at ?? undefined,
```

3. En `refreshPortfolioDownloads`, dentro del map para jobs no terminados, añadir al objeto retornado los campos de metadata/tiktok para que aparezcan cuando el job termina:

```typescript
      return {
        ...downloadItem,
        status: job.status,
        outputPath: job.output_path ?? undefined,
        errorMessage: job.error_message ?? undefined,
        updatedAt: job.updated_at,
        videoTitle: job.video_title ?? downloadItem.videoTitle,
        videoDescription: job.video_description ?? downloadItem.videoDescription,
        youtubeTags: job.youtube_tags ?? downloadItem.youtubeTags,
      }
```

4. Añadir las funciones nuevas al final del archivo:

```typescript
export async function createBatchDownloads(
  portfolioId: string,
  sourceUrls: string[],
  repository: PortfolioRepository,
  api: DownloadApi,
): Promise<PortfolioDownload[]> {
  const portfolio = repository.getById(portfolioId)
  if (!portfolio) {
    throw new Error('Portfolio no encontrado')
  }
  const jobs = await api.createDownloadBatch(sourceUrls)
  const created = jobs.map((job) => mapBackendJob(job, 'full'))
  repository.save({
    ...portfolio,
    updatedAt: new Date().toISOString(),
    downloads: [...created, ...portfolio.downloads],
  })
  return created
}

export function applyCaptionToPortfolio(
  portfolioId: string,
  jobId: string,
  job: BackendDownloadJob,
  repository: PortfolioRepository,
): void {
  const portfolio = repository.getById(portfolioId)
  if (!portfolio) {
    return
  }
  repository.save({
    ...portfolio,
    updatedAt: new Date().toISOString(),
    downloads: portfolio.downloads.map((item) =>
      item.jobId === jobId
        ? {
            ...item,
            tiktokCaption: job.tiktok_caption ?? undefined,
            tiktokHashtags: job.tiktok_hashtags ?? undefined,
            tiktokGeneratedAt: job.tiktok_generated_at ?? undefined,
          }
        : item,
    ),
  })
}
```

- [ ] **Step 4: Ejecutar tests**

Run: `npm run test -- src/application/downloadCoordinator.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/application/downloadCoordinator.ts src/application/downloadCoordinator.test.ts
git commit -m "feat(coordinator): map new fields, batch downloads and caption apply"
```

---

### Task 17: UI — búsqueda, selección múltiple y caption TikTok

**Files:**
- Modify: `src/App.tsx`
- Modify: `src/App.css`
- Test: `src/App.test.tsx`

- [ ] **Step 1: Revisar App.tsx y su test**

Leer `src/App.tsx` y `src/App.test.tsx` completos para conocer cómo se inyecta el `DownloadApiClient`/repositorio, cómo se renderiza el portfolio activo y sus descargas, y el patrón de los tests existentes (fakes de API, `render`, `screen`, `userEvent`).

- [ ] **Step 2: Escribir el test de flujo que falla**

Añadir a `src/App.test.tsx` un test del flujo buscar → seleccionar todos → descargar, usando un fake de API que implemente `searchVideos` y `createDownloadBatch` (seguir el patrón de fakes ya presente en el archivo). Estructura esperada:

```typescript
it('busca, selecciona todos y descarga en lote', async () => {
  const user = userEvent.setup()
  const api = {
    // ...métodos existentes que use App (createDownload, getDownload)...
    searchVideos: vi.fn().mockResolvedValue([
      { videoId: 'a', title: 'Video A', url: 'https://youtu.be/a' },
      { videoId: 'b', title: 'Video B', url: 'https://youtu.be/b' },
    ]),
    createDownloadBatch: vi.fn().mockResolvedValue([
      { id: '1', source_url: 'https://youtu.be/a', status: 'queued', created_at: 'x', updated_at: 'x' },
      { id: '2', source_url: 'https://youtu.be/b', status: 'queued', created_at: 'x', updated_at: 'x' },
    ]),
  }
  // render App con este api y un portfolio activo (seguir patrón del archivo)
  // crear/seleccionar portfolio si el test lo requiere

  await user.type(screen.getByPlaceholderText(/buscar/i), 'perros')
  await user.click(screen.getByRole('button', { name: /buscar/i }))

  expect(await screen.findByText('Video A')).toBeInTheDocument()

  await user.click(screen.getByRole('button', { name: /seleccionar todos/i }))
  await user.click(screen.getByRole('button', { name: /descargar/i }))

  expect(api.createDownloadBatch).toHaveBeenCalledWith(['https://youtu.be/a', 'https://youtu.be/b'])
})
```

Ajustar el render/monta del componente al patrón exacto que use el archivo (props, contexto o inyección directa del cliente).

- [ ] **Step 3: Ejecutar para ver que falla**

Run: `npm run test -- src/App.test.tsx`
Expected: FAIL (no existe la UI de búsqueda).

- [ ] **Step 4: Implementar la UI de búsqueda + selección + batch**

En `src/App.tsx`, dentro de la vista del portfolio activo, añadir:

- Estado: `searchQuery`, `searchResults: VideoSearchResult[]`, `selectedIds: Set<string>`, `searching`, `searchError`, `batching`.
- Un formulario de búsqueda: input `placeholder="Buscar videos en YouTube"` + botón "Buscar" que llama `api.searchVideos(searchQuery)` y guarda resultados (maneja error en `searchError`).
- Lista de resultados: por cada `VideoSearchResult`, una tarjeta con:
  - `<img src={result.thumbnailUrl} alt="" />` (si existe),
  - título (`result.title`), canal y duración,
  - un checkbox controlado por `selectedIds` (toggle por `videoId`).
- Botón "Seleccionar todos" que llena/vacía `selectedIds` con todos los `videoId`.
- Botón "Descargar N seleccionados" (deshabilitado si `selectedIds` vacío o `batching`) que:
  - calcula las URLs de los resultados seleccionados,
  - llama `createBatchDownloads(activePortfolioId, urls, repository, api)`,
  - refresca el portfolio en el estado, limpia selección/resultados.

Snippet de referencia para el handler batch:

```typescript
async function handleBatchDownload() {
  const urls = searchResults
    .filter((r) => selectedIds.has(r.videoId))
    .map((r) => r.url)
  if (urls.length === 0) return
  setBatching(true)
  try {
    await createBatchDownloads(activePortfolioId, urls, repository, api)
    reloadPortfolios()
    setSelectedIds(new Set())
    setSearchResults([])
  } catch (error) {
    setSearchError(error instanceof Error ? error.message : 'Error al descargar')
  } finally {
    setBatching(false)
  }
}
```

(`reloadPortfolios`/`activePortfolioId`/`repository`/`api` deben corresponder a los nombres reales del componente — ajustar al leer App.tsx.)

- [ ] **Step 5: Implementar la UI de caption TikTok por descarga**

En el render de cada `PortfolioDownload` completada:

- Si `download.videoDescription`, mostrar la descripción original recortada (p. ej. primeros 200 chars).
- Botón "Generar caption TikTok" (deshabilitado mientras `generatingId === download.jobId`) que:
  - llama `api.generateTikTokCaption(download.jobId)`,
  - en éxito: `applyCaptionToPortfolio(activePortfolioId, download.jobId, job, repository)` y `reloadPortfolios()`,
  - en error: mostrar el mensaje (el 503 trae "Configura ANTHROPIC_API_KEY...").
- Si `download.tiktokCaption`, mostrar la caption y `download.tiktokHashtags?.join(' ')`, con un botón "Copiar" que hace `navigator.clipboard.writeText(`${caption}\n${hashtags}`)`.

Snippet de referencia:

```typescript
async function handleGenerateCaption(jobId: string) {
  setGeneratingId(jobId)
  setCaptionError('')
  try {
    const job = await api.generateTikTokCaption(jobId)
    applyCaptionToPortfolio(activePortfolioId, jobId, job, repository)
    reloadPortfolios()
  } catch (error) {
    setCaptionError(error instanceof Error ? error.message : 'Error al generar caption')
  } finally {
    setGeneratingId(null)
  }
}
```

- [ ] **Step 6: Estilos mínimos**

En `src/App.css` añadir reglas para las tarjetas de resultados (miniatura, layout en grid/lista, checkbox alineado) y el bloque de caption. Mantener el estilo existente del proyecto.

- [ ] **Step 7: Ejecutar tests**

Run: `npm run test -- src/App.test.tsx`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/App.tsx src/App.css src/App.test.tsx
git commit -m "feat(ui): add search, multi-select batch download and tiktok caption"
```

---

### Task 18: Verificación frontend completa

- [ ] **Step 1: Lint + tests + build**

Run:
```bash
npm run lint
npm run test:coverage
npm run build
```
Expected: todo PASS, cobertura acorde a la config del proyecto. Corregir lo que aparezca.

- [ ] **Step 2: Commit (si hubo correcciones)**

```bash
git add -A
git commit -m "chore(frontend): fix lint/coverage after feature"
```

---

### Task 19: Verificación end-to-end con Docker

- [ ] **Step 1: Reconstruir el stack**

Desde `yt-clipper-api/` (con la corrección de puertos de esta sesión):

```bash
POSTGRES_PORT=5433 FRONTEND_PORT=8081 docker compose \
  -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.cors-8081.yml \
  up --build -d
```

- [ ] **Step 2: Migración aplicada**

Verificar en logs que la API ejecutó `alembic upgrade head` sin errores:
```bash
docker compose -f docker-compose.yml -f docker-compose.full.yml logs api | grep -i alembic
```
Expected: aplica `0002_add_metadata_and_tiktok_fields`.

- [ ] **Step 3: Probar búsqueda vía API**

```bash
curl -s -H 'X-API-Key: dev-secret-change-me' \
  'http://localhost:8000/api/v1/search?q=perros&limit=3' | head
```
Expected: JSON con `results` no vacío.

- [ ] **Step 4: Probar el flujo en el navegador**

Abrir `http://localhost:8081`: buscar, seleccionar varios/todos, descargar en lote, y (con `ANTHROPIC_API_KEY` configurada en `.env`) generar un caption TikTok en una descarga completada. Sin la key, verificar que el botón muestra el mensaje de "Configura ANTHROPIC_API_KEY".

- [ ] **Step 5: Marcar el plan como completado**

Actualizar el estado del spec/plan si aplica y confirmar con el usuario.

---

## Notas de cobertura y riesgos

- **Cobertura ≥ 85% backend**: los adaptadores (`AnthropicCaptionGenerator`, `search`, provider) tienen tests con fakes/mocks; el use case de caption se prueba con un generador fake; los endpoints con `dependency_overrides`. La rama real de construcción del cliente Anthropic (`import anthropic`) no se ejecuta en tests — si baja la cobertura, añadir un test que instancie `AnthropicCaptionGenerator(model=..., client=FakeClient(...))` (ya cubierto) y, si hace falta, marcar la rama del `import` con `# pragma: no cover`.
- **Orden de rutas**: `/downloads/batch` antes de `/downloads/{job_id}` para evitar captura de path param.
- **`.env` bloqueado**: documentar variables en `.env.example`; el usuario edita `.env`.
