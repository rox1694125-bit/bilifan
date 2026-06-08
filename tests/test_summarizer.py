import json
import subprocess

import pytest

import bilifan.summarizer as summarizer
from bilifan.bilibili import BilibiliPartRef
from bilifan.summarizer import (
    CHUNK_SUMMARY_SCHEMA,
    SummarizationError,
    build_chunk_prompt,
    merge_partial_summaries,
    run_codex_chunk_summary,
    summarize_chunks,
)


REF = BilibiliPartRef(
    bvid="BV1abcDEF12G",
    part_index=2,
    sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
)


def _metadata():
    return {
        "title": "测试视频",
        "part_title": "当前 P",
        "owner_name": "UP",
        "description": "简介",
        "tags": ["AI"],
        "duration": 120,
    }


def _chunks():
    return {
        "chunks": [
            {
                "chunk_index": 1,
                "start": 0,
                "end": 120,
                "segments": [
                    {"source_index": 0, "start": 0, "end": 60, "text": "这是转写内容"},
                    {"source_index": 1, "start": 60, "end": 120, "text": "第二段"},
                ],
                "text": "这是转写内容",
            }
        ]
    }


def _valid_partial():
    return {
        "chunk_index": 1,
        "chapters": [
            {
                "title": "开场",
                "start": 0,
                "end": 120,
                "summary": "讲清楚主要问题。",
                "key_points": ["第一点", "第二点"],
                "quotes": ["这是转写内容"],
                "visual_anchors": ["白板"],
            }
        ],
    }


def test_build_chunk_prompt_contains_schema_and_learning_note_style():
    prompt = build_chunk_prompt(metadata=_metadata(), chunk=_chunks()["chunks"][0], style="学习笔记")

    assert "学习笔记" in prompt
    assert "这是转写内容" in prompt
    assert "transcript_segments" in prompt
    assert '"start": 60.0' in prompt
    assert json.dumps(CHUNK_SUMMARY_SCHEMA["required"], ensure_ascii=False) in prompt


def test_run_codex_chunk_summary_invokes_codex_exec_and_reads_output(tmp_path):
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_valid_partial(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"event":"done"}', stderr="")

    partial = run_codex_chunk_summary(
        metadata=_metadata(),
        chunk=_chunks()["chunks"][0],
        run_dir=tmp_path,
        model="gpt-5.5",
        style="学习笔记",
        runner=fake_runner,
    )

    cmd = calls[0]["cmd"]
    assert cmd[1:3] == ["exec", "--ephemeral"]
    assert cmd[0].endswith("codex")
    assert "--json" in cmd
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5.5"
    assert "--output-schema" in cmd
    assert calls[0]["input"].startswith("你是 Bilifan")
    assert calls[0]["cwd"] == tmp_path
    assert partial["chapters"][0]["title"] == "开场"


