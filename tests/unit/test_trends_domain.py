from yt_clipper.domain.trends import SearchSuggestion, TrendingVideo


def test_trending_video_holds_title_and_tags() -> None:
    video = TrendingVideo(title="Un titulo #viral", tags=["futbol", "gol"])
    assert video.title == "Un titulo #viral"
    assert video.tags == ["futbol", "gol"]


def test_search_suggestion_holds_text_and_kind() -> None:
    suggestion = SearchSuggestion(text="#viral", kind="hashtag")
    assert suggestion.text == "#viral"
    assert suggestion.kind == "hashtag"
