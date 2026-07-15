# Search Suggestions (Trends) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Añadir una sección de sugerencias de búsqueda (chips de hashtags/keywords) derivadas de las tendencias reales de YouTube (Data API `mostPopular`), que al pulsarse ejecutan la búsqueda.

**Architecture:** Backend hexagonal: value objects `TrendingVideo`/`SearchSuggestion`, puerto `TrendsProvider`, adaptador `YouTubeTrendsProvider` (httpx + caché TTL) o `UnavailableTrendsProvider`, use case que deriva sugerencias, y endpoint `GET /suggestions`. Frontend: cliente `getSuggestions` + sección de chips en `App.tsx` que reutiliza el flujo de búsqueda.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest. Frontend: React 18 + TS + Vite + Vitest + Testing Library.

**Branches:** backend en `feat/search-suggestions` (ya creada). Frontend: crear `feat/search-suggestions` desde `main` antes de la primera tarea de frontend.

**Comandos:** backend desde `yt-clipper-api/` con `.venv/bin/python`; frontend desde `yt-clipper-studio/` con `npm`.

---

## Parte 1 — Backend (`yt-clipper-api`, rama `feat/search-suggestions`)

### Task 1: Dominio — value objects + excepciones

**Files:**
- Create: `src/yt_clipper/domain/trends.py`
- Modify: `src/yt_clipper/domain/exceptions.py`
- Test: `tests/unit/test_trends_domain.py`

- [ ] **Step 1: Test que falla.** Crear `tests/unit/test_trends_domain.py`:
```python
from yt_clipper.domain.trends import SearchSuggestion, TrendingVideo


def test_trending_video_holds_title_and_tags() -> None:
    video = TrendingVideo(title="Un titulo #viral", tags=["futbol", "gol"])
    assert video.title == "Un titulo #viral"
    assert video.tags == ["futbol", "gol"]


def test_search_suggestion_holds_text_and_kind() -> None:
    suggestion = SearchSuggestion(text="#viral", kind="hashtag")
    assert suggestion.text == "#viral"
    assert suggestion.kind == "hashtag"
```

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/test_trends_domain.py -q` → FAIL (módulo inexistente).

- [ ] **Step 3: Implementar.** Crear `src/yt_clipper/domain/trends.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TrendingVideo:
    title: str
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchSuggestion:
    text: str
    kind: str
```
Añadir a `src/yt_clipper/domain/exceptions.py`:
```python
class TrendsUnavailableError(DomainError):
    """Raised when no YouTube API key is configured for trends."""


class TrendsError(DomainError):
    """Raised when the YouTube trends API call fails."""
```

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/test_trends_domain.py -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/domain/trends.py tests/unit/test_trends_domain.py` → limpio.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/domain/trends.py src/yt_clipper/domain/exceptions.py tests/unit/test_trends_domain.py
git commit -m "feat(domain): add trending video and search suggestion value objects"
```

---

### Task 2: Puerto TrendsProvider

**Files:**
- Modify: `src/yt_clipper/application/ports.py`

- [ ] **Step 1: Implementar.** En `src/yt_clipper/application/ports.py`:
1. Añadir al import de dominio de trends:
```python
from yt_clipper.domain.trends import TrendingVideo
```
2. Añadir el Protocol (junto a los otros):
```python
class TrendsProvider(Protocol):
    def get_trending(self, region: str, max_results: int) -> list[TrendingVideo]: ...
```

- [ ] **Step 2: Verificar** — `.venv/bin/python -c "import yt_clipper.application.ports"` sin error; `.venv/bin/python -m ruff check src/yt_clipper/application/ports.py` limpio.

- [ ] **Step 3: Commit**
```bash
git add src/yt_clipper/application/ports.py
git commit -m "feat(ports): add TrendsProvider protocol"
```

---

### Task 3: Use case GetSearchSuggestionsUseCase

**Files:**
- Modify: `src/yt_clipper/application/use_cases.py`
- Test: `tests/unit/application/test_get_search_suggestions_use_case.py` (crear)

- [ ] **Step 1: Test que falla.** Crear `tests/unit/application/test_get_search_suggestions_use_case.py`:
```python
from yt_clipper.application.use_cases import GetSearchSuggestionsUseCase
from yt_clipper.domain.trends import SearchSuggestion, TrendingVideo


