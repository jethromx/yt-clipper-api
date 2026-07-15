# Model Selector + Project Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hacer el modelo de Claude configurable desde el frontend (global + override por video, con allowlist en backend) y borrar los videos (archivos + jobs) al borrar un proyecto o un video individual.

**Architecture:** Backend FastAPI hexagonal: se amplía el puerto `CaptionGenerator.generate` con `model`, se añade `DownloadJobRepository.delete`, un `DeleteDownloadUseCase`, endpoints `GET /models` y `DELETE /downloads/{job_id}`, y validación de allowlist en la capa HTTP. Frontend React: cliente API + coordinador + UI con selectores de modelo y borrado.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Celery, Anthropic SDK, pytest. Frontend: React 18 + TS + Vite + Vitest + Testing Library.

**Comandos:** backend desde `yt-clipper-api/` con `.venv/bin/python`; frontend desde `yt-clipper-studio/` con `npm`.

---

## Parte 1 — Backend (`yt-clipper-api`)

### Task 1: Config — allowlist de modelos

**Files:**
- Modify: `src/yt_clipper/config.py`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Test que falla** — añadir a `tests/unit/test_config.py`:

```python
def test_settings_expose_allowed_models() -> None:
    from yt_clipper.config import Settings

    settings = Settings()

    assert settings.anthropic_model in settings.anthropic_allowed_models
    assert "claude-haiku-4-5" in settings.anthropic_allowed_models
    assert "claude-sonnet-5" in settings.anthropic_allowed_models
    assert "claude-opus-4-8" in settings.anthropic_allowed_models
```

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/test_config.py -q` → FAIL (AttributeError).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/config.py`:

Añadir el campo dentro de `Settings`, después de `anthropic_model`:
```python
    anthropic_allowed_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "claude-haiku-4-5",
            "claude-sonnet-5",
            "claude-opus-4-8",
        ]
    )
```
Y extender el `field_validator` existente para que también parse este campo desde CSV. Cambiar la línea del decorador:
```python
    @field_validator("api_keys", "cors_origins", mode="before")
```
por:
```python
    @field_validator("api_keys", "cors_origins", "anthropic_allowed_models", mode="before")
```
(`Annotated`, `NoDecode`, `Field`, `field_validator` ya están importados.)

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/test_config.py -q` → PASS. Y `.venv/bin/python -m ruff check src/yt_clipper/config.py` → limpio.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/config.py tests/unit/test_config.py
git commit -m "feat(config): add anthropic model allowlist"
```

---

### Task 2: Puertos — model en generate + delete en repo

**Files:**
- Modify: `src/yt_clipper/application/ports.py`

- [ ] **Step 1: Editar el puerto.** En `src/yt_clipper/application/ports.py`:

1. En `DownloadJobRepository`, añadir el método al Protocol:
```python
    def delete(self, job_id: UUID) -> None: ...
```

2. En `CaptionGenerator`, cambiar la firma:
```python
class CaptionGenerator(Protocol):
    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption: ...
```

- [ ] **Step 2: Verificar** — `.venv/bin/python -c "import yt_clipper.application.ports"` sin error; `.venv/bin/python -m ruff check src/yt_clipper/application/ports.py` limpio. (mypy fallará en implementaciones aún no actualizadas — se arregla en Tasks 3/5; no lo persigas aquí.)

- [ ] **Step 3: Commit**
```bash
git add src/yt_clipper/application/ports.py
git commit -m "feat(ports): add model param to generate and delete to repository"
```

---

### Task 3: Adaptadores de caption — override de modelo

**Files:**
- Modify: `src/yt_clipper/infrastructure/ai/anthropic_caption.py`
- Test: `tests/unit/test_anthropic_caption.py`

- [ ] **Step 1: Test que falla** — añadir a `tests/unit/test_anthropic_caption.py` (reutiliza los fakes `FakeClient`/`FakeMessages`/`_Response`/`_Block`/`_metadata` ya presentes en el archivo):

