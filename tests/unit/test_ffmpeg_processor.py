from pathlib import Path
from unittest.mock import Mock

from yt_clipper.domain.video import ClipRange
from yt_clipper.infrastructure.media import ffmpeg_processor
from yt_clipper.infrastructure.media.ffmpeg_processor import FfmpegMediaProcessor


def test_ffmpeg_processor_invokes_ffmpeg(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    run = Mock()
    monkeypatch.setattr(ffmpeg_processor.subprocess, "run", run)
    output_path = tmp_path / "clip.mp4"

    result = FfmpegMediaProcessor(timeout_seconds=10).clip(
        tmp_path / "source.mp4",
        ClipRange(1, 2),
        output_path,
    )

    assert result == output_path
    run.assert_called_once()
    assert run.call_args.kwargs["check"] is True
    assert run.call_args.kwargs["timeout"] == 10