class FakeTrendsProvider:
    def __init__(self, videos: list[TrendingVideo]) -> None:
        self.videos = videos
        self.calls: list[tuple[str, int]] = []

    def get_trending(self, region: str, max_results: int) -> list[TrendingVideo]:
        self.calls.append((region, max_results))
        return self.videos


def test_extracts_hashtags_and_topics_dedupes_and_caps() -> None:
    provider = FakeTrendsProvider(
        [
            TrendingVideo(title="Gran partido #futbol #GOL", tags=["liga mx", "futbol"]),
            TrendingVideo(title="Resumen #futbol", tags=["gol"]),
        ]
    )
    use_case = GetSearchSuggestionsUseCase(provider)

    suggestions = use_case.execute(region="MX", limit=10)
    texts = [s.text for s in suggestions]

    # order: per video, hashtags first then topic tags; dedupe by lowercased text
    assert texts[:3] == ["#futbol", "#GOL", "liga mx"]
    assert texts.count("#futbol") == 1  # "#futbol" from video 2 deduped
    assert "futbol" in texts  # the tag "futbol" is distinct text from "#futbol"
    assert SearchSuggestion(text="#futbol", kind="hashtag") in suggestions


def test_caps_to_limit() -> None:
    provider = FakeTrendsProvider(
        [TrendingVideo(title=f"#h{i}", tags=[f"t{i}"]) for i in range(20)]
    )
    use_case = GetSearchSuggestionsUseCase(provider)

    suggestions = use_case.execute(region="MX", limit=5)

    assert len(suggestions) == 5


def test_excludes_long_tags_and_empty() -> None:
    provider = FakeTrendsProvider(
        [TrendingVideo(title="hola", tags=["x" * 40, "corto"])]
    )
    use_case = GetSearchSuggestionsUseCase(provider)

    suggestions = use_case.execute(region="MX", limit=10)

    assert [s.text for s in suggestions] == ["corto"]
```
(El dedupe es por `text.lower()` exacto: `"#futbol"` y `"futbol"` son textos distintos y NO se deduplican entre sí.)

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/application/test_get_search_suggestions_use_case.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/application/use_cases.py`:
1. Añadir imports:
```python
import re

from yt_clipper.domain.trends import SearchSuggestion, TrendingVideo
```
(Colocar `import re` con los imports de stdlib al inicio; los de dominio con los demás `from yt_clipper.domain...`.)
2. Añadir constantes y el use case al final del archivo:
```python
MAX_SUGGESTIONS = 30
TRENDING_FETCH_SIZE = 25
MAX_TAG_LENGTH = 30
_HASHTAG_RE = re.compile(r"#[\wÀ-ſ]+", re.UNICODE)


class GetSearchSuggestionsUseCase:
    def __init__(self, provider: TrendsProvider) -> None:
        self.provider = provider

    def execute(self, region: str, limit: int) -> list[SearchSuggestion]:
        bounded = max(1, min(limit, MAX_SUGGESTIONS))
        videos = self.provider.get_trending(region, TRENDING_FETCH_SIZE)
        suggestions: list[SearchSuggestion] = []
        seen: set[str] = set()
        for video in videos:
            for candidate in self._candidates(video):
                key = candidate.text.lower()
                if not candidate.text or key in seen:
                    continue
                seen.add(key)
                suggestions.append(candidate)
                if len(suggestions) >= bounded:
                    return suggestions
        return suggestions

    @staticmethod
    def _candidates(video: TrendingVideo) -> list[SearchSuggestion]:
        result = [
            SearchSuggestion(text=match, kind="hashtag")
            for match in _HASHTAG_RE.findall(video.title)
        ]
        result.extend(
            SearchSuggestion(text=tag, kind="topic")
            for tag in video.tags
            if tag and len(tag) <= MAX_TAG_LENGTH
        )
        return result
```
Añadir `TrendsProvider` al import desde `yt_clipper.application.ports` (junto a los demás puertos que ya se importan ahí).

- [ ] **Step 4: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/application/test_get_search_suggestions_use_case.py -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/application/use_cases.py tests/unit/application/test_get_search_suggestions_use_case.py`.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/application/use_cases.py tests/unit/application/test_get_search_suggestions_use_case.py
git commit -m "feat(usecase): derive search suggestions from trending videos"
```

---

