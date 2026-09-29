import json
from unittest.mock import Mock

import pytest

import bilifan.pipeline as pipeline
import bilifan.retry as retry
from bilifan.bundle import build_content_bundle
from bilifan.exports import build_nabaichuan_records
from test_duration_preflight import BILIBILI, install_pipeline_fakes
from test_retry import _run_dir, _article, _chapters, _write_json


def test_new_video_delivers_raw_and_article_without_report_calls(tmp_path, monkeypatch):
    calls = install_pipeline_fakes(monkeypatch, duration=120)
    no_report = Mock(side_effect=AssertionError("new report generation is disabled"))
    monkeypatch.setattr(pipeline, "summarize_article_sections", no_report)
    monkeypatch.setattr(pipeline, "render_report_html", no_report)
    result = pipeline.run_summarize_pipeline(pipeline.PipelineRequest(
        url=BILIBILI, out=tmp_path, output_format="html", yes_i_understand=True,
        with_frames=True, with_diagrams=True, summary_template="观点提炼",
    ))
    for name in ("transcript.json", "transcript.txt", "transcript.srt",
                 "transcript_article.json", "transcript.html", "content_bundle.json"):
        assert (result.run_dir / name).is_file(), name
    assert not (result.run_dir / "report.html").exists()
    assert not (result.run_dir / "report.pdf").exists()
    assert not (result.run_dir / "chapters.json").exists()
    no_report.assert_not_called()
    assert calls["article"] == 1
    bundle = json.loads((result.run_dir / "content_bundle.json").read_text())
    assert bundle["output_profile"] == "transcript_article_v1"
    assert bundle["summary"] == {"status": "not_generated", "style": "", "chapters": [],
                                  "summary_validation": {"status": "not_applicable", "checks": {}, "warnings": []}}


def test_article_failure_keeps_downloadable_raw_transcript(tmp_path, monkeypatch):
    install_pipeline_fakes(monkeypatch, duration=120)
    monkeypatch.setattr(pipeline, "generate_transcript_article",
                        Mock(side_effect=pipeline.ArticleError("provider unavailable")))
    with pytest.raises(pipeline.PipelineRunError) as caught:
        pipeline.run_summarize_pipeline(pipeline.PipelineRequest(url=BILIBILI, out=tmp_path))
    run_dir = caught.value.diagnostics_path.parent
    raw = json.loads((run_dir / "transcript.json").read_text())
    assert raw["segments"][0]["text"] in (run_dir / "transcript.txt").read_text()
    assert "00:00:00,000" in (run_dir / "transcript.srt").read_text()
    assert {"transcript.txt", "transcript.srt"} <= set(caught.value.artifact_paths)


@pytest.mark.parametrize("stage", ["article", "summarization", "render", "bundle"])
def test_article_retry_preserves_legacy_report_and_excludes_old_conclusions(tmp_path, monkeypatch, stage):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "transcript_article.json", _article())
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.html").write_text("historical interpretation")
    (run_dir / "report.pdf").write_bytes(b"historical pdf")
    old = {name: (run_dir / name).read_bytes() for name in ("report.html", "report.pdf", "chapters.json")}
    def article(**kwargs):
        value = _article()
        _write_json(kwargs["run_dir"] / "transcript_article.json", value)
        return value
    monkeypatch.setattr(retry, "generate_transcript_article", article)
    forbidden = Mock(side_effect=AssertionError("reports must remain read-only"))
    monkeypatch.setattr(retry, "summarize_article_sections", forbidden)
    monkeypatch.setattr(retry, "render_report_html", forbidden)
    result = retry.retry_run(run_dir, from_stage=stage, output_format="html")
    assert {name: (run_dir / name).read_bytes() for name in old} == old
    assert not {"report.html", "report.pdf", "chapters.json"} & set(result.artifact_paths)
    bundle = json.loads((run_dir / "content_bundle.json").read_text())
    assert bundle["summary"]["chapters"] == []
    assert bundle["summary"]["status"] == "not_generated"
    forbidden.assert_not_called()


def test_article_only_bundle_exports_segments_without_fake_chapters():
    article = _article()
    text = article["sections"][0]["paragraphs"][0]["text"]
    bundle = build_content_bundle(
        metadata={"input_url_sanitized": BILIBILI, "title": "Fixture"},
        transcript={"source": "whisper", "language": "zh", "segments": [{"start": 0, "end": 120, "text": text}]},
        transcript_article=article, artifact_paths=["transcript.html"],
        platform="bilibili", source_id="BV1abcDEF12G", part_id="p1",
    )
    records = build_nabaichuan_records(bundle)
    assert {item["type"] for item in records} == {"video", "transcript_segment"}
    segment = next(item for item in records if item["type"] == "transcript_segment")
    assert segment["chapter_id"] is None
    assert segment["parent_record_id"] == records[0]["record_id"]
