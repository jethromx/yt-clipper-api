import pytest

from yt_clipper.domain.exceptions import (
    CaptionGenerationError,
    CaptionGeneratorUnavailableError,
)
from yt_clipper.domain.video import VideoMetadata
from yt_clipper.infrastructure.ai.anthropic_caption import (
    AnthropicCaptionGenerator,
    UnavailableCaptionGenerator,
)


class _Block:
    def __init__(self, name, data):  # type: ignore[no-untyped-def]
        self.type = "tool_use"
        self.name = name
        self.input = data


class _Response:
    def __init__(self, blocks):  # type: ignore[no-untyped-def]
        self.content = blocks


class FakeMessages:
    def __init__(self, response=None, raises=None):  # type: ignore[no-untyped-def]
        self._response = response
        self._raises = raises
        self.kwargs = None

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.kwargs = kwargs
        if self._raises:
            raise self._raises
        return self._response


class FakeClient:
    def __init__(self, messages):  # type: ignore[no-untyped-def]
        self.messages = messages


def _metadata() -> VideoMetadata:
    return VideoMetadata(video_id="abc", title="Titulo", description="Desc", tags=["x"])


def test_unavailable_generator_raises() -> None:
    with pytest.raises(CaptionGeneratorUnavailableError):
        UnavailableCaptionGenerator().generate(_metadata())


def test_anthropic_generator_parses_tool_use() -> None:
    response = _Response(
        [
            _Block(
                "emit_tiktok_caption",
                {"caption": "Mira esto ", "hashtags": ["viral", "#viral", "perros"]},
            )
        ]
    )
    client = FakeClient(FakeMessages(response=response))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    caption = generator.generate(_metadata())

    assert caption.caption == "Mira esto"
    assert caption.hashtags == ["#viral", "#perros"]


def test_anthropic_generator_wraps_sdk_errors() -> None:
    client = FakeClient(FakeMessages(raises=RuntimeError("boom")))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    with pytest.raises(CaptionGenerationError):
        generator.generate(_metadata())


def test_anthropic_generator_errors_when_no_tool_use() -> None:
    client = FakeClient(FakeMessages(response=_Response([])))
    generator = AnthropicCaptionGenerator(model="claude-haiku-4-5", client=client)

    with pytest.raises(CaptionGenerationError):
        generator.generate(_metadata())
