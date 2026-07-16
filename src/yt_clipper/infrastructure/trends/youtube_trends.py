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
        raise TrendsUnavailableError("Configura YOUTUBE_API_KEY para obtener tendencias")


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
        except Exception as exc:  # network / HTTP / parse
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
