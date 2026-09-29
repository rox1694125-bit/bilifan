import json
import subprocess
from pathlib import Path

import pytest

import bilifan.article as article_module
from bilifan.article import ArticleError, generate_transcript_article
from bilifan.article_cache import cache_directory, active_generation
from bilifan.execution import OperationCanceled
from bilifan import metrics
from test_article import REF, _metadata, _article_payload


def _inputs():
    segments = [
        {"start": 0, "end": 30, "text": "第一部分先保留原始文件，确认归档内容完整，再进行后续整理。"},
        {"start": 30, "end": 60, "text": "第二部分需要核对处理结果，并保留可以追溯到原视频的时间位置。"},
    ]
    transcript = {"source": "whisper", "language": "zh", "model": "turbo", "segments": segments, "transcript_check": {"status": "ok"}}
    chunks = {"chunks": [{"chunk_index": i+1, "start": s["start"], "end": s["end"], "segment_start_index": i, "segment_end_index": i, "segments": [{"source_index": i, **s}], "text": s["text"]} for i,s in enumerate(segments)]}
    return transcript, chunks


def _runner(calls, fail_index=None):
    def run(cmd, **kwargs):
        prompt = json.loads(kwargs["input"].split("\n")[-1])
        chunk = prompt["chunk"]
        index = chunk["chunk_index"]
        calls.append(index)
        if index == fail_index:
            raise subprocess.TimeoutExpired(cmd, 5)
        value = _article_payload()
        section = value["sections"][0]
        section.update(start=chunk["start"], end=chunk["end"], source_segment_start_index=chunk["segment_start_index"], source_segment_end_index=chunk["segment_end_index"], warnings=["fixture_warning"])
        section["paragraphs"] = [{"text": chunk["text"], "emphasis": []}]
        Path(cmd[cmd.index("--output-last-message")+1]).write_text(json.dumps(value))
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5}}), stderr="")
    return run


def _generate(run_dir, calls, *, cache=None, **kwargs):
    transcript, chunks = _inputs()
    run_dir.mkdir(parents=True, exist_ok=True)
    return generate_transcript_article(ref=REF, metadata=_metadata(), transcript=transcript, chunks=chunks, run_dir=run_dir, cache_dir=cache, runner=_runner(calls, kwargs.pop("fail_index", None)), **kwargs)


def test_second_block_failure_keeps_first_checkpoint_outside_retry_workspace(tmp_path):
    stable_run = tmp_path / "runs" / "stable"
    cache = cache_directory(stable_run)
    calls = []
    with pytest.raises(ArticleError):
        _generate(tmp_path / ".retry-one" / "work", calls, cache=cache, fail_index=2)
    assert calls == [1, 2]
    assert len(list(active_generation(cache).glob("*.json"))) == 1
    result = _generate(tmp_path / ".retry-two" / "work", calls, cache=cache)
    assert calls == [1, 2, 2]
    assert result["sections"][0]["warnings"] == ["fixture_warning"]
    assert cache.parent.parent.name == ".workbench-state"


def test_corrupt_checkpoint_only_regenerates_its_chunk(tmp_path):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    paths = sorted(active_generation(cache).glob("*.json"))
    damaged = json.loads(paths[0].read_text())["chunk_index"]
    paths[0].write_text("{broken")
    calls.clear()
    _generate(tmp_path / "run", calls, cache=cache)
    assert calls == [damaged]


def test_cache_payload_is_revalidated_before_reuse(tmp_path):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    path = next(active_generation(cache).glob("*.json"))
    value = json.loads(path.read_text())
    damaged = value["chunk_index"]
    value["article"]["sections"][0]["start"] = 10000
    path.write_text(json.dumps(value))
    calls.clear()
    _generate(tmp_path / "run", calls, cache=cache)
    assert calls == [damaged]


@pytest.mark.parametrize("change", ["model", "prompt", "rules", "transcript"])
def test_changed_generation_inputs_invalidate_checkpoints(tmp_path, monkeypatch, change):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    transcript, chunks = _inputs()
    kwargs = {}
    if change == "model":
        kwargs["model"] = "different-test-model"
    elif change == "prompt":
        original = article_module.build_article_prompt
        monkeypatch.setattr(article_module, "build_article_prompt", lambda **kw: "规则变更\n" + original(**kw))
    elif change == "rules":
        monkeypatch.setattr(article_module, "ARTICLE_NORMALIZATION_VERSION", "test-new-version")
    else:
        chunks["chunks"][0]["text"] += "追加一个新的来源说明。"
        chunks["chunks"][0]["segments"][0]["text"] = chunks["chunks"][0]["text"]
        transcript["segments"][0]["text"] = chunks["chunks"][0]["text"]
    calls.clear()
    generate_transcript_article(ref=REF, metadata=_metadata(), transcript=transcript, chunks=chunks, run_dir=tmp_path/"run", cache_dir=cache, runner=_runner(calls), **kwargs)
    assert calls == ([1] if change == "transcript" else [1, 2])


