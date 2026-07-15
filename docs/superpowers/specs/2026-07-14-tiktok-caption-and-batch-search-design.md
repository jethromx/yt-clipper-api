# Diseño: Caption TikTok con IA + Búsqueda y descarga en lote

- Fecha: 2026-07-14
- Estado: Aprobado (pendiente de plan de implementación)
- Repos afectados: `yt-clipper-api` (backend), `yt-clipper-studio` (frontend)

## Resumen

Se añaden dos features al producto yt-clipper:

- **Feature A — Caption TikTok con IA.** Al completar una descarga, el backend
  captura la metadata de YouTube (título, descripción, tags) y la persiste en el
  job. Bajo demanda, el usuario genera con Claude una descripción corta al estilo
  TikTok **en español** más hashtags.
- **Feature B — Búsqueda y descarga en lote.** El usuario busca videos por
  frase/palabra, selecciona varios o todos, y los descarga automáticamente
  encolados con una sola acción.

Ambas features respetan la arquitectura hexagonal existente
(`domain` / `application` / `infrastructure` / `interfaces/http`) y el patrón del
frontend (`domain` / `application` / `infrastructure`).

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Fuente del caption | Híbrido: siempre extraer metadata de YouTube; IA opcional bajo demanda |
| Idioma del caption IA | Español, siempre |
| Ejecución de la generación IA | Síncrona en el request (no Celery); es una sola llamada rápida |
| Modelo por defecto | `claude-haiku-4-5` (barato/rápido), configurable |
| Buscador de videos | `yt-dlp` `ytsearch` (sin API key nueva) |
| Descargas de lote | Siempre video completo (`kind: full`), sin recorte |

---

## Feature A — Caption TikTok con IA

### Dominio (`yt-clipper-api`)

- Extender `VideoMetadata` (frozen dataclass) con:
  - `description: str | None = None`
  - `tags: list[str] = field(default_factory=list)`
- Extender `DownloadJob` con campos nuevos:
  - `video_title: str | None = None`
  - `video_description: str | None = None` (descripción original de YouTube)
  - `youtube_tags: list[str] = field(default_factory=list)`
  - `tiktok_caption: str | None = None`
  - `tiktok_hashtags: list[str] = field(default_factory=list)`
  - `tiktok_generated_at: datetime | None = None`
- Nuevo método en `DownloadJob`:
  - `apply_metadata(title, description, tags)` — asigna los campos de YouTube y
    actualiza `updated_at`.
  - `apply_tiktok_caption(caption, hashtags)` — asigna caption/hashtags y
    `tiktok_generated_at`, actualiza `updated_at`.
- Nuevo value object en `domain/video.py`:
  - `TikTokCaption(caption: str, hashtags: list[str])`.

### Puertos (`application/ports.py`)

- Nuevo `CaptionGenerator` (Protocol):
  - `generate(metadata: VideoMetadata) -> TikTokCaption`
- Ampliar `VideoProvider`:
  - `download_best(...)` cambia su retorno a `DownloadResult` (ver abajo).

### Provider yt-dlp

- Refactor de `download_best` para devolver metadata en la misma operación de red:
  - Usar `extract_info(source_url, download=True)`; conservar la estrategia de
    "diff del directorio" para localizar el archivo final (robusta ante merges).
  - Devolver un dataclass `DownloadResult(path: Path, metadata: VideoMetadata)`
    definido en `application/ports.py`.
- `_metadata_from_info` captura además `description` (str o None) y `tags`
  (lista de str; default `[]`).

### Aplicación

- `ExecuteDownloadJobUseCase.execute`:
  - Tras la descarga, llamar `job.apply_metadata(...)` con la metadata devuelta
    por `download_best`, **antes** de `mark_completed`.
- Nuevo `GenerateTikTokCaptionUseCase`:
  - Depende de `DownloadJobRepository` y `CaptionGenerator`.
  - `execute(job_id) -> DownloadJob`:
    1. Cargar job; si no existe → `DomainError`.
    2. Si el job no está `COMPLETED` o no tiene `video_title` → error de dominio
       específico (`CaptionNotAvailableError`) → HTTP 409.
    3. Construir `VideoMetadata` desde los campos del job.
    4. `generator.generate(metadata)` → `TikTokCaption`.
    5. `job.apply_tiktok_caption(...)`, `repository.update(job)`, retornar job.

### Infraestructura — `AnthropicCaptionGenerator`

- Ubicación: `infrastructure/ai/anthropic_caption.py`.
- Usa el SDK `anthropic`. Cliente construido con `settings.anthropic_api_key`.
- Modelo: `settings.anthropic_model` (default `claude-haiku-4-5`).
- Estrategia de salida estructurada: **tool use** con una herramienta
  `emit_tiktok_caption` cuyo input schema exige `caption: string` y
  `hashtags: string[]`. Se lee el `tool_use` block del response.