```python
def test_anthropic_generator_uses_model_override() -> None:
    response = _Response(
        [_Block("emit_tiktok_caption", {"caption": "Hola", "hashtags": ["#a"]})]
    )
    messages = FakeMessages(response=response)
    client = FakeClient(messages)
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    generator.generate(_metadata(), model="claude-sonnet-5")

    assert messages.kwargs["model"] == "claude-sonnet-5"


def test_anthropic_generator_falls_back_to_default_model() -> None:
    response = _Response(
        [_Block("emit_tiktok_caption", {"caption": "Hola", "hashtags": ["#a"]})]
    )
    messages = FakeMessages(response=response)
    client = FakeClient(messages)
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    generator.generate(_metadata())

    assert messages.kwargs["model"] == "claude-haiku-4-5"
```

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/test_anthropic_caption.py -q` → FAIL (generate no acepta `model`).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/infrastructure/ai/anthropic_caption.py`:

Cambiar la firma y el uso del modelo en `AnthropicCaptionGenerator.generate`:
```python
    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption:
        try:
            response = self._client.messages.create(
                model=model or self.model,
                max_tokens=512,
                system=_SYSTEM_PROMPT,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": _TOOL_NAME},
                messages=[{"role": "user", "content": self._build_prompt(metadata)}],
            )
        except Exception as exc:  # SDK/network failures
            raise CaptionGenerationError(str(exc)) from exc

        payload = self._extract_tool_input(response)
        caption = str(payload.get("caption") or "").strip()[:_MAX_CAPTION_CHARS]
        hashtags = self._normalize_hashtags(payload.get("hashtags") or [])
        if not caption:
            raise CaptionGenerationError("El proveedor no devolvio caption")
        return TikTokCaption(caption=caption, hashtags=hashtags)
```
Y en `UnavailableCaptionGenerator`, actualizar la firma para cumplir el Protocol:
```python
    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption:
        raise CaptionGeneratorUnavailableError(
            "Configura ANTHROPIC_API_KEY para generar captions de TikTok"
        )
```

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/test_anthropic_caption.py -q` → PASS (todos). `.venv/bin/python -m ruff check` en el archivo.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/infrastructure/ai/anthropic_caption.py tests/unit/test_anthropic_caption.py
git commit -m "feat(ai): support per-request model override"
```

---

### Task 4: Use cases — model en generate + DeleteDownloadUseCase

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_generate_tiktok_caption_use_case.py`
- Test: `tests/unit/application/test_delete_download_use_case.py` (crear)

- [ ] **Step 1: Tests que fallan.**

(a) En `tests/unit/application/test_generate_tiktok_caption_use_case.py`, ampliar el `FakeGenerator` para capturar `model` y añadir un test. Reemplaza la clase `FakeGenerator` por:
```python
class FakeGenerator:
    def __init__(self) -> None:
        self.seen: VideoMetadata | None = None
        self.seen_model: str | None = None

    def generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption:
        self.seen = metadata
        self.seen_model = model
        return TikTokCaption(caption="Mira esto", hashtags=["#viral", "#perros"])
```
Y añade el test:
```python
def test_generate_caption_passes_model() -> None:
    job = _completed_job()
    generator = FakeGenerator()
    use_case = GenerateTikTokCaptionUseCase(FakeRepository(job), generator)

    use_case.execute(job.id, model="claude-sonnet-5")

    assert generator.seen_model == "claude-sonnet-5"
```

(b) Crear `tests/unit/application/test_delete_download_use_case.py`:
```python
from uuid import uuid4

from yt_clipper.application.use_cases import DeleteDownloadUseCase
from yt_clipper.domain.video import DownloadJob


class FakeRepository:
    def __init__(self, job: DownloadJob | None = None) -> None:
        self.jobs = {job.id: job} if job else {}
        self.deleted: list = []

    def add(self, job):
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def update(self, job):
        self.jobs[job.id] = job
        return job

    def delete(self, job_id) -> None:
        self.deleted.append(job_id)
        self.jobs.pop(job_id, None)


class FakeStorage:
    def __init__(self) -> None:
        self.cleaned: list = []

    def cleanup_download_path(self, job) -> None:
        self.cleaned.append(job.id)


def test_delete_removes_files_and_record() -> None:
    job = DownloadJob(source_url="https://youtu.be/abc")
    repository = FakeRepository(job)
    storage = FakeStorage()

    DeleteDownloadUseCase(repository, storage).execute(job.id)

    assert storage.cleaned == [job.id]
    assert repository.deleted == [job.id]


