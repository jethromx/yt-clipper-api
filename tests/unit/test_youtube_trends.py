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
    def __init__(
        self, response: FakeResponse | None = None, raises: Exception | None = None
    ) -> None:
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