- Prompt (system + user), en español:
  - Rol: experto en captions de TikTok.
  - Entrada: título, descripción (recortada a ~1000 chars), tags.
  - Requisitos: `caption` ≤ 150 caracteres, con gancho; 6–8 hashtags relevantes
    en español, sin espacios, con `#`, sin duplicados.
- Normalización post-respuesta: recortar caption, deduplicar hashtags, asegurar
  prefijo `#`, limitar a 8.
- Errores del SDK/red → `CaptionGenerationError` (mapea a HTTP 502).
- Si `anthropic_api_key` es `None`: la factoría de dependencias inyecta un
  generador `UnavailableCaptionGenerator` cuyo `generate` lanza
  `CaptionGeneratorUnavailableError` → HTTP 503 con mensaje claro
  ("Configura ANTHROPIC_API_KEY para generar captions").

### HTTP

- `schemas.py`: `DownloadJobResponse` gana `video_title`, `video_description`,
  `youtube_tags`, `tiktok_caption`, `tiktok_hashtags`, `tiktok_generated_at`;
  `from_domain` los mapea.
- Nueva ruta en `routes.py`:
  - `POST /api/v1/downloads/{job_id}/tiktok` → `GenerateTikTokCaptionUseCase`.
    Respuestas: 200 con `DownloadJobResponse`; 404 job inexistente;
    409 job no completado / sin metadata; 502 error del proveedor IA;
    503 IA no configurada.
- Dependencias en `dependencies.py`: factoría del generador (Anthropic o
  Unavailable según config) y del nuevo use case.

### Persistencia

- `models.py`: añadir columnas a `DownloadJobRecord`:
  - `video_title` (Text, null), `video_description` (Text, null),
    `youtube_tags` (JSON, default `[]`), `tiktok_caption` (Text, null),
    `tiktok_hashtags` (JSON, default `[]`),
    `tiktok_generated_at` (DateTime(timezone=True), null).
- `repositories.py`: mapear los nuevos campos en ambos sentidos
  (record ↔ dominio).
- Migración Alembic nueva (`0002_add_metadata_and_tiktok_fields.py`) con
  `add_column` para cada columna (usar `sa.JSON()` — compatible con PostgreSQL
  y SQLite).

### Config

- `config.py` `Settings`: `anthropic_api_key: str | None = None`,
  `anthropic_model: str = "claude-haiku-4-5"`.
- `.env.example`: documentar `ANTHROPIC_API_KEY=` (vacío) y `ANTHROPIC_MODEL`.
- `pyproject.toml`: añadir dependencia `anthropic`.

---

## Feature B — Búsqueda y descarga en lote

### Dominio (`yt-clipper-api`)

- Nuevo value object `VideoSearchResult`:
  - `video_id: str`, `title: str`, `url: str`,
    `duration_seconds: float | None`, `channel: str | None`,
    `thumbnail_url: str | None`.

### Provider yt-dlp

- Nuevo `search(query: str, limit: int) -> list[VideoSearchResult]`:
  - Query `f"ytsearch{limit}:{query}"`, opciones `extract_flat: "in_playlist"`,
    `skip_download: True`.
  - Mapear cada `entry`: `id`, `title`, `url`/`webpage_url`, `duration`,
    `channel`/`uploader`, primera miniatura disponible (`thumbnails[-1].url` o
    `thumbnail`).
  - Entradas sin `id` se descartan.
- Añadir `search` al puerto `VideoProvider`.

### Aplicación

- `SearchVideosUseCase`:
  - `execute(query, limit) -> list[VideoSearchResult]`.
  - Valida `query` no vacío (→ error de dominio) y clamp de `limit` a `[1, 50]`.
- `CreateDownloadBatchUseCase`:
  - Depende de `DownloadJobRepository` y `JobQueue`.
  - `execute(source_urls: list[str]) -> list[DownloadJob]`:
    - Valida lista no vacía y tamaño ≤ 50 (→ error de dominio).
    - Por cada URL: crea `DownloadJob` (sin `clip_range`), `repository.add`,
      `queue.enqueue_download(job.id)`.
    - Retorna la lista de jobs creados.
  - Nota: reutiliza la misma lógica de creación que `CreateDownloadUseCase`;
    se extraerá un helper compartido para evitar duplicación.

### HTTP

- `GET /api/v1/search?q=<frase>&limit=20`:
  - Params: `q` (requerido, no vacío), `limit` (int, default 20, 1–50).
  - Respuesta: `SearchResponse { results: list[SearchResultResponse] }` donde
    `SearchResultResponse` = `{ video_id, title, url, duration_seconds,
    channel, thumbnail_url }`.
  - 400 si `q` vacío.
