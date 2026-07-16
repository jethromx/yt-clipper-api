# Diseño: Sugerencias de búsqueda basadas en tendencias

- Fecha: 2026-07-15
- Estado: Aprobado (pendiente de plan)
- Repos: `yt-clipper-api` (backend), `yt-clipper-studio` (frontend)

## Resumen

Añadir una sección de **sugerencias de búsqueda** derivadas de las tendencias reales de
YouTube (YouTube Data API v3, `videos.list?chart=mostPopular`). De los videos en tendencia
por país se extraen hashtags y keywords que se muestran como chips clicables; al pulsar uno
se ejecuta la búsqueda (respetando el filtro de duración existente).

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Fuente de tendencias | YouTube Data API `videos.list?chart=mostPopular` (real, por país) |
| Credencial | `YOUTUBE_API_KEY` (gratis, cuota diaria); sin key → endpoint 503 |
| Forma de las sugerencias | Chips de **hashtags** (del título) + **keywords** (de los `tags` del video) |
| Región | Fija por config (`MX`) para el MVP; selector de país fuera de alcance |
| Caché | En memoria con TTL ~1h para ahorrar cuota |
| Interacción | Clic en chip → llena el buscador y ejecuta la búsqueda |

## Backend (`yt-clipper-api`)

### Dominio (`domain/`)
- Nuevo `domain/trends.py` (o dentro de `domain/video.py`) con value objects:
  - `TrendingVideo(title: str, tags: list[str])` — datos crudos de un video en tendencia.
  - `SearchSuggestion(text: str, kind: str)` — `kind` es `"hashtag"` o `"topic"`.
- Excepciones nuevas en `domain/exceptions.py`:
  - `TrendsUnavailableError(DomainError)` — no hay `YOUTUBE_API_KEY`.
  - `TrendsError(DomainError)` — fallo de la API de YouTube.

### Puertos (`application/ports.py`)
- `TrendsProvider(Protocol)`:
  - `get_trending(self, region: str, max_results: int) -> list[TrendingVideo]`

### Aplicación (`application/use_cases.py`)
- `GetSearchSuggestionsUseCase(provider: TrendsProvider)`:
  - `execute(region: str, limit: int) -> list[SearchSuggestion]`:
    - `bounded = max(1, min(limit, MAX_SUGGESTIONS))` (`MAX_SUGGESTIONS = 30`).
    - `videos = provider.get_trending(region, TRENDING_FETCH_SIZE)` (`TRENDING_FETCH_SIZE = 25`).
    - Por cada video:
      - **hashtags**: extraer del título con regex `#[\wÁÉÍÓÚáéíóúñÑ]+` → `SearchSuggestion(text=tag, kind="hashtag")`.
      - **topics**: de `tags`, tomar los que midan ≤ 30 caracteres → `SearchSuggestion(text=tag, kind="topic")`.
    - Deduplicar por `text.lower()` (conservando el primer `kind` visto), preservando orden de
      inserción (primero los hashtags de cada video, luego sus keywords).
    - Recortar a `bounded`.
  - Nota: la validación/normalización vive aquí; el adaptador solo trae datos crudos.

### Infraestructura (`infrastructure/trends/youtube_trends.py`)
- `YouTubeTrendsProvider(api_key: str, ttl_seconds: int, client=None)`:
  - `get_trending(region, max_results)`:
    - Consulta caché en memoria por `region` (módulo-level `dict[str, tuple[float, list[TrendingVideo]]]`);
      si hay entrada fresca (`now - ts < ttl_seconds`) la devuelve.
    - Si no, `GET https://www.googleapis.com/youtube/v3/videos` con params
      `part=snippet, chart=mostPopular, regionCode=<region>, maxResults=<max_results>, key=<api_key>`
      (usa `httpx`, timeout ~15s).
    - Errores HTTP/red → `TrendsError`.
    - Mapea `items[].snippet` → `TrendingVideo(title=snippet["title"], tags=snippet.get("tags", []))`.
    - Guarda en caché y devuelve.
  - El `client` inyectable (objeto con `.get(url, params=...)`) permite testear sin red.
- `UnavailableTrendsProvider`:
  - `get_trending(...)` lanza `TrendsUnavailableError("Configura YOUTUBE_API_KEY ...")`.

### HTTP (`interfaces/http/`)
- Schemas (`schemas.py`):
  - `SuggestionResponse { text: str, kind: str }`
  - `SuggestionsResponse { suggestions: list[SuggestionResponse] }`
- Dependencias (`dependencies.py`):
  - `get_trends_provider(settings)`: si `settings.youtube_api_key` → `YouTubeTrendsProvider(...)`;
    si no → `UnavailableTrendsProvider()`.
  - `get_suggestions_use_case(provider)`.
