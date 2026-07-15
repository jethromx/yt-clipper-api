# Diseño: Modelo configurable + Borrado de videos al borrar proyecto

- Fecha: 2026-07-15
- Estado: Aprobado (pendiente de plan)
- Repos: `yt-clipper-api` (backend), `yt-clipper-studio` (frontend)

## Resumen

Dos features incrementales sobre la funcionalidad de caption TikTok + portfolios:

- **Feature A — Modelo configurable.** El usuario elige qué modelo de Claude usa la
  generación de caption. Hay un selector **global** (default de la app) y un selector
  **individual por video** que lo sobreescribe para esa generación. La lista de modelos
  permitidos vive en el backend (allowlist validada) y se expone vía endpoint.
- **Feature B — Borrar videos al borrar proyecto.** Al eliminar un portfolio se borran
  en el backend los archivos + registros de todas sus descargas (best-effort). Además,
  un botón "Eliminar" por descarga borra un video individual.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Selector de modelo | Global (default en localStorage) + override individual por video |
| Allowlist de modelos | `claude-haiku-4-5` (default), `claude-sonnet-5`, `claude-opus-4-8` |
| Origen de la lista | Backend la expone en `GET /api/v1/models` (frontend no hardcodea) |
| Validación del modelo | En el backend contra la allowlist; modelo inválido → 400 |
| Borrado de proyecto | Best-effort: borra jobs/archivos de sus descargas; si alguno falla se ignora y el portfolio se borra igual |
| Borrado individual | Botón por descarga (borra ese video: backend + lista) |
| Semántica DELETE | Idempotente: borrar un job inexistente responde 204 |

---

## Feature A — Modelo configurable

### Backend (`yt-clipper-api`)

**Config** (`config.py`):
- Nuevo `anthropic_allowed_models: list[str]` con default
  `["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"]` (usa el mismo
  `split_csv` validator/`NoDecode` que `api_keys`/`cors_origins` para poder
  configurarlo por env como CSV). El default `anthropic_model` debe estar contenido
  en la allowlist.

**Puerto** (`application/ports.py`):
- `CaptionGenerator.generate` gana un parámetro opcional:
  `generate(self, metadata: VideoMetadata, model: str | None = None) -> TikTokCaption`.

**Adaptadores** (`infrastructure/ai/anthropic_caption.py`):
- `AnthropicCaptionGenerator.generate(metadata, model=None)`: usa `model` si se pasa,
  si no `self.model`. (El `self.model` sigue siendo el default de settings.)
- `UnavailableCaptionGenerator.generate(metadata, model=None)`: ignora `model`, sigue
  lanzando `CaptionGeneratorUnavailableError`.

**Caso de uso** (`application/use_cases.py`):
- `GenerateTikTokCaptionUseCase.execute(job_id, model: str | None = None)`: pasa `model`
  al generador. (La validación de la allowlist se hace en la capa HTTP, ver abajo, para
  no acoplar el use case a la config.)

**HTTP** (`interfaces/http/`):
- Schema nuevo `GenerateCaptionRequest { model: str | None = None }`.
- Nuevo schema `ModelsResponse { models: list[str], default: str }`.
- `GET /api/v1/models` (protegido por API key) → `ModelsResponse` construido desde
  `settings.anthropic_allowed_models` y `settings.anthropic_model`.
- `POST /api/v1/downloads/{job_id}/tiktok` acepta body opcional
  `GenerateCaptionRequest` (default cuerpo vacío → `model=None`). Antes de invocar el
  use case: si `request.model` está presente y no está en
  `settings.anthropic_allowed_models` → `HTTPException(400)`. Luego
  `use_case.execute(job_id, model=request.model)`.
- Dependencia `configured_settings`/`get_settings` ya disponible para leer la allowlist
  en la ruta.

### Frontend (`yt-clipper-studio`)

**Tipos** (`domain/models.ts`): `AvailableModels { models: string[]; default: string }`.

**API client** (`infrastructure/api/downloadApi.ts`):
- `getModels(): Promise<AvailableModels>` → `GET /api/v1/models`.
- `generateTikTokCaption(jobId, model?)`: si `model` se pasa, envía body
  `{ model }`; si no, POST sin body (o `{}`).

**UI** (`App.tsx`):
- Al montar, cargar `getModels()` a estado `availableModels`. Fallback: si falla, usar
  una lista mínima `[default]` para no romper la UI.
- **Selector global**: un `<select>` en la cabecera junto a la config, valor guardado en
  `localStorage` (clave p. ej. `yt-clipper:model`). Estado `globalModel`.
- **Selector individual**: junto a cada botón "Generar caption", un `<select>` cuyo valor
  inicial es `globalModel`; el valor elegido se guarda en un map `perVideoModel[jobId]`.
  Al pulsar "Generar", se envía `perVideoModel[jobId] ?? globalModel`.

---

## Feature B — Borrar videos al borrar proyecto

### Backend (`yt-clipper-api`)

**Puerto** (`application/ports.py`):
- `DownloadJobRepository` gana `delete(self, job_id: UUID) -> None`.

**Repositorio** (`infrastructure/persistence/repositories.py`):
- `SqlAlchemyDownloadJobRepository.delete(job_id)`: `session.get(record)`; si existe,
  `session.delete(record)` + `commit()`; si no existe, no-op (idempotente).

