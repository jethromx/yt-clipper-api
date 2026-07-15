from pathlib import Path

from yt_clipper.application.ports import DownloadResult
from yt_clipper.domain.video import VideoSearchResult
from yt_clipper.infrastructure.youtube import ytdlp_provider
from yt_clipper.infrastructure.youtube.ytdlp_provider import YtDlpVideoProvider


def test_ytdlp_metadata_maps_info() -> None:
    metadata = YtDlpVideoProvider._metadata_from_info(
        {
            "id": "abc123",
            "title": "Example",
            "duration": 42,
            "webpage_url": "https://www.youtube.com/watch?v=abc123",
        }
    )

    assert metadata.video_id == "abc123"
    assert metadata.title == "Example"
    assert metadata.duration_seconds == 42


def test_ytdlp_download_returns_created_file(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):  # type: ignore[no-untyped-def]
            self.options = options
            captured_options.update(options)

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
            return None

        def extract_info(self, source_url, download):  # type: ignore[no-untyped-def]
            (tmp_path / "video.mp4").write_text("content")
            return {
                "id": "abc123",
                "title": "Example",
                "duration": 42,
                "webpage_url": source_url,
            }

    monkeypatch.setattr(ytdlp_provider, "YoutubeDL", FakeYoutubeDL)

    result = YtDlpVideoProvider(socket_timeout_seconds=5).download_best(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path,
    )

    assert result == DownloadResult(
        path=tmp_path / "video.mp4",
        metadata=YtDlpVideoProvider._metadata_from_info(
            {
                "id": "abc123",
                "title": "Example",
                "duration": 42,
                "webpage_url": "https://www.youtube.com/watch?v=abc123",
            }
        ),
    )
    assert captured_options["retries"] == 5
    assert captured_options["fragment_retries"] == 5
    assert captured_options["extractor_args"]["youtube"]["player_client"] == ["android", "web"]
    assert "Mozilla/5.0" in captured_options["http_headers"]["User-Agent"]


def test_ytdlp_metadata_uses_resilient_options(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured_options = {}

    class FakeYoutubeDL:
        def __init__(self, options):  # type: ignore[no-untyped-def]
            captured_options.update(options)

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, exc_type, exc, traceback):  # type: ignore[no-untyped-def]
            return None

        def extract_info(self, source_url, download):  # type: ignore[no-untyped-def]
            return {
                "id": "abc123",
                "title": "Example",
                "duration": 42,
                "webpage_url": source_url,
            }

    monkeypatch.setattr(ytdlp_provider, "YoutubeDL", FakeYoutubeDL)

    metadata = YtDlpVideoProvider(socket_timeout_seconds=5).get_metadata(
        "https://www.youtube.com/watch?v=abc123"
    )

    assert metadata.video_id == "abc123"
    assert captured_options["socket_timeout"] == 5
    assert captured_options["extractor_retries"] == 3
    assert captured_options["extractor_args"]["youtube"]["player_client"] == ["android", "web"]


def test_ytdlp_metadata_rejects_empty_info() -> None:
    try:
        YtDlpVideoProvider._metadata_from_info(None)
    except RuntimeError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_metadata_from_info_captures_description_and_tags() -> None:
    provider = YtDlpVideoProvider(socket_timeout_seconds=5)

    metadata = provider._metadata_from_info(
        {
            "id": "abc",
            "title": "Titulo",
            "duration": 10,
            "webpage_url": "https://youtu.be/abc",
            "description": "Desc",
            "tags": ["a", "b"],
        }
    )

    assert metadata.description == "Desc"
    assert metadata.tags == ["a", "b"]


def test_search_maps_entries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeYoutubeDL:
        def __init__(self, options):  # type: ignore[no-untyped-def]
            self.options = options

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return False

        def extract_info(self, query, download):  # type: ignore[no-untyped-def]
            assert query == "ytsearch2:perros"
            assert download is False
            return {
                "entries": [
                    {
                        "id": "abc",
                        "title": "Perro 1",
                        "duration": 12,
                        "channel": "Canal",
                        "thumbnails": [{"url": "https://i.ytimg.com/abc.jpg"}],
                    },
                    {"id": None, "title": "descartado"},
                ]
            }

    monkeypatch.setattr("yt_clipper.infrastructure.youtube.ytdlp_provider.YoutubeDL", FakeYoutubeDL)
    provider = YtDlpVideoProvider(socket_timeout_seconds=5)

    results = provider.search("perros", limit=2)

    assert results == [
        VideoSearchResult(
            video_id="abc",
            title="Perro 1",
            url="https://www.youtube.com/watch?v=abc",
            duration_seconds=12,
            channel="Canal",
            thumbnail_url="https://i.ytimg.com/abc.jpg",
        )
    ]
