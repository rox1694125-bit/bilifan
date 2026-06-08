import pytest

from bilifan.sources import SourceAdapterError, resolve_source_adapter
from bilifan.sources.bilibili import BilibiliAdapter
from bilifan.sources.youtube import YouTubeAdapter


def test_resolve_source_adapter_returns_bilibili():
    adapter = resolve_source_adapter("https://www.bilibili.com/video/BV1abcDEF12G?p=2")

    ref = adapter.parse_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    assert isinstance(adapter, BilibiliAdapter)
    assert adapter.platform == "bilibili"
    assert ref.platform == "bilibili"
    assert ref.source_id == "BV1abcDEF12G"
    assert ref.part_id == "p2"
    assert adapter.output_id(ref) == "BV1abcDEF12G_p2"
    assert adapter.timestamp_url(ref, 12.8).endswith("&t=12")


def test_resolve_source_adapter_returns_youtube():
    adapter = resolve_source_adapter("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert isinstance(adapter, YouTubeAdapter)
    assert adapter.platform == "youtube"
    assert ref.platform == "youtube"
    assert ref.source_id == "dQw4w9WgXcQ"
    assert ref.part_id == "p1"
    assert ref.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert adapter.output_id(ref) == "YTdQw4w9WgXcQ_p1"
    assert adapter.timestamp_url(ref, 12.8).endswith("&t=12s")


def test_resolve_source_adapter_returns_youtube_short_url():
    adapter = resolve_source_adapter("https://youtu.be/dQw4w9WgXcQ?t=10")

    ref = adapter.parse_url("https://youtu.be/dQw4w9WgXcQ?t=10")
    assert ref.source_id == "dQw4w9WgXcQ"
    assert ref.canonical_url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_resolve_source_adapter_rejects_unknown_url():
    with pytest.raises(SourceAdapterError, match="Unsupported video URL"):
        resolve_source_adapter("https://example.com/video/1")