**Caso de uso** (`application/use_cases.py`):
- `DeleteDownloadUseCase(repository, storage)`:
  - `execute(job_id)`:
    - `job = repository.get(job_id)`.
    - Si `job` existe: `storage.cleanup_download_path(job)` (borra la carpeta
      `downloads/{job_id}` con video + clip) y `repository.delete(job_id)`.
    - Si no existe: no-op. Retorna `None`.
  - Errores de storage se propagan (el endpoint decide; ver abajo se envuelven en
    best-effort del lado del frontend).

**HTTP** (`interfaces/http/`):
- Dependencia `get_file_storage(settings) -> LocalFileStorage(settings.storage_dir)`.
- Dependencia `get_delete_download_use_case(repository, storage)`.
- `DELETE /api/v1/downloads/{job_id}` (protegido) → `use_case.execute(job_id)` →
  `Response(status_code=204)`. Idempotente (204 aunque el job no existiera).

Nota: tanto `api` como `worker` montan el volumen de descargas en `STORAGE_DIR`, por lo
que el contenedor `api` tiene acceso a los archivos para borrarlos.

### Frontend (`yt-clipper-studio`)

**API client**: `deleteDownload(jobId): Promise<void>` → `DELETE`; en error de red/HTTP
distinto de 2xx, lanza; el llamador decide si lo ignora.

**Coordinador** (`application/downloadCoordinator.ts`):
- `deletePortfolioWithVideos(portfolioId, repository, api)`: obtiene el portfolio, itera
  sus `downloads` llamando `api.deleteDownload(jobId)` en modo best-effort (envuelto en
  try/catch individual; un fallo no aborta el resto), y al final `repository.delete(id)`.
- `deleteSingleDownload(portfolioId, jobId, repository, api)`: `api.deleteDownload(jobId)`
  (best-effort) y luego quita ese item de `portfolio.downloads` y guarda.

**UI** (`App.tsx`):
- `handleDeletePortfolio`: usa `deletePortfolioWithVideos(...)` en vez del
  `deletePortfolio` actual; muestra estado de carga y refresca.
- Botón "Eliminar" por descarga → `deleteSingleDownload(...)` y refresca.

---

## Contratos JSON (referencia)

`GET /api/v1/models` →
```json
{ "models": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-4-8"],
  "default": "claude-haiku-4-5" }
```

`POST /api/v1/downloads/{job_id}/tiktok` body opcional →
```json
{ "model": "claude-sonnet-5" }
```
`400` si `model` no está en la allowlist.

`DELETE /api/v1/downloads/{job_id}` → `204 No Content` (idempotente).

---

## Testing

**Backend** (cobertura ≥85%):
- `GET /models` devuelve allowlist + default (integración con override de settings).
- `POST /tiktok` con `model` válido lo pasa al generador (fake generator captura el
  `model`); con `model` inválido → 400; sin body → usa default (`model=None`).
- `AnthropicCaptionGenerator.generate` usa el `model` override vs `self.model` (fake
  client inspecciona `kwargs["model"]`).
- `GenerateTikTokCaptionUseCase.execute(job_id, model=...)` propaga el model.
- `DeleteDownloadUseCase`: borra archivos + registro cuando existe; no-op cuando no
  existe (fake repo + fake storage que registra llamadas).
- `SqlAlchemyDownloadJobRepository.delete`: round-trip (add → delete → get None);
  delete de id inexistente no lanza.
- `DELETE /api/v1/downloads/{job_id}` → 204 (con y sin job existente).

**Frontend** (Vitest + Testing Library):
- `downloadApi`: `getModels`, `deleteDownload` (204 y 404 tolerado por el llamador),
  `generateTikTokCaption` con y sin `model` en el body.
- `downloadCoordinator`: `deletePortfolioWithVideos` llama delete por cada job y borra el
  portfolio aunque un delete falle; `deleteSingleDownload` quita el item.
- `App`: selector global persiste en localStorage; selector individual sobreescribe y se
  envía el model correcto; borrar proyecto llama delete por cada job; botón eliminar por
  descarga.

## Fuera de alcance (YAGNI)

- Persistir el modelo elegido por-video entre sesiones (el override es efímero; solo el
  global se guarda en localStorage).
- Cola/confirmación de borrado con papelera/undo (el borrado es inmediato).
- Exponer parámetros del modelo (temperature, max_tokens) en la UI.
- Borrado de archivos huérfanos no referenciados por ningún job.

## Riesgos y mitigaciones

- **Borrado parcial**: si el backend borra el archivo pero falla el borrado del registro
  (o viceversa), el `DeleteDownloadUseCase` hace primero cleanup de archivos y luego el
  registro; ante error se propaga y el frontend lo trata best-effort (el portfolio se
  borra localmente igual). Aceptable para datos de dev.
- **Modelo fuera de allowlist**: validado en backend (400) para no gastar llamadas a la
  API con modelos no soportados.
- **Job en curso al borrarse**: borrar un job `running` elimina su registro/carpeta; el
  worker podría fallar al escribir después, pero el job ya no se consulta. Aceptable;
  no se añade cancelación de Celery (fuera de alcance).
