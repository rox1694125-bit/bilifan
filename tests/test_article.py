import json
import subprocess

import pytest

import bilifan.article as article_module
from bilifan.article import (
    ARTICLE_SCHEMA_VERSION,
    ArticleError,
    build_article_prompt,
    generate_transcript_article,
    normalize_transcript_article,
    run_codex_article_generation,
)
from bilifan.bilibili import BilibiliPartRef
from bilifan.summarizer import SummarizationError


REF = BilibiliPartRef(
    bvid="BV1abcDEF12G",
    part_index=1,
    sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
)


def _metadata():
    return {"title": "测试视频", "part_title": "P1", "owner_name": "UP", "duration": 90}


def _transcript(source="whisper"):
    return {
        "source": source,
        "language": "zh",
        "model": "turbo" if source == "whisper" else "",
        "segments": [
            {"start": 0, "end": 30, "text": "今天我们讲人工只能和工作流。"},
            {"start": 30, "end": 60, "text": "这个地方其实其实很重要。"},
            {"start": 60, "end": 90, "text": "最后总结一下。"},
        ],
        "transcript_check": {"status": "ok"},
    }


def _chunks():
    return {
        "chunks": [
            {
                "chunk_index": 1,
                "start": 0,
                "end": 90,
                "segment_start_index": 0,
                "segment_end_index": 2,
                "segments": [
                    {
                        "source_index": 0,
                        "start": 0,
                        "end": 30,
                        "text": "今天我们讲人工只能和工作流。",
                    },
                    {
                        "source_index": 1,
                        "start": 30,
                        "end": 60,
                        "text": "这个地方其实其实很重要。",
                    },
                    {"source_index": 2, "start": 60, "end": 90, "text": "最后总结一下。"},
                ],
                "text": "今天我们讲人工只能和工作流。\n这个地方其实其实很重要。\n最后总结一下。",
            }
        ]
    }


