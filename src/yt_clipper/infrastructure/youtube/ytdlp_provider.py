from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from yt_clipper.domain.video import VideoMetadata


class YtDlpVideoProvider:
    def __init__(self, socket_timeout_seconds: int) -> None:
        self.socket_timeout_seconds = socket_timeout_seconds

    def get_metadata(self, source_url: str) -> VideoMetadata:
        options = self._base_options()
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(source_url, download=False)
        return self._metadata_from_info(info)

    def download_best(self, source_url: str, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(output_dir / "%(title).120s-%(id)s.%(ext)s")
        options = {
            **self._base_options(),
            "format": "bestvideo*+bestaudio/best",
            "merge_output_format": "mp4",
            "outtmpl": output_template,
            "restrictfilenames": True,
            "noplaylist": True,
        }
        before = set(output_dir.iterdir())
        with YoutubeDL(options) as downloader:
            downloader.download([source_url])
        created_files = [
            path for path in output_dir.iterdir() if path not in before and path.is_file()
        ]
        if not created_files:
            raise RuntimeError("yt-dlp finished without creating an output file")
        return max(created_files, key=lambda path: path.stat().st_mtime)

    def _base_options(self) -> dict[str, Any]:
        return {
            "quiet": True,
            "socket_timeout": self.socket_timeout_seconds,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 3,
            "file_access_retries": 3,
            "http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            },
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
        }

    @staticmethod
    def _metadata_from_info(info: dict[str, Any] | None) -> VideoMetadata:
        if not info:
            raise RuntimeError("yt-dlp did not return metadata")
        return VideoMetadata(
            video_id=str(info.get("id") or ""),
            title=str(info.get("title") or "untitled"),
            duration_seconds=info.get("duration"),
            webpage_url=info.get("webpage_url"),
        )
