import subprocess
from pathlib import Path

from yt_clipper.domain.video import ClipRange


class FfmpegMediaProcessor:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds

    def clip(self, input_path: Path, clip_range: ClipRange, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(clip_range.start_seconds),
            "-to",
            str(clip_range.end_seconds),
            "-i",
            str(input_path),
            "-c",
            "copy",
            str(output_path),
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=self.timeout_seconds)
        return output_path
