from __future__ import annotations

from pathlib import Path
from typing import Any

from bilifan.bilibili import BilibiliPartRef, parse_bilibili_url
from bilifan.media import download_current_part_audio
from bilifan.metadata import fetch_current_part_metadata

from .base import SourceOptions, VideoRef


class BilibiliAdapter:
    platform = "bilibili"

    def can_parse(self, url: str) -> bool:
        try:
            parse_bilibili_url(url)
        except ValueError:
            return False
        return True

    def parse_url(self, url: str) -> VideoRef:
        ref = parse_bilibili_url(url)
        return VideoRef(
            platform=self.platform,
            source_id=ref.bvid,
            part_id=f"p{ref.part_index}",
            canonical_url=ref.sanitized_url,
            raw_url=url,
        )

    def legacy_ref(self, ref: VideoRef) -> BilibiliPartRef:
        part_index = int(ref.part_id.removeprefix("p") or "1")
        return BilibiliPartRef(
            bvid=ref.source_id,
            part_index=part_index,
            sanitized_url=ref.canonical_url,
        )

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        return self.legacy_ref(ref).timestamp_url(seconds)

    def output_id(self, ref: VideoRef) -> str:
        return self.legacy_ref(ref).output_id

    def fetch_metadata(
        self,
        ref: VideoRef,
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        return fetch_current_part_metadata(
            self.legacy_ref(ref),
            run_dir,
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        return download_current_part_audio(
            self.legacy_ref(ref),
            metadata,
            run_dir,
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )
