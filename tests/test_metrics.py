import json

import pytest

from bilifan import metrics
from bilifan.article_cache import sidecar_directory
from bilifan.execution import OperationCanceled


def _records(run):
    return [json.loads(p.read_text()) for p in (sidecar_directory(run) / "attempts").glob("*.json")]


def test_metrics_measure_stages_and_emit_structured_events_without_payload_text(tmp_path, monkeypatch):
    clock = [10.0]
    events = []
    monkeypatch.setattr(metrics.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(metrics, "emit_event", events.append)
    run = tmp_path / "runs" / "stable"
    with metrics.attempt_context("full", "codex-exec", "test-model"):
        metrics.bind_run(run)
        metrics.stage_event("article", "running")
        clock[0] = 14.0
        metrics.model_call(True, 80, {"input_tokens": 12, "output_tokens": 5, "cached_input_tokens": 4, "prompt": "do not retain secret"})
        metrics.stage_event("article", "done")
        clock[0] = 16.0
    record, = _records(run)
    assert record["status"] == "succeeded"
    assert record["stages"]["article"]["seconds"] == 4
    assert record["processing_seconds"] == 6
    assert record["queue_seconds"] is None
    assert record["usage"] == {"input_tokens": 12, "output_tokens": 5, "cached_input_tokens": 4}
    assert record["model_calls"] == 1
    assert record["model_failures"] == 0
    assert record["program_fingerprint"]
    assert record["quality_rule_version"]
    assert events[-1]["type"] == "metrics"
    assert events[-1]["metrics"] == record
    assert "do not retain secret" not in json.dumps(record)


def test_unknown_usage_does_not_turn_into_zero_or_partial_total(tmp_path):
    with metrics.attempt_context("retry", "codex-exec", "test-model"):
        metrics.bind_run(tmp_path / "stable")
        metrics.model_call(True, 5, {"input_tokens": 8, "output_tokens": 2})
        metrics.model_call(False, 7)
    record, = _records(tmp_path / "stable")
    assert record["usage"] == {"input_tokens": None, "output_tokens": None, "cached_input_tokens": None}
    assert record["known_usage"]["input_tokens"] == 8
    assert record["model_calls"] == 2
    assert record["model_failures"] == 1
    assert record["input_chars"] == 12


@pytest.mark.parametrize("error, status", [(RuntimeError("secret error omitted"), "failed"), (OperationCanceled("stop"), "canceled")])
def test_exception_finishes_attempt_and_preserves_cache_counts(tmp_path, error, status):
    with pytest.raises(type(error)):
        with metrics.attempt_context("retry", "codex-exec", "test-model"):
            metrics.bind_run(tmp_path / "stable")
            metrics.stage_event("article", "running")
            metrics.cache_event(True, 1, 3)
            raise error
    record, = _records(tmp_path / "stable")
    assert record["status"] == status
    assert record["stages"]["article"]["status"] == status
    assert record["completed_chunks"] == 1
    assert record["remaining_chunks"] == 2
    assert record["cache_hits"] == 1
    assert "secret error omitted" not in json.dumps(record)
    assert metrics.snapshot() is None


def test_nested_attempts_restore_outer_context(tmp_path):
    with metrics.attempt_context("outer", "codex-exec", "test-model"):
        metrics.bind_run(tmp_path / "outer")
        metrics.model_call(True, 10)
        with metrics.attempt_context("inner", "codex-exec", "test-model"):
            metrics.bind_run(tmp_path / "inner")
            metrics.model_call(False, 5)
        assert metrics.snapshot()["model_calls"] == 1
        assert metrics.snapshot()["model_failures"] == 0
    assert _records(tmp_path / "inner")[0]["model_failures"] == 1


def test_bind_cannot_move_attempt_into_retry_workspace(tmp_path):
    with metrics.attempt_context("retry", "codex-exec", "test-model"):
        metrics.bind_run(tmp_path / "original")
        with pytest.raises(ValueError, match="stable run"):
            metrics.bind_run(tmp_path / ".retry" / "work")


def test_usage_parser_ignores_nonusage_events_and_unapproved_fields():
    events = '\n'.join([
        'noise',
        json.dumps({"type": "item.completed", "item": {"text": "SECRET", "usage": {"input_tokens": 999}}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 5, "cached_input_tokens": 2, "cost_usd": 100, "prompt": "SECRET"}}),
    ])
    assert metrics.usage_from_codex_events(events) == {"input_tokens": 12, "output_tokens": 5, "cached_input_tokens": 2}
    assert metrics.usage_from_codex_events('not JSON') is None
    assert metrics.sanitize_usage({"input_tokens": True, "output_tokens": -1, "cached_input_tokens": 2.3}) == {}


def test_multiple_usage_events_with_missing_counters_remain_unknown():
    events = '\n'.join([
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 5}}),
        json.dumps({"type": "turn.completed", "usage": {"output_tokens": 2}}),
    ])
    assert metrics.usage_from_codex_events(events) == {"input_tokens": None, "output_tokens": 7, "cached_input_tokens": None}


def test_hard_process_exit_leaves_started_call_for_confirmed_termination_finalizer(tmp_path):
    import subprocess
    import sys
    run = tmp_path / "stable"
    code = '''
import os,sys
from pathlib import Path
from bilifan import metrics
with metrics.attempt_context("retry", "codex-exec", "fixture"):
    metrics.bind_run(Path(sys.argv[1]))
    metrics.stage_event("article", "running")
    metrics.start_model_call(123)
    os._exit(7)
'''
    result = subprocess.run([sys.executable, "-c", code, str(run)])
    assert result.returncode == 7
    pending, = _records(run)
    assert pending["status"] == "running"
    assert pending["model_calls"] == 1
    assert len(pending["inflight_calls"]) == 1
    fixed = metrics.finalize_abandoned(run, "canceled", pending["attempt_id"])
    assert fixed["status"] == "canceled"
    assert fixed["model_calls"] == 1
    assert fixed["model_failures"] == 1
    assert fixed["interrupted_calls"] == 1
    assert fixed["inflight_calls"] == {}
    assert fixed["usage"]["input_tokens"] is None
    assert fixed["stages"]["article"]["status"] == "canceled"
    assert metrics.finalize_abandoned(run, "interrupted", pending["attempt_id"]) is None


def test_abandoned_finalizer_never_guesses_between_attempts(tmp_path):
    import copy
    from bilifan.article_cache import atomic_json
    run = tmp_path / "stable"
    with metrics.attempt_context("retry", "codex-exec", "fixture"):
        metrics.bind_run(run)
    original, = _records(run)
    for attempt_id in ("a" * 32, "b" * 32):
        candidate = copy.deepcopy(original)
        candidate.update(status="running", attempt_id=attempt_id)
        atomic_json(sidecar_directory(run) / "attempts" / f"{attempt_id}.json", candidate)
    assert metrics.finalize_abandoned(run, "interrupted") is None
    chosen = metrics.finalize_abandoned(run, "interrupted", "a" * 32)
    assert chosen["attempt_id"] == "a" * 32
    assert next(r for r in _records(run) if r["attempt_id"] == "b" * 32)["status"] == "running"
    assert next(r for r in _records(run) if r["attempt_id"] == original["attempt_id"])["status"] == "succeeded"