### Task 4: Config + dependencia httpx

**Files:**
- Modify: `src/yt_clipper/config.py`, `pyproject.toml`
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Test que falla.** Añadir a `tests/unit/test_config.py`:
```python
def test_settings_expose_trends_defaults(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from yt_clipper.config import Settings

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.youtube_api_key is None
    assert settings.trends_region == "MX"
    assert settings.trends_cache_ttl_seconds == 3600
```

- [ ] **Step 2: Ver que falla** — `.venv/bin/python -m pytest tests/unit/test_config.py -q` → FAIL (AttributeError).

- [ ] **Step 3: Implementar.** En `src/yt_clipper/config.py`, dentro de `Settings`, añadir tras los campos `anthropic_*`:
```python
    youtube_api_key: str | None = None
    trends_region: str = "MX"
    trends_cache_ttl_seconds: int = 3600
```
En `pyproject.toml`, añadir `httpx` a la lista `[project]` `dependencies` (runtime), p. ej. antes de `imageio-ffmpeg`:
```toml
    "httpx>=0.27.0",
```
(y déjalo también en dev si ya está — pip lo resolverá igual).

- [ ] **Step 4: Instalar** — `.venv/bin/python -m pip install -e '.[dev]'` → sin errores.

- [ ] **Step 5: Ver que pasa** — `.venv/bin/python -m pytest tests/unit/test_config.py -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/config.py`.

- [ ] **Step 6: Commit**
```bash
git add src/yt_clipper/config.py pyproject.toml
git commit -m "feat(config): add youtube trends settings and httpx dependency"
```

---

### Task 5: Adaptadores de tendencias (YouTube + Unavailable)

**Files:**
- Create: `src/yt_clipper/infrastructure/trends/__init__.py`
- Create: `src/yt_clipper/infrastructure/trends/youtube_trends.py`
- Test: `tests/unit/test_youtube_trends.py` (crear)

- [ ] **Step 1: Tests que fallan.** Crear `tests/unit/test_youtube_trends.py`:
```python
import pytest

from yt_clipper.domain.exceptions import TrendsError, TrendsUnavailableError
from yt_clipper.infrastructure.trends.youtube_trends import (
    UnavailableTrendsProvider,
    YouTubeTrendsProvider,
)


class FakeResponse:
    def __init__(self, payload: dict, raise_status: Exception | None = None) -> None:
        self._payload = payload
        self._raise_status = raise_status

    def raise_for_status(self) -> None:
        if self._raise_status is not None:
            raise self._raise_status

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, response: FakeResponse | None = None, raises: Exception | None = None) -> None:
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: float):  # type: ignore[no-untyped-def]
        self.calls.append(params)
        if self.raises is not None:
            raise self.raises
        return self.response


_PAYLOAD = {
    "items": [
        {"snippet": {"title": "Gran gol #futbol", "tags": ["liga mx", "gol"]}},
        {"snippet": {"title": "sin tags"}},
    ]
}


def test_unavailable_provider_raises() -> None:
    with pytest.raises(TrendsUnavailableError):
        UnavailableTrendsProvider().get_trending("MX", 25)


def test_youtube_provider_maps_items() -> None:
    client = FakeClient(response=FakeResponse(_PAYLOAD))
    provider = YouTubeTrendsProvider(api_key="k", ttl_seconds=3600, client=client)

    videos = provider.get_trending("MX", 25)

    assert videos[0].title == "Gran gol #futbol"
    assert videos[0].tags == ["liga mx", "gol"]
    assert videos[1].tags == []
    assert client.calls[0]["regionCode"] == "MX"
    assert client.calls[0]["chart"] == "mostPopular"


def test_youtube_provider_uses_cache() -> None:
    client = FakeClient(response=FakeResponse(_PAYLOAD))
    provider = YouTubeTrendsProvider(api_key="k", ttl_seconds=3600, client=client)

    provider.get_trending("MXCACHE", 25)
    provider.get_trending("MXCACHE", 25)

    assert len(client.calls) == 1  # segunda llamada sale de caché


def test_youtube_provider_wraps_errors() -> None:
    client = FakeClient(raises=RuntimeError("boom"))
    provider = YouTubeTrendsProvider(api_key="k", ttl_seconds=3600, client=client)

    with pytest.raises(TrendsError):
        provider.get_trending("MXERR", 25)
```
Nota: los tests usan `region` distintos (`MXCACHE`, `MXERR`) para no colisionar con la caché de módulo entre tests.