def test_force_regenerates_every_chunk(tmp_path):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    calls.clear()
    _generate(tmp_path / "run", calls, cache=cache, force_article=True)
    assert calls == [1, 2]


def test_cancel_after_completed_chunk_preserves_checkpoint(tmp_path, monkeypatch):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    def check():
        if (cache / "active.json").exists() and list(active_generation(cache).glob("*.json")):
            raise OperationCanceled("fixture cancel")
    monkeypatch.setattr(article_module, "check_cancelled", check)
    with pytest.raises(OperationCanceled):
        _generate(tmp_path / "run", calls, cache=cache)
    assert calls == [1]
    monkeypatch.setattr(article_module, "check_cancelled", lambda: None)
    _generate(tmp_path / "run", calls, cache=cache)
    assert calls == [1, 2]


def test_metrics_count_calls_cache_and_unknown_without_storing_prompt(tmp_path):
    stable = tmp_path / "runs" / "stable"
    cache = cache_directory(stable)
    calls = []
    with metrics.attempt_context("retry", "codex-exec", "test-model"):
        metrics.bind_run(stable)
        _generate(tmp_path / "run", calls, cache=cache)
    with metrics.attempt_context("retry", "codex-exec", "test-model"):
        metrics.bind_run(stable)
        _generate(tmp_path / "run", calls, cache=cache)
    records = [json.loads(p.read_text()) for p in (cache.parent / "attempts").glob("*.json")]
    first = next(r for r in records if r["model_calls"] == 2)
    second = next(r for r in records if r["model_calls"] == 0)
    assert first["usage"]["input_tokens"] == 20
    assert first["usage"]["output_tokens"] == 10
    assert second["cache_hits"] == 2
    assert second["completed_chunks"] == 2
    assert second["remaining_chunks"] == 0
    assert first["queue_seconds"] is None
    assert all("第一部分" not in json.dumps(r, ensure_ascii=False) for r in records)


def test_invalid_generation_is_never_cached(tmp_path, monkeypatch):
    cache = cache_directory(tmp_path / "runs" / "stable")
    monkeypatch.setattr(article_module, "run_codex_article_generation", lambda **kw: {"sections": []})
    with pytest.raises(ArticleError):
        _generate(tmp_path / "run", [], cache=cache)
    assert not list(active_generation(cache).glob("*.json"))


def test_checkpoint_write_failure_keeps_existing_delivery(tmp_path, monkeypatch):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    run = tmp_path / "run"
    _generate(run, calls, cache=cache)
    old = (run / "transcript_article.json").read_bytes()
    def fail_save(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr(article_module, "save_checkpoint", fail_save)
    with pytest.raises(ArticleError, match="checkpoint"):
        _generate(run, calls, cache=cache, force_article=True)
    assert (run / "transcript_article.json").read_bytes() == old
    assert sum(1 for _ in (cache / "generations").glob("*/*.json")) == 2


def test_raw_only_edit_rebinds_prompt_and_invalidates_changed_block(tmp_path):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    transcript, chunks = _inputs()
    transcript["segments"][0]["text"] = "修改后的原稿：先验证原始数据，再保存最新备份，并核对全部处理结果。"
    calls.clear()
    article = generate_transcript_article(ref=REF, metadata=_metadata(), transcript=transcript, chunks=chunks, run_dir=tmp_path/"run", cache_dir=cache, runner=_runner(calls))
    assert calls == [1]
    assert "修改后的原稿" in article["sections"][0]["paragraphs"][0]["text"]


def test_force_failure_resume_uses_only_fresh_generation(tmp_path):
    cache = cache_directory(tmp_path / "runs" / "stable")
    calls = []
    _generate(tmp_path / "run", calls, cache=cache)
    old_generation = active_generation(cache)
    with pytest.raises(ArticleError):
        _generate(tmp_path / "run", calls, cache=cache, force_article=True, fail_index=2)
    new_generation = active_generation(cache)
    assert new_generation != old_generation
    assert len(list(old_generation.glob("*.json"))) == 2
    assert len(list(new_generation.glob("*.json"))) == 1
    calls.clear()
    _generate(tmp_path / "run", calls, cache=cache)
    assert calls == [2]
    assert active_generation(cache) == new_generation


def test_raw_segment_layout_change_requires_rechunking(tmp_path):
    transcript, chunks = _inputs()
    transcript["segments"].append({"start": 60, "end": 90, "text": "这是新增的实质段落，需要重新分块，不能静默遗漏。"})
    calls = []
    with pytest.raises(ArticleError, match="rebuild chunks"):
        generate_transcript_article(ref=REF, metadata=_metadata(), transcript=transcript, chunks=chunks, run_dir=tmp_path, runner=_runner(calls))
    assert calls == []
