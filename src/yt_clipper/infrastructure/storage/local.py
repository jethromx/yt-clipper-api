import shutil
from pathlib import Path

from yt_clipper.domain.video import DownloadJob


class LocalFileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare_download_path(self, job: DownloadJob) -> Path:
        path = self.root / str(job.id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def prepare_clip_path(self, job: DownloadJob, source_path: Path) -> Path:
        suffix = source_path.suffix or ".mp4"
        return self.root / str(job.id) / f"clip{suffix}"

    def cleanup_download_path(self, job: DownloadJob) -> None:
        path = self.root / str(job.id)
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    def resolve(self, relative_path: str) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            return path
        return self.root / path
