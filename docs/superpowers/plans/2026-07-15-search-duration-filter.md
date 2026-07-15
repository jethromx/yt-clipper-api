# Search Duration Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir un filtro de duración máxima a la búsqueda de YouTube para descubrir/descargar solo videos cortos (para TikTok).

**Architecture:** Backend: `SearchVideosUseCase` acepta `max_duration_seconds`, sobre-pide al provider y filtra por duración; el endpoint `GET /search` expone el parámetro. Frontend: `searchVideos` envía el parámetro y `App.tsx` añade un selector de presets.

**Tech Stack:** Python 3.12, FastAPI, pytest. Frontend: React 18 + TS + Vite + Vitest + Testing Library.

**Branches:** backend ya está en `feat/search-duration-filter`. En el frontend, crear/usar la rama `feat/search-duration-filter` (`git checkout -b feat/search-duration-filter` desde `main`) antes de la primera tarea de frontend.

**Comandos:** backend desde `yt-clipper-api/` con `.venv/bin/python`; frontend desde `yt-clipper-studio/` con `npm`.

---

## Parte 1 — Backend (`yt-clipper-api`, rama `feat/search-duration-filter`)

### Task 1: SearchVideosUseCase — filtro por duración

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_search_and_batch_use_cases.py`

Contexto actual:
```python
MAX_SEARCH_LIMIT = 50

class SearchVideosUseCase:
    def __init__(self, video_provider: VideoProvider) -> None:
        self.video_provider = video_provider

    def execute(self, query: str, limit: int) -> list[VideoSearchResult]:
        if not query.strip():
            raise EmptySearchQueryError("query must not be empty")
        bounded = max(1, min(limit, MAX_SEARCH_LIMIT))
        return self.video_provider.search(query.strip(), bounded)