def test_delete_missing_job_is_noop() -> None:
    repository = FakeRepository()
    storage = FakeStorage()

    DeleteDownloadUseCase(repository, storage).execute(uuid4())

    assert storage.cleaned == []
    assert repository.deleted == []
```

- [ ] **Step 2: Ver que fallan** — `.venv/bin/python -m pytest tests/unit/application/test_generate_tiktok_caption_use_case.py tests/unit/application/test_delete_download_use_case.py -q` → FAIL.

- [ ] **Step 3: Implementar.** En `src/yt_clipper/application/use_cases.py`:

(a) En `GenerateTikTokCaptionUseCase`, cambiar `execute` para aceptar y propagar `model`:
```python
    def execute(self, job_id: UUID, model: str | None = None) -> DownloadJob:
        job = self.repository.get(job_id)
        if job is None:
            raise DomainError(f"download job not found: {job_id}")
        if job.status != DownloadStatus.COMPLETED or not job.video_title:
            raise CaptionNotAvailableError("caption requires a completed job with video metadata")
        title = job.video_title  # narrowed to str by the guard above
        metadata = VideoMetadata(
            video_id="",
            title=title,
            description=job.video_description,
            tags=list(job.youtube_tags),
        )
        caption: TikTokCaption = self.generator.generate(metadata, model)
        job.apply_tiktok_caption(caption)
        self.repository.update(job)
        return job
```

(b) Añadir el import del puerto `FileStorage` a la línea de imports de `yt_clipper.application.ports` (ya se importan varios de ahí; añade `FileStorage` si no está). Luego añadir al final del archivo:
```python
class DeleteDownloadUseCase:
    def __init__(self, repository: DownloadJobRepository, storage: FileStorage) -> None:
        self.repository = repository
        self.storage = storage

    def execute(self, job_id: UUID) -> None:
        job = self.repository.get(job_id)
        if job is None:
            return
        self.storage.cleanup_download_path(job)
        self.repository.delete(job_id)
```

- [ ] **Step 4: Ver que pasan** — `.venv/bin/python -m pytest tests/unit/application/ -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/application/use_cases.py`.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_generate_tiktok_caption_use_case.py tests/unit/application/test_delete_download_use_case.py
git commit -m "feat(usecase): pass model to caption and add delete download use case"
```

---

### Task 5: Repositorio — delete

**Files:**
- Modify: `src/yt_clipper/infrastructure/persistence/repositories.py`
- Test: `tests/unit/test_repository.py`

- [ ] **Step 1: Test que falla** — añadir a `tests/unit/test_repository.py` (reusa el patrón de `session` del archivo):

```python
def test_repository_delete_removes_job(session) -> None:  # type: ignore[no-untyped-def]
    from uuid import uuid4

    from yt_clipper.domain.video import DownloadJob
    from yt_clipper.infrastructure.persistence.repositories import (
        SqlAlchemyDownloadJobRepository,
    )

    repo = SqlAlchemyDownloadJobRepository(session)
    job = DownloadJob(source_url="https://youtu.be/abc")
    repo.add(job)

    repo.delete(job.id)

    assert repo.get(job.id) is None
    # borrar un id inexistente no debe lanzar
    repo.delete(uuid4())
```
Adapta la obtención de `session` al patrón real del archivo (fixture o engine inline en memoria).

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/test_repository.py -q` → FAIL (no existe `delete`).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/infrastructure/persistence/repositories.py`, añadir el método a `SqlAlchemyDownloadJobRepository` (después de `update`):
```python
    def delete(self, job_id: UUID) -> None:
        record = self.session.get(DownloadJobRecord, str(job_id))
        if record is None:
            return
        self.session.delete(record)
        self.session.commit()
```

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/test_repository.py -q` → PASS. ruff limpio.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/infrastructure/persistence/repositories.py tests/unit/test_repository.py
git commit -m "feat(persistence): add delete to download job repository"
```

---

### Task 6: Schemas — GenerateCaptionRequest + ModelsResponse

**Files:**
- Modify: `src/yt_clipper/interfaces/http/schemas.py`