- [ ] **Step 2: Ver que fallan** — `.venv/bin/python -m pytest tests/unit/test_youtube_trends.py -q` → FAIL (módulo inexistente).

- [ ] **Step 3: Implementar.** Crear `src/yt_clipper/infrastructure/trends/__init__.py` vacío. Crear `src/yt_clipper/infrastructure/trends/youtube_trends.py`:
```python
from __future__ import annotations

import time
from typing import Any

from yt_clipper.domain.exceptions import TrendsError, TrendsUnavailableError
from yt_clipper.domain.trends import TrendingVideo

_API_URL = "https://www.googleapis.com/youtube/v3/videos"
_TIMEOUT_SECONDS = 15.0
_CACHE: dict[str, tuple[float, list[TrendingVideo]]] = {}


class UnavailableTrendsProvider:
    def get_trending(self, region: str, max_results: int) -> list[TrendingVideo]:
        raise TrendsUnavailableError(
            "Configura YOUTUBE_API_KEY para obtener tendencias"
        )


class YouTubeTrendsProvider:
    def __init__(self, api_key: str, ttl_seconds: int, client: Any | None = None) -> None:
        self.api_key = api_key
        self.ttl_seconds = ttl_seconds
        if client is not None:
            self._client = client
        else:
            import httpx

            self._client = httpx.Client()

    def get_trending(self, region: str, max_results: int) -> list[TrendingVideo]:
        cached = _CACHE.get(region)
        if cached is not None and (time.monotonic() - cached[0]) < self.ttl_seconds:
            return cached[1]
        try:
            response = self._client.get(
                _API_URL,
                params={
                    "part": "snippet",
                    "chart": "mostPopular",
                    "regionCode": region,
                    "maxResults": max_results,
                    "key": self.api_key,
                },
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # red / HTTP / parse
            raise TrendsError(str(exc)) from exc
        videos = [self._to_video(item) for item in payload.get("items", [])]
        _CACHE[region] = (time.monotonic(), videos)
        return videos

    @staticmethod
    def _to_video(item: dict[str, Any]) -> TrendingVideo:
        snippet = item.get("snippet") or {}
        return TrendingVideo(
            title=str(snippet.get("title") or ""),
            tags=[str(tag) for tag in (snippet.get("tags") or [])],
        )
```

- [ ] **Step 4: Ver que pasan** — `.venv/bin/python -m pytest tests/unit/test_youtube_trends.py -q` → PASS. `.venv/bin/python -m ruff check src/yt_clipper/infrastructure/trends tests/unit/test_youtube_trends.py` → limpio. `.venv/bin/python -m mypy` → sin errores nuevos en estos archivos.

- [ ] **Step 5: Commit**
```bash
git add src/yt_clipper/infrastructure/trends tests/unit/test_youtube_trends.py
git commit -m "feat(trends): add youtube and unavailable trends providers with cache"
```

---

### Task 6: Schemas, dependencias y ruta /suggestions

**Files:**
- Modify: `src/yt_clipper/interfaces/http/schemas.py`
- Modify: `src/yt_clipper/interfaces/http/dependencies.py`
- Modify: `src/yt_clipper/interfaces/http/routes.py`
- Test: `tests/integration/test_http_api.py`

- [ ] **Step 1: Tests que fallan.** Añadir a `tests/integration/test_http_api.py`:
```python
from yt_clipper.domain.exceptions import TrendsUnavailableError
from yt_clipper.domain.trends import SearchSuggestion
from yt_clipper.interfaces.http.dependencies import get_suggestions_use_case


class FakeSuggestionsUseCase:
    def execute(self, region: str, limit: int) -> list[SearchSuggestion]:
        return [SearchSuggestion(text="#futbol", kind="hashtag")]


class UnavailableSuggestionsUseCase:
    def execute(self, region: str, limit: int) -> list[SearchSuggestion]:
        raise TrendsUnavailableError("configura la key")


def test_suggestions_returns_list() -> None:
    app = create_app()
    app.dependency_overrides[get_suggestions_use_case] = lambda: FakeSuggestionsUseCase()
    client = TestClient(app)

    response = client.get(
        "/api/v1/suggestions", headers={"X-API-Key": "dev-secret-change-me"}
    )

    assert response.status_code == 200
    assert response.json()["suggestions"][0]["text"] == "#futbol"


def test_suggestions_unavailable_returns_503() -> None:
    app = create_app()
    app.dependency_overrides[get_suggestions_use_case] = lambda: UnavailableSuggestionsUseCase()
    client = TestClient(app)

    response = client.get(
        "/api/v1/suggestions", headers={"X-API-Key": "dev-secret-change-me"}
    )

    assert response.status_code == 503
```