```
El fake `FakeSearchProvider` existente en el test devuelve `[VideoSearchResult(video_id="abc", title="t", url="u")]` y registra `(query, limit)` en `self.calls`.

- [ ] **Step 1: Escribir los tests que fallan.** Añadir a `tests/unit/application/test_search_and_batch_use_cases.py`:

```python
class DurationSearchProvider:
    def __init__(self, results: list[VideoSearchResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int) -> list[VideoSearchResult]:
        self.calls.append((query, limit))
        return self.results


def _result(video_id: str, duration: float | None) -> VideoSearchResult:
    return VideoSearchResult(
        video_id=video_id, title=video_id, url=f"u/{video_id}", duration_seconds=duration
    )


def test_search_filters_by_max_duration_and_excludes_unknown() -> None:
    provider = DurationSearchProvider(
        [_result("a", 30), _result("b", 120), _result("c", None), _result("d", 60)]
    )
    use_case = SearchVideosUseCase(provider)

    results = use_case.execute("perros", limit=10, max_duration_seconds=60)

    assert [r.video_id for r in results] == ["a", "d"]


def test_search_overfetches_when_filtering() -> None:
    provider = DurationSearchProvider([_result("a", 10)])
    use_case = SearchVideosUseCase(provider)

    use_case.execute("perros", limit=10, max_duration_seconds=60)

    # over-fetch: limit*3 = 30 (<= MAX_SEARCH_LIMIT)
    assert provider.calls == [("perros", 30)]


def test_search_trims_filtered_results_to_limit() -> None:
    provider = DurationSearchProvider([_result(str(i), 10) for i in range(10)])
    use_case = SearchVideosUseCase(provider)

    results = use_case.execute("perros", limit=3, max_duration_seconds=60)

    assert len(results) == 3


def test_search_without_max_duration_keeps_current_behavior() -> None:
    provider = DurationSearchProvider([_result("a", 10)])
    use_case = SearchVideosUseCase(provider)

    use_case.execute("perros", limit=5)

    assert provider.calls == [("perros", 5)]
```
(`VideoSearchResult` y `SearchVideosUseCase` ya se importan en el archivo; si `VideoSearchResult` no está importado, añádelo desde `yt_clipper.domain.video`.)

- [ ] **Step 2: Ver que fallan** — `.venv/bin/python -m pytest tests/unit/application/test_search_and_batch_use_cases.py -q` → FAIL (`execute()` no acepta `max_duration_seconds`).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/application/use_cases.py`:

1. Añadir la constante junto a `MAX_SEARCH_LIMIT`:
```python
OVER_FETCH_FACTOR = 3
```
2. Reemplazar `SearchVideosUseCase.execute` por:
```python
    def execute(
        self, query: str, limit: int, max_duration_seconds: int | None = None
    ) -> list[VideoSearchResult]:
        if not query.strip():
            raise EmptySearchQueryError("query must not be empty")
        bounded = max(1, min(limit, MAX_SEARCH_LIMIT))
        if max_duration_seconds is None:
            return self.video_provider.search(query.strip(), bounded)
        fetch_limit = min(bounded * OVER_FETCH_FACTOR, MAX_SEARCH_LIMIT)
        results = self.video_provider.search(query.strip(), fetch_limit)
        filtered = [
            result
            for result in results
            if result.duration_seconds is not None
            and result.duration_seconds <= max_duration_seconds
        ]
        return filtered[:bounded]
```

- [ ] **Step 4: Ver que pasan** — `.venv/bin/python -m pytest tests/unit/application/test_search_and_batch_use_cases.py -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/application/use_cases.py tests/unit/application/test_search_and_batch_use_cases.py` → limpio.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_search_and_batch_use_cases.py
git commit -m "feat(usecase): filter search results by max duration"
```

---

### Task 2: Endpoint /search — parámetro max_duration_seconds

**Files:**
- Modify: `src/yt_clipper/interfaces/http/routes.py`
- Test: `tests/integration/test_http_api.py`

Contexto actual:
```python
@router.get("/search", response_model=SearchResponse)
def search_videos(
    q: str = Query(...),
    limit: int = Query(default=20, ge=1, le=50),
    use_case: SearchVideosUseCase = Depends(get_search_use_case),
) -> SearchResponse:
    try:
        results = use_case.execute(q, limit)
    except DomainError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SearchResponse(results=[SearchResultResponse.from_domain(r) for r in results])
```
El test de integración ya tiene un `FakeSearchUseCase` con `execute(self, query, limit)`. Hay que ampliarlo para aceptar y registrar `max_duration_seconds`.

- [ ] **Step 1: Escribir el test que falla.** En `tests/integration/test_http_api.py`:

1. Reemplazar la clase `FakeSearchUseCase` existente por:
```python
class FakeSearchUseCase:
    def __init__(self) -> None:
        self.received_max_duration: int | None = "unset"  # type: ignore[assignment]

    def execute(self, query: str, limit: int, max_duration_seconds=None):  # type: ignore[no-untyped-def]
        self.received_max_duration = max_duration_seconds
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
```
2. Añadir un test nuevo:
```python
def test_search_passes_max_duration_seconds() -> None:
    app = create_app()
    use_case = FakeSearchUseCase()
    app.dependency_overrides[get_search_use_case] = lambda: use_case
    client = TestClient(app)

    response = client.get(
        "/api/v1/search",
        params={"q": "perros", "limit": 5, "max_duration_seconds": 60},
        headers={"X-API-Key": "dev-secret-change-me"},
    )

    assert response.status_code == 200
    assert use_case.received_max_duration == 60
```
(Si el test existente `test_search_returns_results` usa `FakeSearchUseCase` sin instanciarlo con el nuevo `__init__`, sigue siendo compatible: la firma `execute` acepta `max_duration_seconds` por defecto `None`.)

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → FAIL (el endpoint aún no pasa el parámetro; `received_max_duration` queda en `"unset"`).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/interfaces/http/routes.py`, reemplazar `search_videos` por:
```python
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
```

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → PASS. Luego `.venv/bin/python -m ruff check src/yt_clipper/interfaces/http/routes.py tests/integration/test_http_api.py`, `.venv/bin/python -m mypy`, y full `.venv/bin/python -m pytest -q` (todo verde, cobertura ≥85%).

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/interfaces/http/routes.py tests/integration/test_http_api.py
git commit -m "feat(http): add max_duration_seconds to search endpoint"
```

---

## Parte 2 — Frontend (`yt-clipper-studio`, rama `feat/search-duration-filter`)

Primero: `git checkout -b feat/search-duration-filter` desde `main` (si aún no existe).

### Task 3: Cliente API — searchVideos con maxDurationSeconds

**Files:**
- Modify: `src/infrastructure/api/downloadApi.ts`
- Test: `src/infrastructure/api/downloadApi.test.ts`

Contexto actual:
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
    return body.results.map((result) => ({ /* ...map... */ }))
  }
```

- [ ] **Step 1: Tests que fallan.** Añadir a `src/infrastructure/api/downloadApi.test.ts`:
```typescript
it('searchVideos adds max_duration_seconds when provided', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  await client.searchVideos('perros', 5, 60)

  expect(fetchMock.mock.calls[0][0]).toContain('max_duration_seconds=60')
})

it('searchVideos omits max_duration_seconds when not provided', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  await client.searchVideos('perros', 5)

  expect(fetchMock.mock.calls[0][0]).not.toContain('max_duration_seconds')
})
```

- [ ] **Step 2: Ver que fallan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → FAIL.

- [ ] **Step 3: Implementar.** En `src/infrastructure/api/downloadApi.ts`, cambiar la firma y la construcción de params de `searchVideos`:
```typescript
  async searchVideos(
    query: string,
    limit = 20,
    maxDurationSeconds?: number,
  ): Promise<VideoSearchResult[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) })
    if (maxDurationSeconds !== undefined) {
      params.set('max_duration_seconds', String(maxDurationSeconds))
    }
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
```

- [ ] **Step 4: Ver que pasan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → PASS. `npm run lint` → limpio.

- [ ] **Step 5: Commit**
```bash
git add src/infrastructure/api/downloadApi.ts src/infrastructure/api/downloadApi.test.ts
git commit -m "feat(api): pass max_duration_seconds to search"
```

---

### Task 4: UI — selector de duración

**Files:**
- Modify: `src/App.tsx`, `src/App.css`
- Test: `src/App.test.tsx`

- [ ] **Step 1: Leer App.tsx.** Leer `src/App.tsx` y `src/App.test.tsx`. Localizar: el estado `searchQuery`, el handler de búsqueda (llama `apiClient.searchVideos(searchQuery)` — puede pasar `limit`), y el formulario de búsqueda (input con placeholder `/buscar/i` + botón "Buscar"). El backend se mockea en los tests vía `fetch` por URL.

- [ ] **Step 2: Test que falla.** Añadir a `src/App.test.tsx` (adaptar al patrón real de render/fetch-mock del archivo):
```typescript
it('envía max_duration_seconds al elegir un preset de duración', async () => {
  const user = userEvent.setup()
  // fetch mock: responder a GET /api/v1/models y a GET /api/v1/search (capturando la URL)
  // render App con un portfolio activo (patrón del archivo)

  await user.selectOptions(screen.getByLabelText(/duración/i), '60')
  await user.type(screen.getByPlaceholderText(/buscar/i), 'perros')
  await user.click(screen.getByRole('button', { name: /buscar/i }))

  // assert: la petición a /api/v1/search incluyó max_duration_seconds=60
  await waitFor(() => {
    const searchCall = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
      .map((c) => String(c[0]))
      .find((u) => u.includes('/api/v1/search'))
    expect(searchCall).toContain('max_duration_seconds=60')
  })
})
```
Ajustar la obtención de las llamadas de `fetch` al patrón del archivo (si usan un `fetchMock` local en vez de `globalThis.fetch`, úsalo).

- [ ] **Step 3: Ver que falla** — `npm run test -- src/App.test.tsx` → FAIL.

- [ ] **Step 4: Implementar en App.tsx.**
1. Estado nuevo:
```typescript
const [maxDuration, setMaxDuration] = useState<number | undefined>(undefined)
```
2. En el formulario de búsqueda, junto al input, un select accesible:
```tsx
<select
  aria-label="Duración"
  value={maxDuration ?? ''}
  onChange={(e) => setMaxDuration(e.target.value ? Number(e.target.value) : undefined)}
>
  <option value="">Cualquiera</option>
  <option value="60">≤ 1 min</option>
  <option value="180">≤ 3 min</option>
  <option value="300">≤ 5 min</option>
  <option value="600">≤ 10 min</option>
</select>
```
3. En el handler de búsqueda, pasar `maxDuration` a `searchVideos`. Localiza la llamada real (algo como `apiClient.searchVideos(searchQuery)` o `apiClient.searchVideos(searchQuery, N)`) y cámbiala a:
```typescript
const results = await apiClient.searchVideos(searchQuery, /* limit real, p. ej. 20 */ 20, maxDuration)
```
Usa el `limit` que ya use el componente (si hoy no pasa `limit`, usa el default `20` explícito para poder pasar el tercer argumento).

- [ ] **Step 5: Estilos** — en `src/App.css`, estilar el nuevo `<select>` de duración acorde a la barra de búsqueda existente.

- [ ] **Step 6: Ver que pasa** — `npm run test -- src/App.test.tsx` → PASS; luego `npm run test` completo sin regresiones. `npm run lint`.

- [ ] **Step 7: Commit**
```bash
git add src/App.tsx src/App.css src/App.test.tsx
git commit -m "feat(ui): add duration filter to search"
```

---

### Task 5: Verificación

- [ ] **Step 1: Backend gate** (desde `yt-clipper-api/`):
```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```
Todo PASS, cobertura ≥85%. Si `ruff format --check` marca algo, `ruff format .` y recomprobar.

- [ ] **Step 2: Frontend gate** (desde `yt-clipper-studio/`):
```bash
npm run lint
npm run test:coverage
npm run build
```
Todo PASS, cobertura sobre umbrales (branches 75, functions 80, lines 80, statements 80). Si algún umbral baja, añadir un test dirigido (p. ej. el select en "Cualquiera" NO envía el parámetro).

- [ ] **Step 3: e2e (opcional, Docker)** — reconstruir el stack y probar:
```bash
curl -s -H 'X-API-Key: dev-secret-change-me' \
  'http://localhost:8000/api/v1/search?q=perros&limit=5&max_duration_seconds=60' \
  | python3 -c "import sys,json; [print(r['duration_seconds']) for r in json.load(sys.stdin)['results']]"
```
Esperado: todas las duraciones ≤ 60.

---

## Notas
- **YAGNI**: solo filtro por duración máxima en la búsqueda; sin reformateo vertical ni recorte del archivo (la descarga parcial ya existe aparte).
- **Sobre-pedido**: `limit*3` con tope `MAX_SEARCH_LIMIT (50)`; sin filtro no hay sobre-pedido.
- **Cobertura backend**: el filtro y el sobre-pedido se cubren con unit tests del use case; el paso del parámetro con el test de integración.
