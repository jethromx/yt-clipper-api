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
    provider = FakeTrendsProvider([TrendingVideo(title="hola", tags=["x" * 40, "corto"])])
    use_case = GetSearchSuggestionsUseCase(provider)

    suggestions = use_case.execute(region="MX", limit=10)

    assert [s.text for s in suggestions] == ["corto"]
