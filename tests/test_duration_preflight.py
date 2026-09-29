import json
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

import bilifan.pipeline as pipeline
from bilifan.pipeline import PipelineRequest, PipelineRunError
from bilifan.cli import app as cli_app
from bilifan.web.app import create_app
from bilifan.web.jobs import explain_failure


BILIBILI = "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def install_pipeline_fakes(monkeypatch, *, duration, actual_duration=None):
    """Keep actual parsing, chunking, rendering and bundling; fake external work."""
    calls = Counter()
    effective_duration = actual_duration or float(duration or 120)

    def metadata(adapter, source_ref, ref, run_dir, source_options):
        return {
            "video_id": ref.bvid, "part_index": ref.part_index,
            "input_url_sanitized": ref.sanitized_url, "title": "Duration fixture",
            "part_title": "Duration fixture", "duration": duration, "subtitles": [],
        }

    def audio(adapter, source_ref, ref, metadata, run_dir, source_options):
        calls["audio"] += 1
        path = run_dir / ".bilifan/cache/audio.mp3"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"audio fixture")
        return {"audio_path": ".bilifan/cache/audio.mp3", "duration_seconds": effective_duration,
                "duration_check": {"status": "ok"}}

    def transcript(metadata, media, run_dir, **kwargs):
        calls["transcript"] += 1
        return {
            "source": "bilibili-subtitle", "language": "zh",
            "segments": [{"start": 0, "end": effective_duration, "text": '这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。' * max(1, int(effective_duration / 120))}],
            "transcript_check": {"status": "ok", "segment_count": 1},
        }

    def article(**kwargs):
        calls["article"] += 1
        result = {"schema_version": 1, "source": "bilibili-subtitle", "cleaning_level": "light",
                  "sections": [{"section_index": 1, "title": "Fixture", "start": 0,
                                "end": effective_duration, "source_segment_start_index": 0,
                                "source_segment_end_index": 0,
                                "paragraphs": [{"text": kwargs["transcript"]["segments"][0]["text"], "emphasis": []}],
                                "key_terms": [], "warnings": []}], "warnings": []}
        (kwargs["run_dir"] / "transcript_article.json").write_text(json.dumps(result))
        return result

    def summary(**kwargs):
        calls["summary"] += 1
        return {"style": "学习笔记", "chapters": [{"chapter_index": 1, "title": "Fixture",
                "start": 0, "end": effective_duration, "summary": "Fixture summary",
                "timestamp_url": kwargs["ref"].timestamp_url(0),
                "key_points": [], "quotes": [], "visual_anchors": []}]}

    monkeypatch.setattr(pipeline, "_fetch_source_metadata", metadata)
    monkeypatch.setattr(pipeline, "_download_source_audio", audio)
    monkeypatch.setattr(pipeline, "build_transcript", transcript)
    monkeypatch.setattr(pipeline, "generate_transcript_article", article)
    monkeypatch.setattr(pipeline, "summarize_article_sections", summary)
    return calls


@pytest.mark.parametrize("url", [BILIBILI, YOUTUBE])
@pytest.mark.parametrize("options", [{}, {"transcriber": "whisper"}, {"force_whisper": True}])
def test_over_limit_stops_before_all_expensive_steps(tmp_path, monkeypatch, url, options):
    calls = install_pipeline_fakes(monkeypatch, duration=193 * 60)
    events = []
    with pytest.raises(PipelineRunError, match="180 minutes") as caught:
        pipeline.run_summarize_pipeline(
            PipelineRequest(url=url, out=tmp_path, output_format="html", yes_i_understand=True, **options),
            progress_callback=lambda *event: events.append(event),
        )
    assert not calls
    diagnostic = json.loads(caught.value.diagnostics_path.read_text())
    assert diagnostic["stage"] == "metadata"
    assert diagnostic["error_type"] == "LongVideoLimitExceeded"
    assert diagnostic["transcript_check"] is None
    assert diagnostic["duration_check"]["status"] == "metadata_only"
    assert diagnostic["warnings"] == ["long_video_limit_exceeded"]
    assert set(diagnostic["artifact_paths"]) == {"metadata.json", "diagnostics.json"}
    assert events[-1][0:2] == ("metadata", "failed")
    assert not (caught.value.diagnostics_path.parent / "transcript.json").exists()


@pytest.mark.parametrize("duration", [90 * 60, 180 * 60])
@pytest.mark.parametrize("allow", [False, True])
@pytest.mark.parametrize("confirmation", ["missing", "declined"])
def test_confirmation_gate_also_precedes_work(tmp_path, monkeypatch, duration, allow, confirmation):
    calls = install_pipeline_fakes(monkeypatch, duration=duration)
    with pytest.raises(PipelineRunError, match="confirmation") as caught:
        pipeline.run_summarize_pipeline(PipelineRequest(
            url=BILIBILI, out=tmp_path, output_format="html", allow_long_video=allow,
            confirm_long_video=None if confirmation == "missing" else lambda _: False,
        ))
    assert not calls
    assert json.loads(caught.value.diagnostics_path.read_text())["stage"] == "metadata"