- `POST /api/v1/downloads/batch`:
  - Body: `BatchDownloadRequest { source_urls: list[HttpUrl] }` (1–50 items).
  - Respuesta 202: `BatchDownloadResponse { jobs: list[DownloadJobResponse] }`.
  - 400 si lista vacía o excede el máximo.

### Frontend (`yt-clipper-studio`)

- **Tipos** (`domain/models.ts`):
  - `BackendDownloadJob` y `PortfolioDownload` ganan: `videoTitle?`,
    `videoDescription?`, `youtubeTags?: string[]`, `tiktokCaption?`,
    `tiktokHashtags?: string[]`, `tiktokGeneratedAt?` (y sus equivalentes
    snake_case en el tipo backend).
  - Nuevos tipos `VideoSearchResult` y `SearchResponse`.
- **API client** (`infrastructure/api/downloadApi.ts`):
  - `searchVideos(query, limit): Promise<VideoSearchResult[]>`
  - `createDownloadBatch(sourceUrls): Promise<BackendDownloadJob[]>`
  - `generateTikTokCaption(jobId): Promise<BackendDownloadJob>`
- **Aplicación**:
  - `downloadCoordinator`: al mapear jobs backend→portfolio, incluir los campos
    nuevos; nueva acción para batch (crea N `PortfolioDownload`).
  - `portfolioService`: soportar añadir múltiples descargas de una vez.
- **UI (`App.tsx`)**:
  - Sección de búsqueda dentro del portfolio activo: input + botón Buscar.
  - Resultados como tarjetas: miniatura, título, canal, duración, checkbox.
  - Control "Seleccionar todos" y botón "Descargar N seleccionados" → batch.
  - En cada descarga completada: mostrar descripción original recortada, botón
    "Generar caption TikTok", y al generar mostrar caption + hashtags con botón
    "Copiar" (usa `navigator.clipboard`).
  - Estados de carga/deshabilitado y manejo de error (mensaje inline) para
    búsqueda, batch y generación de caption.

---

## Contratos JSON (referencia)

`GET /api/v1/search?q=perros&limit=20` →
```json
{ "results": [
  { "video_id": "abc123", "title": "...", "url": "https://youtube.com/watch?v=abc123",
    "duration_seconds": 84.0, "channel": "Canal", "thumbnail_url": "https://i.ytimg.com/..." }
] }
```

`POST /api/v1/downloads/batch` body →
```json
{ "source_urls": ["https://youtube.com/watch?v=abc123", "https://youtube.com/watch?v=def456"] }
```
respuesta `202` →
```json
{ "jobs": [ { "id": "...", "status": "queued", ... } ] }
```

`POST /api/v1/downloads/{job_id}/tiktok` respuesta `200` →
```json
{ "id": "...", "status": "completed",
  "tiktok_caption": "...", "tiktok_hashtags": ["#perros", "#viral"],
  "tiktok_generated_at": "2026-07-14T00:00:00Z", ... }
```

---

## Testing

**Backend** (mantener cobertura ≥ 85%):
- `test_ytdlp_provider`: `download_best` devuelve `DownloadResult` con metadata;
  `search` mapea entries a `VideoSearchResult`; casos sin `id`/miniatura.
- Use cases: `ExecuteDownloadJobUseCase` aplica metadata; `SearchVideosUseCase`
  (validación/clamp); `CreateDownloadBatchUseCase` (crea y encola N; valida
  vacío y tope); `GenerateTikTokCaptionUseCase` con fake generator (éxito, job
  no completado → 409, generador no disponible → 503).
- Integración HTTP: `GET /search`, `POST /downloads/batch`,
  `POST /downloads/{id}/tiktok` (con generador fake inyectado por dependencia).

**Frontend** (Vitest + Testing Library):
- `downloadApi.test`: `searchVideos`, `createDownloadBatch`,
  `generateTikTokCaption` (con `fetch` fake).
- `downloadCoordinator.test`: mapeo de campos nuevos y acción batch.
- `App.test`: flujo buscar → seleccionar (incl. "seleccionar todos") →
  descargar; botón generar caption muestra resultado; botón copiar.

## Fuera de alcance (YAGNI)

- Paginación de resultados de búsqueda (solo un `limit`).
- Regenerar/editar el caption IA (una generación reemplaza la anterior).
- Recorte parcial en descargas de lote (siempre completo).
- Persistencia de resultados de búsqueda (son efímeros en el frontend).
- Reintentos/rate-limit específicos para la API de Anthropic más allá del
  manejo de error básico.

## Riesgos y mitigaciones

- **yt-dlp `ytsearch` lento o con 403**: el endpoint hereda los timeouts/retries
  del provider; el frontend muestra error y permite reintentar.
- **Coste de Claude**: modelo barato por defecto y generación solo bajo demanda.
- **Miniaturas remotas**: se cargan vía `<img>` desde `i.ytimg.com`; no hay CSP
  en la app (a diferencia de un Artifact), por lo que cargan directamente.
