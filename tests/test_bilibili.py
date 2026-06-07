import pytest

from bilifan.bilibili import BilibiliPartRef, parse_bilibili_url


def test_parse_bilibili_url_with_explicit_part_and_tracking_params():
    ref = parse_bilibili_url(
        "https://www.bilibili.com/video/BV1abcDEF12G/?p=2&spm_id_from=333.999"
    )

    assert ref == BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=2,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    )
    assert ref.output_id == "BV1abcDEF12G_p2"
    assert ref.timestamp_url(1234.7) == (
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=1234"
    )


def test_parse_bilibili_url_defaults_to_part_one():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G")

    assert ref.part_index == 1
    assert ref.sanitized_url == "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
    assert ref.output_id == "BV1abcDEF12G_p1"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/BV1abcDEF12G",
        "https://www.bilibili.com/read/cv123",
        "not a url",
    ],
)
def test_parse_bilibili_url_rejects_unsupported_urls(url):
    with pytest.raises(ValueError, match="supported Bilibili video URL"):
        parse_bilibili_url(url)


def test_parse_bilibili_url_rejects_invalid_part_index():
    with pytest.raises(ValueError, match="positive integer"):
        parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=0")