@pytest.mark.parametrize("duration", [90 * 60, 180 * 60])
def test_confirmed_video_prompts_once_and_completes(tmp_path, monkeypatch, duration):
    calls = install_pipeline_fakes(monkeypatch, duration=duration)
    prompts = []
    def confirm(message):
        prompts.append(message)
        assert not calls
        return True
    result = pipeline.run_summarize_pipeline(PipelineRequest(
        url=BILIBILI, out=tmp_path, output_format="html", confirm_long_video=confirm,
    ))
    assert len(prompts) == 1
    assert (result.run_dir / "transcript.html").is_file()
    assert not (result.run_dir / "report.html").exists()
    assert calls == {"transcript": 1, "article": 1}


@pytest.mark.parametrize("url", [BILIBILI, YOUTUBE])
def test_explicit_over_limit_permission_allows_processing(tmp_path, monkeypatch, url):
    calls = install_pipeline_fakes(monkeypatch, duration=193 * 60)
    result = pipeline.run_summarize_pipeline(PipelineRequest(
        url=url, out=tmp_path, output_format="html", allow_long_video=True, force_whisper=True,
    ))
    assert (result.run_dir / "transcript.html").is_file()
    assert not (result.run_dir / "report.html").exists()
    assert calls == {"audio": 1, "transcript": 1, "article": 1}


@pytest.mark.parametrize("duration,actual", [(None, 193 * 60), (120, 193 * 60)])
def test_actual_duration_keeps_late_guard_for_unknown_or_wrong_metadata(tmp_path, monkeypatch, duration, actual):
    calls = install_pipeline_fakes(monkeypatch, duration=duration, actual_duration=actual)
    with pytest.raises(PipelineRunError, match="180 minutes") as caught:
        pipeline.run_summarize_pipeline(PipelineRequest(
            url=BILIBILI, out=tmp_path, output_format="html", force_whisper=True,
        ))
    assert calls == {"audio": 1, "transcript": 1}
    assert json.loads(caught.value.diagnostics_path.read_text())["stage"] == "chunking"


@pytest.mark.parametrize("entry", ["single", "batch", "feishu"])
@pytest.mark.parametrize("allowed", [False, True])
def test_web_entrypoints_apply_long_video_permission(tmp_path, monkeypatch, entry, allowed):
    calls = install_pipeline_fakes(monkeypatch, duration=193 * 60)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    client = TestClient(create_app(
        outputs=tmp_path / "outputs", token="fixture-token", open_browser=False,
        pipeline_runner=pipeline.run_summarize_pipeline, run_jobs_inline=True,
    ))
    headers = {"X-Bilifan-Token": "fixture-token"}
    assert client.post("/api/consent", headers=headers).status_code == 200
    if entry == "single":
        response = client.post("/api/jobs", headers=headers, json={
            "url": BILIBILI, "format": "html", "allow_long_video": allowed})
        item = client.get("/api/jobs/current", headers=headers).json()
    else:
        endpoint = "/api/jobs/batch" if entry == "batch" else "/api/intake/feishu"
        payload = {"urls": [BILIBILI], "format": "html", "allow_long_video": allowed} if entry == "batch" else {
            "external_batch_id": "duration-fixture", "urls": [BILIBILI],
            "defaults": {"format": "html", "allow_long_video": allowed}}
        response = client.post(endpoint, headers=headers, json=payload)
        item = client.get("/api/jobs/queue", headers=headers).json()["items"][0]
    assert response.status_code == 200
    if allowed:
        assert item["status"] == "succeeded"
        assert calls == {"transcript": 1, "article": 1}
        return
    assert not calls
    assert item["status"] == "failed"
    assert item["stage"] == "metadata"
    assert "高级设置" in item["friendly_error"]["next_action"]
    assert "重新提交" in item["friendly_error"]["next_action"]


def test_historical_long_video_failures_explain_correct_next_action():
    error = explain_failure(stage="chunking", message="Videos longer than 180 minutes require --allow-long-video.", warnings=[])
    assert "180" in error["cause"]
    assert "高级设置" in error["next_action"]
    assert "重新排队" in error["next_action"]


@pytest.mark.parametrize("allowed", [False, True])
def test_cli_entrypoint_checks_duration_before_work(tmp_path, monkeypatch, allowed):
    calls = install_pipeline_fakes(monkeypatch, duration=193 * 60)
    command = ["summarize", BILIBILI, "--yes-i-understand", "--format", "html", "--out", str(tmp_path / "outputs")]
    if allowed:
        command.append("--allow-long-video")
    result = CliRunner().invoke(cli_app, command, env={"BILIFAN_CONFIG_HOME": str(tmp_path / "config")})
    if allowed:
        assert result.exit_code == 0, result.output
        assert calls == {"transcript": 1, "article": 1}
    else:
        assert result.exit_code == 1
        assert "--allow-long-video" in result.output
        assert not calls


@pytest.mark.parametrize("duration", [None, 120])
def test_late_confirmation_failure_also_records_diagnostics(tmp_path, monkeypatch, duration):
    calls = install_pipeline_fakes(monkeypatch, duration=duration, actual_duration=100 * 60)
    with pytest.raises(PipelineRunError, match="confirmation") as caught:
        pipeline.run_summarize_pipeline(PipelineRequest(
            url=BILIBILI, out=tmp_path, output_format="html", force_whisper=True,
        ))
    assert calls == {"audio": 1, "transcript": 1}
    assert json.loads(caught.value.diagnostics_path.read_text())["stage"] == "chunking"