def _article_payload():
    return {
        "schema_version": ARTICLE_SCHEMA_VERSION,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 90,
                "source_segment_start_index": 0,
                "source_segment_end_index": 2,
                "paragraphs": [
                    {
                        "text": "今天我们讲人工智能和工作流。这个地方很重要。最后总结一下。",
                        "emphasis": [{"text": "人工智能", "kind": "strong"}],
                    }
                ],
                "key_terms": ["人工智能", "工作流"],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def test_build_article_prompt_uses_strong_cleaning_for_whisper():
    prompt = build_article_prompt(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript("whisper"),
        chunk=_chunks()["chunks"][0],
    )

    assert "强清洗" in prompt
    assert "错别字" in prompt
    assert "人工只能" in prompt
    assert "output_schema" in prompt


def test_build_article_prompt_uses_light_cleaning_for_subtitles():
    prompt = build_article_prompt(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript("bilibili-subtitle"),
        chunk=_chunks()["chunks"][0],
    )

    assert "轻清洗" in prompt
    assert "少改词" in prompt


def test_article_schema_declares_type_for_const_schema_version():
    assert article_module.ARTICLE_SCHEMA["properties"]["schema_version"] == {
        "type": "integer",
        "const": ARTICLE_SCHEMA_VERSION,
    }


def test_article_output_schema_excludes_normalized_section_fields():
    section_schema = article_module.ARTICLE_OUTPUT_SCHEMA["properties"]["sections"]["items"]

    assert "timestamp_url" not in section_schema["properties"]
    assert "cleaning_level" not in section_schema["properties"]
    assert set(section_schema["required"]) == set(section_schema["properties"])


def test_normalize_transcript_article_adds_timestamp_urls_and_validates_ranges():
    article = normalize_transcript_article(
        _article_payload(),
        ref=REF,
        transcript=_transcript(),
        chunks=_chunks(),
    )

    section = article["sections"][0]
    assert article["schema_version"] == ARTICLE_SCHEMA_VERSION
    assert section["timestamp_url"].endswith("&t=0")
    assert section["cleaning_level"] == "strong"
    assert section["paragraphs"][0]["emphasis"][0] == {"text": "人工智能", "kind": "strong"}


def test_normalize_transcript_article_rejects_unanchored_section():
    payload = _article_payload()
    payload["sections"][0]["source_segment_start_index"] = 99

    with pytest.raises(ArticleError, match="source segment"):
        normalize_transcript_article(payload, ref=REF, transcript=_transcript(), chunks=_chunks())


def test_normalize_transcript_article_rejects_timestamps_outside_source_segment_span():
    payload = _article_payload()
    payload["sections"][0]["start"] = 999
    payload["sections"][0]["end"] = 1000

    with pytest.raises(ArticleError, match="timestamp.*source segment"):
        normalize_transcript_article(payload, ref=REF, transcript=_transcript(), chunks=_chunks())


def test_normalize_transcript_article_repairs_source_segment_range_from_valid_timestamps():
    payload = _article_payload()
    payload["sections"][0]["start"] = 0
    payload["sections"][0]["end"] = 90
    payload["sections"][0]["source_segment_start_index"] = 1
    payload["sections"][0]["source_segment_end_index"] = 1

    article = normalize_transcript_article(
        payload,
        ref=REF,
        transcript=_transcript(),
        chunks=_chunks(),
    )

    section = article["sections"][0]
    assert section["start"] == 0
    assert section["end"] == 90
    assert section["source_segment_start_index"] == 0
    assert section["source_segment_end_index"] == 2


def test_normalize_transcript_article_snaps_section_boundary_out_of_segment_gap():
    chunks = _chunks()
    chunks["chunks"][0]["end"] = 13.04
    chunks["chunks"][0]["segment_end_index"] = 1
    chunks["chunks"][0]["segments"] = [
        {"source_index": 0, "start": 0.0, "end": 7.62, "text": "第一段"},
        {"source_index": 1, "start": 8.26, "end": 13.04, "text": "第二段"},
    ]
    payload = _article_payload()
    payload["sections"][0]["start"] = 8.0
    payload["sections"][0]["end"] = 13.04
    payload["sections"][0]["source_segment_start_index"] = 1
    payload["sections"][0]["source_segment_end_index"] = 1

    article = normalize_transcript_article(
        payload,
        ref=REF,
        transcript=_transcript(),
        chunks=chunks,
    )

    section = article["sections"][0]
    assert section["start"] == 8.26
    assert section["end"] == 13.04
    assert section["source_segment_start_index"] == 1
    assert section["source_segment_end_index"] == 1


def test_run_codex_article_generation_invokes_codex_exec(tmp_path):
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_article_payload(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    article = run_codex_article_generation(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chunk=_chunks()["chunks"][0],
        run_dir=tmp_path,
        model="gpt-5.5",
        runner=fake_runner,
    )

    assert calls[0]["cmd"][1:3] == ["exec", "--ephemeral"]
    assert calls[0]["cmd"][calls[0]["cmd"].index("--model") + 1] == "gpt-5.5"
    assert "强清洗" in calls[0]["input"]
    assert article["sections"][0]["title"] == "人工智能工作流"


def test_run_codex_article_generation_wraps_codex_resolution_errors(tmp_path, monkeypatch):
    def fake_resolver():
        raise SummarizationError("missing /Users/jack/secret")

    def fake_runner(cmd, **kwargs):
        raise AssertionError("runner should not be called when codex cannot be resolved")

    monkeypatch.setattr(article_module, "resolve_codex_executable", fake_resolver)

    with pytest.raises(ArticleError) as exc_info:
        run_codex_article_generation(
            ref=REF,
            metadata=_metadata(),
            transcript=_transcript(),
            chunk=_chunks()["chunks"][0],
            run_dir=tmp_path,
            model="gpt-5.5",
            runner=fake_runner,
        )

    message = str(exc_info.value)
    assert "missing" in message
    assert "/Users/jack" not in message


def test_generate_transcript_article_writes_stable_artifact(tmp_path):
    def fake_runner(cmd, **kwargs):
        assert cmd[cmd.index("--model") + 1] == "gpt-5.5"
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_article_payload(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    article = generate_transcript_article(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chunks=_chunks(),
        run_dir=tmp_path,
        provider="codex-exec",
        runner=fake_runner,
    )

    written = json.loads((tmp_path / "transcript_article.json").read_text(encoding="utf-8"))
    assert article == written
    assert written["sections"][0]["timestamp_url"].endswith("&t=0")


def test_generate_transcript_article_rejects_unsupported_provider(tmp_path):
    def fake_runner(cmd, **kwargs):
        raise AssertionError("runner should not be called for unsupported provider")

    with pytest.raises(ArticleError, match="Unsupported LLM provider"):
        generate_transcript_article(
            ref=REF,
            metadata=_metadata(),
            transcript=_transcript(),
            chunks=_chunks(),
            run_dir=tmp_path,
            provider="other",
            runner=fake_runner,
        )
