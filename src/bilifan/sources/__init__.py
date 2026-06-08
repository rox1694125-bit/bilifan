from __future__ import annotations

from .base import SourceAdapter, SourceOptions, VideoRef
from .bilibili import BilibiliAdapter
from .youtube import YouTubeAdapter


class SourceAdapterError(ValueError):
    pass


def resolve_source_adapter(url: str) -> SourceAdapter:
    for adapter in (BilibiliAdapter(), YouTubeAdapter()):
        if adapter.can_parse(url):
            return adapter
    raise SourceAdapterError(
        "Unsupported video URL. Bilifan supports Bilibili and YouTube public video URLs."
    )


__all__ = [
    "BilibiliAdapter",
    "SourceAdapter",
    "SourceAdapterError",
    "SourceOptions",
    "VideoRef",
    "YouTubeAdapter",
    "resolve_source_adapter",
]