- [ ] **Step 1: Implementar.** Añadir al final de `src/yt_clipper/interfaces/http/schemas.py`:
```python
class GenerateCaptionRequest(BaseModel):
    model: str | None = None


class ModelsResponse(BaseModel):
    models: list[str]
    default: str
```
(`BaseModel` ya está importado.)

- [ ] **Step 2: Verificar** — `.venv/bin/python -c "import yt_clipper.interfaces.http.schemas"` sin error; `.venv/bin/python -m ruff check src/yt_clipper/interfaces/http/schemas.py`; `.venv/bin/python -m mypy src/yt_clipper/interfaces/http/schemas.py` → sin errores en el archivo.

- [ ] **Step 3: Commit**
```bash
git add src/yt_clipper/interfaces/http/schemas.py
git commit -m "feat(schemas): add caption request and models response"
```

---

### Task 7: Dependencias HTTP — storage + delete use case

**Files:**
- Modify: `src/yt_clipper/interfaces/http/dependencies.py`

- [ ] **Step 1: Implementar.** En `src/yt_clipper/interfaces/http/dependencies.py`:

1. Ampliar el import de use cases para incluir `DeleteDownloadUseCase`. Añadir import del storage:
```python
from yt_clipper.infrastructure.storage.local import LocalFileStorage
```

2. Añadir factorías:
```python
def get_file_storage(settings: Settings = Depends(get_settings)) -> LocalFileStorage:
    return LocalFileStorage(settings.storage_dir)


def get_delete_download_use_case(
    repository: SqlAlchemyDownloadJobRepository = Depends(get_download_repository),
    storage: LocalFileStorage = Depends(get_file_storage),
) -> DeleteDownloadUseCase:
    return DeleteDownloadUseCase(repository, storage)
```

- [ ] **Step 2: Verificar** — `.venv/bin/python -c "import yt_clipper.interfaces.http.dependencies"`; ruff limpio; `.venv/bin/python -m mypy src/yt_clipper/interfaces/http/dependencies.py` sin errores en el archivo.

- [ ] **Step 3: Commit**
```bash
git add src/yt_clipper/interfaces/http/dependencies.py
git commit -m "feat(http): wire file storage and delete download use case"
```

---

### Task 8: Rutas — GET /models, DELETE /downloads/{id}, model en /tiktok

**Files:**
- Modify: `src/yt_clipper/interfaces/http/routes.py`
- Test: `tests/integration/test_http_api.py`

- [ ] **Step 1: Tests que fallan** — añadir a `tests/integration/test_http_api.py`:

```python
from yt_clipper.interfaces.http.dependencies import get_delete_download_use_case


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

    response = client.get(
        "/api/v1/models", headers={"X-API-Key": "dev-secret-change-me"}
    )

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
```
(`DownloadJob`, `VideoMetadata`, `TikTokCaption`, `uuid4`, `get_generate_caption_use_case` ya se importan en el archivo tras las tasks previas; si falta alguno, añádelo — no dupliques.)

- [ ] **Step 2: Ver que fallan** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → FAIL (404/validación).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/interfaces/http/routes.py`:

1. Ampliar imports:
   - fastapi: asegurar `Response` está importado (ya lo está para health). Mantener `Query`, `Depends`, `HTTPException`, `status`.
   - use cases: añadir `DeleteDownloadUseCase`.
   - config: `from yt_clipper.config import Settings, get_settings`.
   - dependencies: añadir `get_delete_download_use_case`.
   - schemas: añadir `GenerateCaptionRequest`, `ModelsResponse`.

2. Añadir la ruta `GET /models` (después de `search_videos`):
```python
@router.get("/models", response_model=ModelsResponse)
def list_models(settings: Settings = Depends(get_settings)) -> ModelsResponse:
    return ModelsResponse(
        models=list(settings.anthropic_allowed_models),
        default=settings.anthropic_model,
    )