- [ ] **Step 2: Ver que fallan** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → FAIL (404 / ImportError).

- [ ] **Step 3: Implementar schemas.** En `src/yt_clipper/interfaces/http/schemas.py`, añadir al final:
```python
class SuggestionResponse(BaseModel):
    text: str
    kind: str


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionResponse]
```

- [ ] **Step 4: Implementar dependencias.** En `src/yt_clipper/interfaces/http/dependencies.py`:
1. Añadir imports:
```python
from yt_clipper.application.ports import TrendsProvider
from yt_clipper.application.use_cases import GetSearchSuggestionsUseCase
from yt_clipper.infrastructure.trends.youtube_trends import (
    UnavailableTrendsProvider,
    YouTubeTrendsProvider,
)
```
2. Añadir factorías:
```python
def get_trends_provider(settings: Settings = Depends(get_settings)) -> TrendsProvider:
    if not settings.youtube_api_key:
        return UnavailableTrendsProvider()
    return YouTubeTrendsProvider(
        api_key=settings.youtube_api_key,
        ttl_seconds=settings.trends_cache_ttl_seconds,
    )


def get_suggestions_use_case(
    provider: TrendsProvider = Depends(get_trends_provider),
) -> GetSearchSuggestionsUseCase:
    return GetSearchSuggestionsUseCase(provider)
```

- [ ] **Step 5: Implementar ruta.** En `src/yt_clipper/interfaces/http/routes.py`:
1. Ampliar imports: use case `GetSearchSuggestionsUseCase`; excepciones `TrendsError`, `TrendsUnavailableError`; dependencia `get_suggestions_use_case`; schemas `SuggestionResponse`, `SuggestionsResponse`; config `Settings, get_settings` (si no están ya importados de tasks previas). Verifica los imports existentes y añade solo lo que falte.
2. Añadir la ruta (después de `search_videos`):
```python
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
```
Nota de orden: `TrendsUnavailableError` y `TrendsError` son subclases de `DomainError`, por eso van ANTES del `except DomainError`.

- [ ] **Step 6: Ver que pasan** — `.venv/bin/python -m pytest tests/integration/test_http_api.py -q` → PASS. Luego `.venv/bin/python -m ruff check` en los 4 archivos, `.venv/bin/python -m mypy`, y full `.venv/bin/python -m pytest -q` (todo verde, cobertura ≥85%).

- [ ] **Step 7: Commit**
```bash
git add src/yt_clipper/interfaces/http tests/integration/test_http_api.py
git commit -m "feat(http): add suggestions endpoint"
```

---

### Task 7: Verificación backend

- [ ] **Step 1: Gate completo**
```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest
```
Todo PASS, cobertura ≥85%. Si `ruff format --check` marca algo, `.venv/bin/python -m ruff format .` y recomprobar.

- [ ] **Step 2: Commit (si hubo formato)**
```bash
git add -A && git commit -m "chore(backend): ruff format"
```

---

## Parte 2 — Frontend (`yt-clipper-studio`)

Primero: `git checkout -b feat/search-suggestions` desde `main`.

### Task 8: Tipos de dominio

**Files:**
- Modify: `src/domain/models.ts`

- [ ] **Step 1: Añadir tipos.** Al final de `src/domain/models.ts`:
```typescript
export interface SearchSuggestion {
  text: string
  kind: string
}

export interface BackendSuggestion {
  text: string
  kind: string
}
```

- [ ] **Step 2: Verificar** — `npx tsc -b --noEmit` sin errores nuevos.

- [ ] **Step 3: Commit**
```bash
git add src/domain/models.ts
git commit -m "feat(models): add SearchSuggestion type"
```

---

### Task 9: Cliente API — getSuggestions

