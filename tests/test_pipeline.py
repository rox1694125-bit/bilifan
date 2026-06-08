from pathlib import Path

from bilifan.pipeline import (
    PipelineRequest,
    PipelineResult,
    PipelineStage,
    default_progress,
)


def test_pipeline_request_defaults_for_web_and_cli(tmp_path):
    request = PipelineRequest(url="https://www.bilibili.com/video/BV1abcDEF12G", out=tmp_path)

    assert request.output_format == "html,pdf"
    assert request.transcriber == "auto"
    assert request.force_whisper is False
    assert request.llm_provider == "codex-exec"
    assert request.llm_model == "gpt-5.5"
    assert request.require_pdf is False
    assert request.allow_long_video is False
    assert request.yes_i_understand is False
    assert request.overwrite is False
    assert request.cookies_from_browser is None
    assert request.cookies_file is None


def test_pipeline_result_uses_relative_run_key(tmp_path):
    result = PipelineResult(
        run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
        run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
        diagnostics_path=tmp_path / "diagnostics.json",
        artifact_paths=["report.html"],
        warnings=[],
    )

    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert result.artifact_paths == ["report.html"]


def test_default_progress_accepts_all_known_stages():
    for stage in PipelineStage:
        default_progress(stage.value, "running", f"{stage.value} running")