```

3. Reemplazar la ruta `generate_tiktok_caption` por una que acepte body opcional y valide el modelo:
```python
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
```

4. Añadir la ruta `DELETE /downloads/{job_id}` (después de `download_file`):
```python
@router.delete("/downloads/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_download(
    job_id: UUID,
    use_case: DeleteDownloadUseCase = Depends(get_delete_download_use_case),
) -> Response:
    use_case.execute(job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

- [ ] **Step 4: Ver que pasan** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → PASS. ruff + `.venv/bin/python -m mypy` (solo puede quedar el error preexistente no relacionado si lo hubiera; no debe haber nuevos) + full `.venv/bin/python -m pytest -q`.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/interfaces/http/routes.py tests/integration/test_http_api.py
git commit -m "feat(http): add models and delete endpoints, model override on tiktok"
```

---

### Task 9: Verificación backend

- [ ] **Step 1: Gate completo**
```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```
Todo PASS, cobertura ≥85%. Si `ruff format --check` marca archivos, corre `.venv/bin/python -m ruff format .` y vuelve a verificar.

- [ ] **Step 2: Commit (si hubo formato)**
```bash
git add -A
git commit -m "chore(backend): ruff format"
```

---

## Parte 2 — Frontend (`yt-clipper-studio`)

### Task 10: Tipos de dominio

**Files:**
- Modify: `src/domain/models.ts`

- [ ] **Step 1: Añadir tipo.** Al final de `src/domain/models.ts`:
```typescript
export interface AvailableModels {
  models: string[]
  default: string
}
```

- [ ] **Step 2: Verificar** — `npx tsc -b --noEmit` sin errores nuevos en `models.ts`.

- [ ] **Step 3: Commit**
```bash
git add src/domain/models.ts
git commit -m "feat(models): add AvailableModels type"
```

---

### Task 11: Cliente API — getModels, deleteDownload, model en caption

**Files:**
- Modify: `src/infrastructure/api/downloadApi.ts`
- Test: `src/infrastructure/api/downloadApi.test.ts`

- [ ] **Step 1: Tests que fallan** — añadir a `src/infrastructure/api/downloadApi.test.ts`:
```typescript
it('getModels returns the allowlist', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ models: ['claude-haiku-4-5', 'claude-sonnet-5'], default: 'claude-haiku-4-5' }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  const result = await client.getModels()

  expect(result.default).toBe('claude-haiku-4-5')
  expect(result.models).toContain('claude-sonnet-5')
  expect(fetchMock.mock.calls[0][0]).toBe('http://api/api/v1/models')
})

it('deleteDownload issues a DELETE', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  await client.deleteDownload('job-1')

  const [url, init] = fetchMock.mock.calls[0]
  expect(url).toBe('http://api/api/v1/downloads/job-1')
  expect(init.method).toBe('DELETE')
})

it('generateTikTokCaption sends the model in the body when provided', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ id: '1', source_url: 'u', status: 'completed', created_at: 'x', updated_at: 'x' }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  await client.generateTikTokCaption('1', 'claude-sonnet-5')

  const [, init] = fetchMock.mock.calls[0]
  expect(JSON.parse(init.body)).toEqual({ model: 'claude-sonnet-5' })
})
```

- [ ] **Step 2: Ver que fallan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → FAIL.

- [ ] **Step 3: Implementar.** En `src/infrastructure/api/downloadApi.ts`:

1. Ampliar imports de tipos con `AvailableModels`.
2. Cambiar `generateTikTokCaption` para aceptar `model` opcional:
```typescript
  async generateTikTokCaption(jobId: string, model?: string): Promise<BackendDownloadJob> {
    const response = await fetch(`${this.baseUrl}/api/v1/downloads/${jobId}/tiktok`, {
      method: 'POST',
      headers: this.headers(),
      body: model ? JSON.stringify({ model }) : undefined,
    })
    return this.parseResponse(response)
  }
```
3. Añadir métodos:
```typescript
  async getModels(): Promise<AvailableModels> {
    const response = await fetch(`${this.baseUrl}/api/v1/models`, {
      headers: this.headers(),
    })
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await this.getErrorDetail(response)}`)
    }
    return (await response.json()) as AvailableModels
  }

  async deleteDownload(jobId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/v1/downloads/${jobId}`, {
      method: 'DELETE',
      headers: this.authHeaders(),
    })
    if (!response.ok && response.status !== 404) {
      throw new Error(`API ${response.status}: ${await this.getErrorDetail(response)}`)
    }
  }
