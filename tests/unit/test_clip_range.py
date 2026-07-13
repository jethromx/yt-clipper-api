import pytest

from yt_clipper.domain.exceptions import InvalidClipRangeError
from yt_clipper.domain.video import ClipRange, DownloadJob


def test_clip_range_calculates_duration() -> None:
    clip_range = ClipRange(start_seconds=10, end_seconds=25.5)

    assert clip_range.duration_seconds == 15.5


def test_clip_range_rejects_negative_start() -> None:
    with pytest.raises(InvalidClipRangeError):
        ClipRange(start_seconds=-1, end_seconds=10)


def test_clip_range_rejects_end_before_start() -> None:
    with pytest.raises(InvalidClipRangeError):
        ClipRange(start_seconds=20, end_seconds=10)


def test_download_job_knows_when_it_is_a_clip() -> None:
    job = DownloadJob(
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        clip_range=ClipRange(1, 2),
    )

    assert job.is_clip is True