- Ruta (`routes.py`), en el router protegido:
  - `GET /api/v1/suggestions?region=&limit=15`:
    - `region: str | None = Query(default=None)`, `limit: int = Query(default=15, ge=1, le=30)`.
    - `region_value = region or settings.trends_region`.
    - `use_case.execute(region_value, limit)`.
    - Errores: `TrendsUnavailableError` → 503; `TrendsError` → 502; `DomainError` → 400.
  - Respuesta: `SuggestionsResponse`.

### Config (`config.py`)
- `youtube_api_key: str | None = None`
- `trends_region: str = "MX"`
- `trends_cache_ttl_seconds: int = 3600`

### Dependencias (`pyproject.toml`)
- Mover/añadir `httpx` a las dependencias de runtime (hoy está solo en `dev`).

## Frontend (`yt-clipper-studio`)

### Tipos (`domain/models.ts`)
- `SearchSuggestion { text: string; kind: string }`
- `BackendSuggestion { text: string; kind: string }` (idéntico; el backend usa snake-neutral).

### API client (`infrastructure/api/downloadApi.ts`)
- `getSuggestions(limit = 15): Promise<SearchSuggestion[]>` → `GET /api/v1/suggestions?limit=15`.
  - En 503 (sin key) lanza; el llamador lo trata como "sin sugerencias" (oculta la sección).

### UI (`App.tsx`)
- Estado `suggestions: SearchSuggestion[]` y `suggestionsError: boolean`.
- En el montaje (o con un botón "Actualizar tendencias"), llamar `getSuggestions()` best-effort:
  éxito → llenar `suggestions`; error → dejar vacío (sección oculta).
- Renderizar una sección **"Tendencias"** con chips (`<button class="suggestion-chip">`) para
  cada sugerencia (mostrando `text`; los hashtags ya incluyen `#`).
- **Clic en un chip**: setear el término de búsqueda a `suggestion.text` y ejecutar la búsqueda
  (reutilizando el mismo camino que el submit del formulario, respetando `maxDuration`). Para
  esto, extraer un helper `runSearch(term: string)` a partir del handler actual
  `handleSearchVideos`, y que tanto el submit como el chip lo usen.
- Si `suggestions` está vacío, no renderizar la sección (o mostrar un aviso sutil si hubo 503).

## Contratos JSON (referencia)

`GET /api/v1/suggestions?region=MX&limit=15` →
```json
{ "suggestions": [
  { "text": "#futbol", "kind": "hashtag" },
  { "text": "resumen liga mx", "kind": "topic" }
] }
```
`503` si no hay `YOUTUBE_API_KEY`; `502` si la API de YouTube falla.

## Testing

**Backend** (cobertura ≥85%):
- `GetSearchSuggestionsUseCase`: extrae hashtags del título + keywords de tags, deduplica
  case-insensitive, recorta a `limit` (fake provider con `TrendingVideo`s de ejemplo).
- `YouTubeTrendsProvider`: con un `client` fake que devuelve un JSON de `items`, mapea a
  `TrendingVideo`; segunda llamada usa **caché** (el client fake se llama una sola vez); error
  del client → `TrendsError`.
- `UnavailableTrendsProvider.get_trending` → `TrendsUnavailableError`.
- Endpoint: `GET /suggestions` 200 con sugerencias (use case fake); 503 cuando el provider
  no está disponible.

**Frontend** (Vitest + Testing Library):
- `downloadApi.getSuggestions` (200 mapea; 503 lanza).
- `App`: monta y muestra chips desde `getSuggestions`; clic en un chip dispara la búsqueda con
  ese término (el fetch a `/api/v1/search` incluye `q=<chip>`); si `getSuggestions` falla, la
  sección no aparece y el resto de la app funciona.

## Fuera de alcance (YAGNI)

- Selector de país en la UI (región fija por config en el MVP).
- Filtro por categoría de trending (`videoCategoryId`).
- Persistencia/caché en disco (solo memoria con TTL).
- Sugerencias generadas por IA (se optó por tendencias reales vía YouTube Data API).

## Riesgos y mitigaciones

- **Cuota de YouTube API**: `mostPopular` cuesta ~1 unidad; el **caché TTL 1h** evita gastar
  en cada carga. 10k unidades/día es amplio.
- **Videos sin `tags`/hashtags**: algunos trending no traen `tags` ni hashtags; se omiten. El
  `TRENDING_FETCH_SIZE=25` da margen para juntar suficientes sugerencias.
- **Sin key configurada**: 503 explícito y la sección se oculta en el frontend; el resto de la
  app no se ve afectada.
- **`.env` bloqueado para edición** por permisos: el usuario añade `YOUTUBE_API_KEY` a su
  `.env` manualmente; se documenta en `.env.example` si es editable.