```

- [ ] **Step 4: Ver que pasan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → PASS. `npm run lint`.

- [ ] **Step 5: Commit**
```bash
git add src/infrastructure/api/downloadApi.ts src/infrastructure/api/downloadApi.test.ts
git commit -m "feat(api): add getModels, deleteDownload and model on caption"
```

---

### Task 12: Coordinador — borrado de proyecto y de video

**Files:**
- Modify: `src/application/downloadCoordinator.ts`
- Test: `src/application/downloadCoordinator.test.ts`

- [ ] **Step 1: Tests que fallan** — añadir a `src/application/downloadCoordinator.test.ts`:
```typescript
import { deletePortfolioWithVideos, deleteSingleDownload } from './downloadCoordinator'

it('deletePortfolioWithVideos deletes each job then removes the portfolio', async () => {
  const repo = new InMemoryPortfolioRepository()
  repo.save({
    id: 'p1', name: 'X', createdAt: 'x', updatedAt: 'x',
    downloads: [
      { id: 'd1', jobId: 'j1', sourceUrl: 'u', kind: 'full', status: 'completed', createdAt: 'x', updatedAt: 'x' },
      { id: 'd2', jobId: 'j2', sourceUrl: 'u', kind: 'full', status: 'completed', createdAt: 'x', updatedAt: 'x' },
    ],
  })
  const deleted: string[] = []
  const api = { deleteDownload: async (jobId: string) => { deleted.push(jobId) } }

  await deletePortfolioWithVideos('p1', repo, api as never)

  expect(deleted.sort()).toEqual(['j1', 'j2'])
  expect(repo.getById('p1')).toBeUndefined()
})

it('deletePortfolioWithVideos removes the portfolio even if a delete fails', async () => {
  const repo = new InMemoryPortfolioRepository()
  repo.save({
    id: 'p1', name: 'X', createdAt: 'x', updatedAt: 'x',
    downloads: [{ id: 'd1', jobId: 'j1', sourceUrl: 'u', kind: 'full', status: 'completed', createdAt: 'x', updatedAt: 'x' }],
  })
  const api = { deleteDownload: async () => { throw new Error('boom') } }

  await deletePortfolioWithVideos('p1', repo, api as never)

  expect(repo.getById('p1')).toBeUndefined()
})

it('deleteSingleDownload removes the item from the portfolio', async () => {
  const repo = new InMemoryPortfolioRepository()
  repo.save({
    id: 'p1', name: 'X', createdAt: 'x', updatedAt: 'x',
    downloads: [
      { id: 'd1', jobId: 'j1', sourceUrl: 'u', kind: 'full', status: 'completed', createdAt: 'x', updatedAt: 'x' },
      { id: 'd2', jobId: 'j2', sourceUrl: 'u', kind: 'full', status: 'completed', createdAt: 'x', updatedAt: 'x' },
    ],
  })
  const api = { deleteDownload: async () => {} }

  await deleteSingleDownload('p1', 'j1', repo, api as never)

  const downloads = repo.getById('p1')!.downloads
  expect(downloads.map((d) => d.jobId)).toEqual(['j2'])
})
```

- [ ] **Step 2: Ver que fallan** — `npm run test -- src/application/downloadCoordinator.test.ts` → FAIL.

- [ ] **Step 3: Implementar.** En `src/application/downloadCoordinator.ts`:

1. Ampliar la interfaz `DownloadApi` con:
```typescript
  deleteDownload(jobId: string): Promise<void>
```
2. Añadir al final del archivo:
```typescript
export async function deletePortfolioWithVideos(
  portfolioId: string,
  repository: PortfolioRepository,
  api: DownloadApi,
): Promise<void> {
  const portfolio = repository.getById(portfolioId)
  if (!portfolio) {
    return
  }
  await Promise.all(
    portfolio.downloads.map(async (item) => {
      try {
        await api.deleteDownload(item.jobId)
      } catch {
        // best-effort: ignore individual delete failures
      }
    }),
  )
  repository.delete(portfolioId)
}

