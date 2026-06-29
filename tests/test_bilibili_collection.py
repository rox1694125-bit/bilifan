from bilifan.bilibili_collection import preview_bilibili_collection


def test_preview_bilibili_collection_expands_parts_to_canonical_urls(tmp_path):
    calls = []

    def fake_metadata_fetcher(ref, run_dir):
        calls.append((ref, run_dir))
        return {
            "title": "合集标题",
            "parts": [
                {"part_index": 1, "title": "第一课", "duration": 120, "cid": "111"},
                {"part_index": 2, "title": "第二课", "duration": 150, "cid": "222"},
                {"part_index": 3, "title": "第三课", "duration": None, "cid": "333"},
            ],
        }

    preview = preview_bilibili_collection(
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.788",
        work_dir=tmp_path,
        metadata_fetcher=fake_metadata_fetcher,
    )

    assert calls[0][0].bvid == "BV1abcDEF12G"
    assert calls[0][0].part_index == 2
    assert calls[0][0].sanitized_url == "https://www.bilibili.com/video/BV1abcDEF12G?p=2"
    assert calls[0][1].is_dir()
    assert preview == {
        "ok": True,
        "platform": "bilibili",
        "bvid": "BV1abcDEF12G",
        "title": "合集标题",
        "current_part_index": 2,
        "current_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
        "total_parts": 3,
        "parts": [
            {
                "part_index": 1,
                "title": "第一课",
                "duration": 120,
                "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                "is_current": False,
            },
            {
                "part_index": 2,
                "title": "第二课",
                "duration": 150,
                "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
                "is_current": True,
            },
            {
                "part_index": 3,
                "title": "第三课",
                "duration": None,
                "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=3",
                "is_current": False,
            },
        ],
    }


def test_preview_bilibili_collection_falls_back_to_current_part_when_parts_missing(tmp_path):
    def fake_metadata_fetcher(ref, run_dir):
        return {"title": "单视频标题", "duration": 240}

    preview = preview_bilibili_collection(
        "https://www.bilibili.com/video/BV1abcDEF12G",
        work_dir=tmp_path,
        metadata_fetcher=fake_metadata_fetcher,
    )

    assert preview["current_part_index"] == 1
    assert preview["total_parts"] == 1
    assert preview["parts"] == [
        {
            "part_index": 1,
            "title": "单视频标题",
            "duration": 240,
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "is_current": True,
        }
    ]
