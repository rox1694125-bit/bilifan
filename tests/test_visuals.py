import subprocess

from bilifan.bilibili import BilibiliPartRef
from bilifan.visuals import enrich_chapters_with_visuals


REF = BilibiliPartRef(
    bvid="BV1abcDEF12G",
    part_index=1,
    sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
)


def _chapters():
    return {
        "style": "学习笔记",
        "summary_validation": {
            "status": "passed",
            "checks": {
                "required_fields_present": True,
                "timestamps_anchored": True,
                "chapter_timestamps_within_chunk": True,
                "evidence_anchors_present": True,
            },
            "warnings": [],
        },
        "chapters": [
            {
                "chapter_index": 1,
                "title": "建立流程",
                "start": 0,
                "end": 60,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "summary": "先打开项目，再运行命令，最后检查结果。",
                "key_points": ["打开项目", "运行命令", "检查结果"],
                "quotes": [],
                "visual_anchors": ["终端窗口"],
                "evidence": [],
            }
        ],
    }


def test_enrich_chapters_adds_content_based_svg_diagrams(tmp_path):
    chapters = _chapters()

    warnings = enrich_chapters_with_visuals(
        ref=REF,
        chapters=chapters,
        media={},
        run_dir=tmp_path,
        with_diagrams=True,
    )

    diagram = chapters["chapters"][0]["diagram"]
    assert warnings == []
    assert diagram["type"] == "flow"
    assert diagram["caption"] == "图解：建立流程"
    assert diagram["svg"].startswith("<svg")
    assert "打开项目" in diagram["svg"]
    assert "运行命令" in diagram["svg"]
    assert "检查结果" in diagram["svg"]


def test_enrich_chapters_extracts_frames_from_existing_video(tmp_path):
    chapters = _chapters()
    video_path = tmp_path / "media" / "source.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        output_path = tmp_path / cmd[-1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"frame")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    warnings = enrich_chapters_with_visuals(
        ref=REF,
        chapters=chapters,
        media={"video_path": "media/source.mp4"},
        run_dir=tmp_path,
        with_frames=True,
        runner=fake_runner,
    )

    frame = chapters["chapters"][0]["frame"]
    assert warnings == []
    assert frame["path"] == "media/frames/chapter_001_000030.jpg"
    assert frame["timestamp"] == 30
    assert frame["timestamp_url"].endswith("&t=30")
    assert (tmp_path / frame["path"]).is_file()
    assert calls[0]["cmd"][0] == "ffmpeg"
    assert calls[0]["cmd"][calls[0]["cmd"].index("-ss") + 1] == "30.000"
    assert calls[0]["cmd"][-1] == "media/frames/chapter_001_000030.jpg"


def test_enrich_chapters_degrades_when_frames_have_no_video(tmp_path):
    chapters = _chapters()

    warnings = enrich_chapters_with_visuals(
        ref=REF,
        chapters=chapters,
        media={},
        run_dir=tmp_path,
        with_frames=True,
    )

    assert warnings == ["frames_unavailable"]
    assert "frame" not in chapters["chapters"][0]