export async function deleteSingleDownload(
  portfolioId: string,
  jobId: string,
  repository: PortfolioRepository,
  api: DownloadApi,
): Promise<void> {
  try {
    await api.deleteDownload(jobId)
  } catch {
    // best-effort
  }
  const portfolio = repository.getById(portfolioId)
  if (!portfolio) {
    return
  }
  repository.save({
    ...portfolio,
    updatedAt: new Date().toISOString(),
    downloads: portfolio.downloads.filter((item) => item.jobId !== jobId),
  })
}
```
Nota: las clases fake de `DownloadApi` en los tests existentes deberán tener `deleteDownload` si TypeScript lo exige por la interfaz; si un test previo construye un objeto que debe cumplir `DownloadApi` completo, añade `deleteDownload: vi.fn()` a ese literal (como se hizo con `createDownloadBatch`).

- [ ] **Step 4: Ver que pasan** — `npm run test -- src/application/downloadCoordinator.test.ts` → PASS (todos). `npm run lint`.

- [ ] **Step 5: Commit**
```bash
git add src/application/downloadCoordinator.ts src/application/downloadCoordinator.test.ts
git commit -m "feat(coordinator): delete portfolio videos and single download"
```

---

### Task 13: UI — selectores de modelo + borrado

**Files:**
- Modify: `src/App.tsx`, `src/App.css`
- Test: `src/App.test.tsx`

- [ ] **Step 1: Leer App.tsx.** Leer `src/App.tsx` completo y `src/App.test.tsx` para conocer patrones (fetch fake por endpoint, cómo se renderiza la cabecera, cada `downloadItem`, el botón "Generar caption" ~línea 698, y `handleDeletePortfolio` ~línea 224, `handleGenerateCaption` ~línea 348).

- [ ] **Step 2: Tests que fallan** — añadir a `src/App.test.tsx` (adapta el render/fetch-mock al patrón del archivo):

```typescript
it('carga modelos y usa el modelo global al generar caption', async () => {
  // fetch mock: GET /api/v1/models -> { models:[...], default:'claude-haiku-4-5' }
  //             POST /api/v1/downloads/{id}/tiktok -> job con tiktok_caption
  // render App con un portfolio que tenga una descarga 'completed' con videoTitle
  // seleccionar en el <select> global 'claude-sonnet-5'
  // pulsar 'Generar caption TikTok'
  // assert: el fetch al endpoint /tiktok se llamó con body { model: 'claude-sonnet-5' }
})

it('borra un proyecto y elimina sus videos en backend', async () => {
  // fetch mock: DELETE /api/v1/downloads/{id} -> 204
  // render App con portfolio con 2 descargas (jobId j1, j2)
  // pulsar el botón de borrar proyecto (confirmar si hay confirm; stub window.confirm -> true)
  // assert: fetch DELETE llamado para j1 y j2; el portfolio desaparece de la UI
})
```
Implementa el cuerpo real siguiendo el patrón del archivo (mock de `fetch` que despacha por URL/método; usa `findBy*`/`waitFor`). El `<select>` global debe tener un `aria-label` estable, p. ej. `aria-label="Modelo de IA"`, para localizarlo.

- [ ] **Step 3: Ver que fallan** — `npm run test -- src/App.test.tsx` → FAIL.

- [ ] **Step 4: Implementar en App.tsx.**

**Modelo global:** nuevo estado y carga:
```typescript
const [availableModels, setAvailableModels] = useState<string[]>([])
const [globalModel, setGlobalModel] = useState<string>(
  () => localStorage.getItem('yt-clipper:model') ?? '',
)

useEffect(() => {
  apiClient
    .getModels()
    .then((data) => {
      setAvailableModels(data.models)
      setGlobalModel((current) => current || data.default)
    })
    .catch(() => {
      /* si falla, la UI sigue con lo que haya en localStorage */
    })
}, [])

function handleGlobalModelChange(value: string) {
  setGlobalModel(value)
  localStorage.setItem('yt-clipper:model', value)
}
```
Renderizar en la cabecera un `<select aria-label="Modelo de IA" value={globalModel} onChange={(e) => handleGlobalModelChange(e.target.value)}>` con `availableModels.map(...)` como `<option>`.

**Override por video:** un map de estado:
```typescript
const [perVideoModel, setPerVideoModel] = useState<Record<string, string>>({})
```
Junto a cada botón "Generar caption", un `<select value={perVideoModel[downloadItem.jobId] ?? globalModel} onChange={(e) => setPerVideoModel((m) => ({ ...m, [downloadItem.jobId]: e.target.value }))}>` con las mismas opciones.

**Pasar el modelo al generar** — cambiar `handleGenerateCaption` para usar el modelo elegido:
```typescript
      const model = perVideoModel[downloadItem.jobId] ?? globalModel
      const job = await apiClient.generateTikTokCaption(downloadItem.jobId, model || undefined)