**Files:**
- Modify: `src/infrastructure/api/downloadApi.ts`
- Test: `src/infrastructure/api/downloadApi.test.ts`

- [ ] **Step 1: Tests que fallan.** Añadir a `src/infrastructure/api/downloadApi.test.ts`:
```typescript
it('getSuggestions maps backend suggestions', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ suggestions: [{ text: '#futbol', kind: 'hashtag' }] }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  const result = await client.getSuggestions(15)

  expect(result[0]).toEqual({ text: '#futbol', kind: 'hashtag' })
  expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/suggestions?limit=15')
})

it('getSuggestions throws on 503', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 503, text: async () => 'no key' })
  vi.stubGlobal('fetch', fetchMock)
  const client = new DownloadApiClient('http://api', 'key')

  await expect(client.getSuggestions()).rejects.toThrow()
})
```

- [ ] **Step 2: Ver que fallan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → FAIL.

- [ ] **Step 3: Implementar.** En `src/infrastructure/api/downloadApi.ts`:
1. Ampliar el import de tipos con `BackendSuggestion, SearchSuggestion`.
2. Añadir método:
```typescript
  async getSuggestions(limit = 15): Promise<SearchSuggestion[]> {
    const params = new URLSearchParams({ limit: String(limit) })
    const response = await fetch(`${this.baseUrl}/api/v1/suggestions?${params.toString()}`, {
      headers: this.headers(),
    })
    if (!response.ok) {
      throw new Error(`API ${response.status}: ${await this.getErrorDetail(response)}`)
    }
    const body = (await response.json()) as { suggestions: BackendSuggestion[] }
    return body.suggestions.map((s) => ({ text: s.text, kind: s.kind }))
  }
```

- [ ] **Step 4: Ver que pasan** — `npm run test -- src/infrastructure/api/downloadApi.test.ts` → PASS. `npm run lint`.

- [ ] **Step 5: Commit**
```bash
git add src/infrastructure/api/downloadApi.ts src/infrastructure/api/downloadApi.test.ts
git commit -m "feat(api): add getSuggestions"
```

---

### Task 10: UI — sección de chips de tendencias

**Files:**
- Modify: `src/App.tsx`, `src/App.css`
- Test: `src/App.test.tsx`

Contexto: el handler actual es
```typescript
async function handleSearchVideos(event: FormEvent<HTMLFormElement>) {
  event.preventDefault()
  const trimmedQuery = videoQuery.trim()
  if (!trimmedQuery) return
  setIsSearching(true)
  setSearchError('')
  try {
    const results = await apiClient.searchVideos(trimmedQuery, 20, maxDuration)
    setSearchResults(results)
    setSelectedVideoIds(new Set())
  } catch (error) {
    setSearchError(error instanceof Error ? error.message : 'No se pudo buscar videos')
  } finally {
    setIsSearching(false)
  }
}
```
Estado existente: `videoQuery`/`setVideoQuery`, `searchResults`, `maxDuration`, `isSearching`, `searchError`, `setSelectedVideoIds`.

- [ ] **Step 1: Leer** `src/App.tsx` y `src/App.test.tsx` para el patrón real (fetch-mock por URL, cómo se monta App, el `search-form`).

- [ ] **Step 2: Test que falla.** Añadir a `src/App.test.tsx` (adaptar al patrón del archivo). El mock de `fetch` debe responder a `GET /api/v1/models`, `GET /api/v1/suggestions` (→ `{ suggestions:[{text:'#futbol',kind:'hashtag'}] }`) y `GET /api/v1/search` (→ `{ results: [] }`):
```typescript
it('muestra chips de tendencias y al pulsar uno busca ese término', async () => {
  const user = userEvent.setup()
  // configurar fetch mock por URL (incluyendo /api/v1/suggestions)
  // render App con un portfolio activo

  const chip = await screen.findByRole('button', { name: '#futbol' })
  await user.click(chip)

  await waitFor(() => {
    const calls = (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls
    const searchUrl = calls.map((c) => String(c[0])).find((u) => u.includes('/api/v1/search'))
    expect(searchUrl).toBeTruthy()
    expect(searchUrl).toContain('q=%23futbol')
  })
})
```
Adaptar el acceso a `fetch` al patrón del archivo (variable `fetchMock` local si aplica). `%23` es `#` url-encoded.

- [ ] **Step 3: Ver que falla** — `npm run test -- src/App.test.tsx` → FAIL.