def test_run_codex_chunk_summary_uses_packaged_codex_when_not_on_path(
    tmp_path, monkeypatch
):
    calls = []
    fallback_codex = tmp_path / "Codex.app" / "Contents" / "Resources" / "codex"
    fallback_codex.parent.mkdir(parents=True)
    fallback_codex.write_text("#!/bin/sh\n", encoding="utf-8")
    fallback_codex.chmod(0o755)

    monkeypatch.delenv("BILIFAN_CODEX_BIN", raising=False)
    monkeypatch.setattr(summarizer.shutil, "which", lambda name: None)
    monkeypatch.setattr(summarizer, "CODEX_EXEC_CANDIDATES", (fallback_codex,))

    def fake_runner(cmd, **kwargs):
        calls.append(cmd)
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_valid_partial(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    run_codex_chunk_summary(
        metadata=_metadata(),
        chunk=_chunks()["chunks"][0],
        run_dir=tmp_path,
        model="gpt-5.5",
        style="学习笔记",
        runner=fake_runner,
    )

    assert calls[0][0] == str(fallback_codex)


def test_run_codex_chunk_summary_reports_actionable_message_when_codex_missing(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("BILIFAN_CODEX_BIN", raising=False)
    monkeypatch.setattr(summarizer.shutil, "which", lambda name: None)
    monkeypatch.setattr(summarizer, "CODEX_EXEC_CANDIDATES", ())

    def fake_runner(cmd, **kwargs):
        raise AssertionError("runner should not be called when codex cannot be resolved")

    with pytest.raises(SummarizationError) as exc_info:
        run_codex_chunk_summary(
            metadata=_metadata(),
            chunk=_chunks()["chunks"][0],
            run_dir=tmp_path,
            model="gpt-5.5",
            style="学习笔记",
            runner=fake_runner,
        )

    message = str(exc_info.value)
    assert "Codex CLI executable not found" in message
    assert "BILIFAN_CODEX_BIN" in message


def test_run_codex_chunk_summary_raises_when_codex_fails(tmp_path):
    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr="failed with OPENAI_API_KEY=secret /Users/jack/raw",
        )

    with pytest.raises(SummarizationError) as exc_info:
        run_codex_chunk_summary(
            metadata=_metadata(),
            chunk=_chunks()["chunks"][0],
            run_dir=tmp_path,
            model="gpt-5.5",
            style="学习笔记",
            runner=fake_runner,
        )

    message = str(exc_info.value)
    assert "codex exec failed" in message
    assert "secret" not in message
    assert "/Users/jack" not in message


def test_summarize_chunks_writes_partial_and_merges_chapters(tmp_path):
    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_valid_partial(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    chapters = summarize_chunks(
        ref=REF,
        metadata=_metadata(),
        chunks=_chunks(),
        run_dir=tmp_path,
        provider="codex-exec",
        model="gpt-5.5",
        runner=fake_runner,
    )

    assert (tmp_path / "partial_summaries" / "chunk_001.json").is_file()
    assert chapters["style"] == "学习笔记"
    assert chapters["chapters"][0]["chapter_index"] == 1
    assert chapters["chapters"][0]["timestamp_url"].endswith("&t=0")


def test_summarize_chunks_normalizes_small_chunk_boundary_drift(tmp_path):
    chunks = _chunks()
    chunks["chunks"][0]["start"] = 0.82
    chunks["chunks"][0]["end"] = 119.42
    chunks["chunks"][0]["segments"] = [
        {"source_index": 0, "start": 0.82, "end": 60, "text": "这是转写内容"},
        {"source_index": 1, "start": 60, "end": 119.42, "text": "第二段"},
    ]
    partial = _valid_partial()
    partial["chapters"][0]["start"] = 0
    partial["chapters"][0]["end"] = 120

    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    chapters = summarize_chunks(
        ref=REF,
        metadata=_metadata(),
        chunks=chunks,
        run_dir=tmp_path,
        runner=fake_runner,
    )

    saved_partial = json.loads(
        (tmp_path / "partial_summaries" / "chunk_001.json").read_text(
            encoding="utf-8"
        )
    )
    chapter = chapters["chapters"][0]
    assert chapter["start"] == 0.82
    assert chapter["end"] == 119.42
    assert saved_partial["chapters"][0]["start"] == 0.82
    assert saved_partial["chapters"][0]["end"] == 119.42


def test_summarize_chunks_writes_raw_partial_before_rejecting_invalid_summary(tmp_path):
    invalid_partial = _valid_partial()
    invalid_partial["chapters"][0]["start"] = 180
    invalid_partial["chapters"][0]["end"] = 200

    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(invalid_partial, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(SummarizationError, match="outside the input chunk"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=_chunks(),
            run_dir=tmp_path,
            runner=fake_runner,
        )

    saved_partial = json.loads(
        (tmp_path / "partial_summaries" / "chunk_001.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved_partial["chapters"][0]["start"] == 180


def test_summarize_chunks_rejects_invalid_provider(tmp_path):
    with pytest.raises(SummarizationError, match="Unsupported LLM provider"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=_chunks(),
            run_dir=tmp_path,
            provider="mock",
        )


def test_summarize_chunks_rejects_schema_invalid_codex_json(tmp_path):
    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text('{"chunk_index": 1, "chapters": []}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(SummarizationError, match="Invalid chunk summary JSON"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=_chunks(),
            run_dir=tmp_path,
            runner=fake_runner,
        )


def test_summarize_chunks_rejects_mismatched_chunk_index(tmp_path):
    invalid_partial = _valid_partial()
    invalid_partial["chunk_index"] = 99

    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(invalid_partial, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(SummarizationError, match="mismatched chunk_index"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=_chunks(),
            run_dir=tmp_path,
            runner=fake_runner,
        )


def test_summarize_chunks_rejects_chapter_timestamp_outside_chunk(tmp_path):
    invalid_partial = _valid_partial()
    invalid_partial["chapters"][0]["start"] = 180
    invalid_partial["chapters"][0]["end"] = 200

    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(invalid_partial, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(SummarizationError, match="outside the input chunk"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=_chunks(),
            run_dir=tmp_path,
            runner=fake_runner,
        )


def test_summarize_chunks_rejects_unanchored_chapter_start(tmp_path):
    chunks = _chunks()
    chunks["chunks"][0]["segments"] = [
        {"source_index": 0, "start": 0, "end": 10, "text": "第一段"},
        {"source_index": 1, "start": 60, "end": 120, "text": "第二段"},
    ]
    invalid_partial = _valid_partial()
    invalid_partial["chapters"][0]["start"] = 30
    invalid_partial["chapters"][0]["end"] = 90

    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        if not output_path.is_absolute():
            output_path = tmp_path / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(invalid_partial, ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with pytest.raises(SummarizationError, match="not anchored"):
        summarize_chunks(
            ref=REF,
            metadata=_metadata(),
            chunks=chunks,
            run_dir=tmp_path,
            runner=fake_runner,
        )


def test_merge_partial_summaries_redacts_sensitive_text():
    partial = _valid_partial()
    partial["chapters"][0]["summary"] = "Cookie: SESSDATA=secret /Users/jack/raw.txt"

    chapters = merge_partial_summaries(ref=REF, partials=[partial], style="学习笔记")

    serialized = json.dumps(chapters, ensure_ascii=False)
    assert "SESSDATA=secret" not in serialized
    assert "/Users/jack" not in serialized
