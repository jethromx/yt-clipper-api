# Diseño: Filtro de duración en la búsqueda (videos cortos para TikTok)

- Fecha: 2026-07-15
- Estado: Aprobado (pendiente de plan)
- Repos: `yt-clipper-api` (backend), `yt-clipper-studio` (frontend)

## Resumen

Añadir un filtro de duración a la búsqueda de YouTube para poder elegir solo videos
cortos, pensados para subir a TikTok. El filtro se aplica en el backend (el endpoint de
búsqueda ya devuelve la duración de cada resultado); el frontend expone un selector con
presets de duración.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Dónde se filtra | Backend: nuevo parámetro `max_duration_seconds` en `GET /search` |
| Resultados sin duración conocida | Se **excluyen** cuando el filtro está activo |
| Evitar listas vacías | El use case **sobre-pide** al provider y luego recorta a `limit` |
| UI | Selector con presets: Cualquiera / ≤1 min / ≤3 min / ≤5 min / ≤10 min |

## Backend (`yt-clipper-api`)

**Caso de uso** (`application/use_cases.py`):
- `SearchVideosUseCase.execute(query, limit, max_duration_seconds: int | None = None) -> list[VideoSearchResult]`:
  - Valida `query` no vacío (igual que hoy) y hace clamp de `limit` a `[1, MAX_SEARCH_LIMIT]`.
  - Si `max_duration_seconds is None`: comportamiento actual — `provider.search(query, limit)`.
  - Si `max_duration_seconds` está presente:
    - Sobre-pide: `fetch_limit = min(limit * OVER_FETCH_FACTOR, MAX_SEARCH_LIMIT)`
      (con `OVER_FETCH_FACTOR = 3`).
    - Llama `provider.search(query, fetch_limit)`.
    - Filtra: conserva los resultados con `duration_seconds is not None` y
      `duration_seconds <= max_duration_seconds`.
    - Recorta el resultado filtrado a `limit`.
  - `max_duration_seconds`, si se pasa, debe ser `>= 1`; valores `< 1` se tratan como
    "sin filtro" (o el endpoint lo rechaza vía validación de query — ver HTTP).

**HTTP** (`interfaces/http/routes.py`):
- `GET /api/v1/search` gana el parámetro:
  `max_duration_seconds: int | None = Query(default=None, ge=1)`.
- Se pasa al use case: `use_case.execute(q, limit, max_duration_seconds=max_duration_seconds)`.
- Sin cambios en `SearchResponse`/`SearchResultResponse` (ya incluyen `duration_seconds`).

## Frontend (`yt-clipper-studio`)

**API client** (`infrastructure/api/downloadApi.ts`):
- `searchVideos(query, limit = 20, maxDurationSeconds?: number)`: si `maxDurationSeconds`
  está definido, añade `max_duration_seconds` a la query string.

**UI** (`App.tsx`):
- Junto a la barra de búsqueda, un `<select aria-label="Duración">` con opciones:
  - `Cualquiera` → sin filtro (`undefined`)
  - `≤ 1 min` → `60`
  - `≤ 3 min` → `180`
  - `≤ 5 min` → `300`
  - `≤ 10 min` → `600`
- Estado `maxDuration: number | undefined` (default `undefined` = Cualquiera). Se pasa a
  `searchVideos(query, limit, maxDuration)` al buscar.
- (Opcional, fuera de alcance de MVP) persistir la selección en localStorage.

## Contratos JSON (referencia)

`GET /api/v1/search?q=perros&limit=20&max_duration_seconds=60` →
```json
{ "results": [ { "video_id": "...", "title": "...", "duration_seconds": 45.0, ... } ] }
```
Todos los `results` tienen `duration_seconds <= 60`.

## Testing

**Backend** (cobertura ≥85%):
- `SearchVideosUseCase.execute` con `max_duration_seconds`: filtra los que exceden el
  máximo y los de duración `None`; sobre-pide (`fetch_limit = limit*3` cap 50) y recorta a
  `limit`; sin `max_duration_seconds` mantiene el comportamiento actual (fake provider que
  registra el `limit` recibido y devuelve resultados con distintas duraciones).
- Endpoint `GET /search?...&max_duration_seconds=60`: 200 y solo resultados cortos
  (con un use case fake que verifica que recibió el parámetro).

**Frontend** (Vitest + Testing Library):
- `downloadApi.searchVideos` añade `max_duration_seconds` cuando se pasa, y lo omite
  cuando no.
- `App`: al elegir un preset en el selector de duración y buscar, la petición incluye
  `max_duration_seconds` correcto.

## Fuera de alcance (YAGNI)

- Reformateo vertical 9:16 o recorte de duración del archivo descargado (esta feature es
  solo filtro de descubrimiento; la descarga parcial por `start/end` ya existe aparte).
- Filtro por duración mínima o rango (solo máximo).
- Persistencia del preset entre sesiones (se puede añadir luego).

## Riesgos y mitigaciones

- **Duración ausente en `extract_flat`**: algunas entradas de `ytsearch` no traen
  `duration`; se excluyen bajo filtro (mitigación: el sobre-pedido compensa la pérdida).
- **Sobre-pedido y latencia**: `limit*3` con tope 50 mantiene acotada la llamada a
  yt-dlp; sin filtro no se sobre-pide (sin coste extra).
