from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class VideoRef:
    platform: str
    source_id: str
    part_id: str
    canonical_url: str
    raw_url: str

    @property
    def output_id(self) -> str:
        return f"{self.source_id}_{self.part_id}"


@dataclass(frozen=True)
class SourceOptions:
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    language: str = "auto"
    force_whisper: bool = False


class SourceAdapter(Protocol):
    platform: str

    def can_parse(self, url: str) -> bool:
        raise NotImplementedError

    def parse_url(self, url: str) -> VideoRef:
        raise NotImplementedError

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        raise NotImplementedError

    def output_id(self, ref: VideoRef) -> str:
        raise NotImplementedError

    def fetch_metadata(
        self,
        ref: VideoRef,
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        raise NotImplementedError