- [ ] **Step 4: Implementar en App.tsx.**
1. Estado:
```typescript
const [suggestions, setSuggestions] = useState<SearchSuggestion[]>([])
```
(importar `SearchSuggestion` de `./domain/models`).
2. Extraer un helper `runSearch` y reusarlo desde el submit y los chips:
```typescript
async function runSearch(term: string) {
  const trimmedQuery = term.trim()
  if (!trimmedQuery) return
  setIsSearching(true)
  setSearchError('')
  try {
    const results = await apiClient.searchVideos(trimmedQuery, 20, maxDuration)
    setSearchResults(results)
    setSelectedVideoIds(new Set())
  } catch (error) {
    setSearchError(error instanceof Error ? error.message : 'No se pudo buscar videos')
  } finally {
    setIsSearching(false)
  }
}

async function handleSearchVideos(event: FormEvent<HTMLFormElement>) {
  event.preventDefault()
  await runSearch(videoQuery)
}

function handleSuggestionClick(term: string) {
  setVideoQuery(term)
  void runSearch(term)
}
```
3. Cargar sugerencias al montar (best-effort):
```typescript
useEffect(() => {
  apiClient
    .getSuggestions()
    .then(setSuggestions)
    .catch(() => setSuggestions([]))
}, [])
```
4. Renderizar la sección de chips encima del `search-form` (solo si hay sugerencias):
```tsx
{suggestions.length > 0 && (
  <div className="suggestions">
    <span className="suggestions-label">Tendencias</span>
    <div className="suggestion-chips">
      {suggestions.map((s) => (
        <button
          key={s.text}
          type="button"
          className="suggestion-chip"
          onClick={() => handleSuggestionClick(s.text)}
        >
          {s.text}
        </button>
      ))}
    </div>
  </div>
)}
```

- [ ] **Step 5: Estilos** — en `src/App.css`, estilar `.suggestions`, `.suggestions-label`, `.suggestion-chips`, `.suggestion-chip` acorde al diseño existente.

- [ ] **Step 6: Ver que pasa** — `npm run test -- src/App.test.tsx` → PASS; luego full `npm run test`. `npm run lint`.

- [ ] **Step 7: Commit**
```bash
git add src/App.tsx src/App.css src/App.test.tsx
git commit -m "feat(ui): add trending suggestion chips to search"
```

---

### Task 11: Verificación (backend + frontend + e2e)

- [ ] **Step 1: Frontend gate** (desde `yt-clipper-studio/`):
```bash
npm run lint
npm run test:coverage
npm run build
```
Todo PASS, cobertura sobre umbrales (branches 75, functions 80, lines 80, statements 80). Si algún umbral baja, añadir un test dirigido (p. ej. cuando `getSuggestions` falla la sección no aparece).

- [ ] **Step 2: e2e (Docker)** — reconstruir el stack (necesita `httpx` en la imagen y `YOUTUBE_API_KEY` en el `.env` del usuario para datos reales):
```bash
cd ../yt-clipper-api
ENV_FILE=.env POSTGRES_PORT=5433 FRONTEND_PORT=8081 docker compose \
  -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.cors-8081.yml up --build -d
```
Probar:
```bash
curl -s -H 'X-API-Key: dev-secret-change-me' 'http://localhost:8000/api/v1/suggestions?limit=10'
```
Esperado: con `YOUTUBE_API_KEY` configurada → `{ "suggestions": [...] }`; sin ella → **503** con mensaje "Configura YOUTUBE_API_KEY".

- [ ] **Step 3: Documentar** — recordar al usuario añadir a su `.env`:
```dotenv
YOUTUBE_API_KEY=<tu-key>
TRENDS_REGION=MX
```
(El `.env` lo edita el usuario; los archivos `.env` están bloqueados para las herramientas.)

---

## Notas
- **Caché de módulo**: `_CACHE` en `youtube_trends.py` persiste entre requests del mismo proceso; los tests usan regiones distintas para no colisionar.
- **Cuota**: `mostPopular` ~1 unidad + caché TTL 1h → consumo mínimo.
- **Sin key**: 503 explícito; el frontend oculta la sección (carga best-effort con `.catch`).
- **httpx**: pasa a dependencia de runtime; la imagen Docker lo instalará al reconstruir.
