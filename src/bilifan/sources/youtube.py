from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .base import SourceOptions, VideoRef


class YouTubeAdapter:
    platform = "youtube"

    def can_parse(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(self._video_id(parsed))

    def parse_url(self, url: str) -> VideoRef:
        parsed = urlparse(url)
        video_id = self._video_id(parsed)
        if not video_id:
            raise ValueError("Invalid YouTube video URL.")
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        return VideoRef(
            platform=self.platform,
            source_id=video_id,
            part_id="p1",
            canonical_url=canonical_url,
            raw_url=url,
        )

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        timestamp = max(0, int(seconds))
        return f"https://www.youtube.com/watch?v={ref.source_id}&t={timestamp}s"

    def output_id(self, ref: VideoRef) -> str:
        return f"YT{ref.source_id}_p1"

    def fetch_metadata(
        self,
        ref: VideoRef,
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        raise NotImplementedError("YouTube metadata is implemented in the YouTube slice.")

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        raise NotImplementedError("YouTube audio is implemented in the YouTube slice.")

    def _video_id(self, parsed) -> str:
        host = parsed.netloc.lower()
        if host == "youtu.be":
            return parsed.path.strip("/")
        if host in {"www.youtube.com", "youtube.com"} and parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        return ""
