import os
from urllib.parse import urlparse

import pytest

from bilifan.bilibili import parse_bilibili_url
from bilifan.metadata import fetch_current_part_metadata


REAL_BILIBILI_URLS = [
    (
        "https://www.bilibili.com/video/BV14kVE6eEtC"
        "?spm_id_from=333.788.player.player_end_recommend"
        "&vd_source=39fc5b438dea96faea88e7841fb3d0ca"
        "&trackid=web_related_0.router-related-2589621-kz84p.1780846547972.446"
    ),
    "https://www.bilibili.com/video/BV1xuVC6AEbg/?spm_id_from=333.1391.0.0",
    "https://www.bilibili.com/video/BV1ETEF6VEHu/?spm_id_from=333.1391.0.0",
]


@pytest.mark.metadata_smoke
@pytest.mark.skipif(
    os.environ.get("BILIFAN_METADATA_SMOKE") != "1",
    reason="Set BILIFAN_METADATA_SMOKE=1 to hit live Bilibili with yt-dlp.",
)
@pytest.mark.parametrize("url", REAL_BILIBILI_URLS)
def test_live_metadata_smoke_for_real_bilibili_urls(tmp_path, url):
    ref = parse_bilibili_url(url)

    metadata = fetch_current_part_metadata(ref, tmp_path / ref.output_id)

    assert metadata["input_url_sanitized"] == ref.sanitized_url
    assert metadata["video_id"] == ref.bvid
    assert metadata["part_index"] == ref.part_index
    assert metadata["title"]
    assert metadata["owner_name"]
    assert metadata["cid"]
    assert metadata["duration"] is None or metadata["duration"] > 0
    assert isinstance(metadata["parts"], list)
    assert isinstance(metadata["subtitles"], list)
    assert metadata["cover_url"]
    assert not urlparse(metadata["cover_url"]).query
    assert not urlparse(metadata["cover_url"]).fragment
    if metadata["cover_path"]:
        assert (tmp_path / ref.output_id / metadata["cover_path"]).is_file()
    assert metadata["provenance"]["metadata_attempted_source"] == "yt-dlp"
    assert metadata["metadata_source"] in {"yt-dlp", "bilibili-public-api"}
    assert metadata["provenance"]["metadata_source"] == metadata["metadata_source"]
    assert metadata["provenance"]["video_id"] == ref.bvid