```

**Borrar proyecto con videos** — cambiar `handleDeletePortfolio` a async usando el coordinador:
```typescript
  async function handleDeletePortfolio() {
    if (!selectedPortfolio) {
      return
    }
    await deletePortfolioWithVideos(selectedPortfolio.id, repository, apiClient)
    const nextPortfolios = repository.list()
    setPortfolios(nextPortfolios)
    setSelectedPortfolioId(nextPortfolios[0]?.id ?? '')
  }
```
(Importar `deletePortfolioWithVideos` y `deleteSingleDownload` desde `./application/downloadCoordinator`. Puedes retirar el import de `deletePortfolio` de `portfolioService` si ya no se usa.)

**Botón eliminar por descarga** — en el render de cada `downloadItem`, añadir un botón:
```typescript
<button
  className="ghost-action"
  onClick={async () => {
    await deleteSingleDownload(activePortfolioId, downloadItem.jobId, repository, apiClient)
    setPortfolios(repository.list())
  }}
  type="button"
>
  Eliminar
</button>
```

- [ ] **Step 5: Estilos** — en `src/App.css` añadir reglas mínimas para los `<select>` de modelo y el botón Eliminar, acordes al estilo existente.

- [ ] **Step 6: Ver que pasan** — `npm run test -- src/App.test.tsx` → PASS; luego `npm run test` completo sin regresiones. `npm run lint`.

- [ ] **Step 7: Commit**
```bash
git add src/App.tsx src/App.css src/App.test.tsx
git commit -m "feat(ui): model selectors (global + per video) and delete actions"
```

---

### Task 14: Verificación frontend

- [ ] **Step 1: Gate**
```bash
npm run lint
npm run test:coverage
npm run build
```
Todo PASS y cobertura sobre umbrales (branches 75, functions 80, lines 80, statements 80 en `vite.config.ts`). Si algún umbral baja por el código nuevo, añade tests dirigidos (selector individual, botón eliminar por video, fallo de getModels) hasta recuperarlo. NO bajar los umbrales.

- [ ] **Step 2: Commit (si hubo cambios)**
```bash
git add -A
git commit -m "test(frontend): cover model selector and delete flows"
```

---

### Task 15: Verificación end-to-end (Docker)

- [ ] **Step 1: Reconstruir**
```bash
ENV_FILE=.env POSTGRES_PORT=5433 FRONTEND_PORT=8081 docker compose \
  -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.cors-8081.yml \
  up --build -d
```
(Si no existe `.env`, usa el default `.env.example` omitiendo `ENV_FILE`.)

- [ ] **Step 2: Probar endpoints nuevos**
```bash
curl -s -H 'X-API-Key: dev-secret-change-me' http://localhost:8000/api/v1/models
# crea/verifica un job y prueba DELETE:
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE -H 'X-API-Key: dev-secret-change-me' \
  http://localhost:8000/api/v1/downloads/<job_id>
```
Esperado: `/models` devuelve la allowlist + default; DELETE responde 204.

- [ ] **Step 3: Probar en el navegador** — en `http://localhost:8081`: el selector global de modelo aparece y persiste; el selector por video sobreescribe; borrar un proyecto elimina sus descargas (y sus carpetas en `downloads/`); el botón Eliminar por descarga funciona.

---

## Notas

- **Orden de rutas:** `DELETE /downloads/{job_id}` no colisiona con los GET/POST existentes (método distinto). `GET /models` es un path propio.
- **Cobertura backend:** el endpoint `/models` y la validación de allowlist se cubren con los tests de integración; el `DeleteDownloadUseCase` y el repo `delete` con unit tests.
- **`.env` bloqueado para edición** por permisos: sin cambios en `.env.example` en este plan.
