"""Independent delivery acceptance: real pipeline/render/export, fake external work."""
import hashlib
import io
import json
import zipfile
from collections import Counter

import pytest
from fastapi.testclient import TestClient

import bilifan.pipeline as pipeline
import bilifan.retry as retry
from bilifan.article import normalize_transcript_article
from bilifan.bundle import build_content_bundle
from bilifan.exports import build_nabaichuan_records
from bilifan.quality import quality_text
from bilifan.web.app import create_app

URL = "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
RAW = "现在我们设置等待时间为30秒，然后检查原始文件是否保存完整，确认处理结果以后再执行下一步操作。"


@pytest.fixture
def workbench(tmp_path, monkeypatch):
    calls = Counter()
    settings = {"raw": RAW, "duration": 12, "edit": lambda text: text.replace("30秒", "300秒")}
    pdf_sources = []
    outputs = tmp_path / "outputs"
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    def metadata(adapter, source_ref, ref, run_dir, source_options):
        return {"video_id": ref.bvid, "part_index": ref.part_index,
                "input_url_sanitized": ref.sanitized_url, "title": "逐字稿交付验收",
                "part_title": "逐字稿交付验收", "duration": settings["duration"], "subtitles": [],
                "description": settings.get("description", "")}

    def raw(metadata, media, run_dir, **kwargs):
        calls["transcript"] += 1
        return {"source": "bilibili-subtitle", "language": settings.get("language", "zh"),
                "segments": [{"start": 0, "end": settings["duration"], "text": settings["raw"]}],
                "transcript_check": {"status": "ok", "audio_seconds": settings["duration"]}}

    def article(**kwargs):
        calls["article"] += 1
        source = kwargs["transcript"]["segments"][0]
        value = {"schema_version": 1, "source": "bilibili-subtitle", "cleaning_level": "light",
                 "sections": [{"section_index": 1, "title": "操作说明", "start": 0, "end": source["end"],
                     "source_segment_start_index": 0, "source_segment_end_index": 0,
                     "paragraphs": [{"text": settings["edit"](source["text"]), "emphasis": []}],
                     "key_terms": [], "warnings": []}], "warnings": []}
        value = normalize_transcript_article(value, ref=kwargs["ref"], transcript=kwargs["transcript"], chunks=kwargs["chunks"])
        (kwargs["run_dir"] / "transcript_article.json").write_text(json.dumps(value, ensure_ascii=False))
        return value

    def pdf(*, html_path, pdf_path, **kwargs):
        # Inspect precisely what is supplied to the PDF renderer, without
        # claiming this substitute verifies the browser's PDF layout.
        pdf_sources.append(html_path.read_text())
        pdf_path.write_bytes(b"%PDF-1.4\nfixture PDF renderer output\n")
        return pdf_path

    monkeypatch.setattr(pipeline, "_fetch_source_metadata", metadata)
    monkeypatch.setattr(pipeline, "build_transcript", raw)
    monkeypatch.setattr(pipeline, "generate_transcript_article", article)
    monkeypatch.setattr(retry, "generate_transcript_article", article)
    monkeypatch.setattr(pipeline, "export_html_pdf", pdf)
    monkeypatch.setattr(retry, "export_html_pdf", pdf)
    # There is no valid reason for a source-independent report/model call here.
    def forbidden(**kwargs):
        pytest.fail("A new interpretive report was requested")
    monkeypatch.setattr(pipeline, "summarize_article_sections", forbidden)
    monkeypatch.setattr(retry, "summarize_article_sections", forbidden)
    app = create_app(outputs=outputs, token="delivery-test-token", open_browser=False,
                     pipeline_runner=pipeline.run_summarize_pipeline, retry_runner=retry.retry_run,
                     run_jobs_inline=True)
    with TestClient(app) as client:
        client.headers.update({"X-Bilifan-Token": "delivery-test-token"})
        assert client.post("/api/consent").status_code == 200
        yield client, outputs, settings, calls, pdf_sources


def submit(client, *, part=1, format="html,pdf"):
    response = client.post("/api/jobs", json={"url": URL.replace("p=1", f"p={part}"), "format": format})
    assert response.status_code == 200, response.text
    response = client.get(f"/api/jobs/{response.json()['job_id']}")
    assert response.status_code == 200
    return response.json()


def file_url(job, name):
    return f"/api/runs/{job['run_key']}/files/{name}"


def export_url(job):
    return f"/api/runs/{job['run_key']}/exports/nabaichuan"


def test_changed_number_quality_agrees_across_all_delivery_surfaces(workbench):
    client, outputs, settings, calls, pdf_sources = workbench
    job = submit(client)
    assert job["status"] == "succeeded", job
    run = outputs / job["run_key"]
    quality = json.loads((run / "quality.json").read_text())
    assert quality["status"] == "needs_review"
    assert "article_numbers_changed" in {r["code"] for r in quality["reasons"]}
    assert job["quality"] == quality
    history = client.get("/api/history").json()
    history_items = history.get("items", [])
    assert next(item for item in history_items if item["run_key"] == job["run_key"])["quality"] == quality
    assert client.get(file_url(job, "quality.json")).json() == quality
    bundle = client.get(file_url(job, "content_bundle.json")).json()
    assert bundle["quality"] == quality
    html = client.get(file_url(job, "transcript.html")).text
    assert 'data-quality="needs_review"' in html
    assert "对照原稿" in html
    assert "回到视频" in html
    assert pdf_sources and 'data-quality="needs_review"' in pdf_sources[0]
    raw = client.get(file_url(job, "transcript.txt")).text
    assert RAW in raw and "质量状态：需复查" in raw
    for reason in quality["reasons"]:
        assert reason["message"] in raw
        assert reason["message"] in html
        assert reason["message"] in pdf_sources[0]
    archive_response = client.get(file_url(job, "transcript_source.zip"))
    assert archive_response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
        assert json.loads(archive.read("quality.json")) == quality
        srt = archive.read("transcript.srt").decode()
        assert "00:00:00,000 --> 00:00:12,000" in srt
        assert RAW in srt and "需复查" not in srt
        assert quality_text(quality) in archive.read("README.txt").decode()
    assert not (run / "report.html").exists()
    assert not (run / "chapters.json").exists()
    assert calls["article"] == 1


def test_single_export_requires_explicit_inclusion_without_approving_content(workbench):
    client, outputs, settings, calls, _ = workbench
    job = submit(client, format="html")
    response = client.post(export_url(job))
    assert response.status_code == 409
    rejected = response.json()
    assert rejected["review_required"]
    assert rejected["quality"] == job["quality"]
    assert "尚未导出" in rejected["detail"]
    assert not (outputs / job["run_key"] / "nabaichuan.jsonl").exists()
    response = client.post(export_url(job), params={"include_review_required": True})
    assert response.status_code == 200, response.text
    records = [json.loads(line) for line in client.get(response.json()["artifact"]).text.splitlines()]
    assert len(records) >= 2
    assert all(record["quality"] == job["quality"] for record in records)
    assert all(record["quality"]["review_required"] for record in records)
    assert all(record.get("human_reviewed") is not True for record in records)
    assert "人工审核通过" not in json.dumps(records, ensure_ascii=False)
    assert {record["type"] for record in records} == {"video", "transcript_segment"}
    for record in records[1:]:
        assert record["chapter_id"] is None
        assert record["text_source"] == "transcript_article"
    assert calls["article"] == 1  # Export does not call the model again.


def test_batch_skips_flagged_run_with_actionable_reason(workbench):
    client, outputs, settings, calls, _ = workbench
    flagged = submit(client, part=1, format="html")
    settings["edit"] = lambda text: text
    clean = submit(client, part=2, format="html")
    assert clean["quality"]["status"] == "clean"
    response = client.post("/api/exports/nabaichuan/batch")
    assert response.status_code == 200
    batch = response.json()
    assert batch["exported_runs"] == 1
    assert batch["skipped_runs"] == 1
    skipped = next(item for item in batch["items"] if item["run_key"] == flagged["run_key"])
    assert skipped["reason"] == "quality_review_required"
    assert "需复查" in skipped["message"]
    report = client.get(batch["report"]).json()
    assert report["items"] == batch["items"]
    records = [json.loads(line) for line in client.get(batch["artifact"]).text.splitlines()]
    assert records and all(record["quality"]["status"] == "clean" for record in records)


def test_unusable_raw_remains_downloadable_and_retry_calls_no_article_model(workbench):
    client, outputs, settings, calls, _ = workbench
    settings.update(raw="谢谢", duration=120)
    job = submit(client, format="html")
    assert job["status"] == "failed"
    assert job["quality"]["status"] == "unusable"
    assert calls["article"] == 0
    raw = client.get(file_url(job, "transcript.txt"))
    assert raw.status_code == 200
    assert "谢谢" in raw.text and "不可用" in raw.text
    assert client.get(file_url(job, "transcript_source.zip")).status_code == 200
    response = client.post(f"/api/runs/{job['run_key']}/retry", json={"from_stage": "summarization", "format": "html"})
    assert response.status_code == 200
    retried = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert retried["status"] == "failed"
    assert calls["article"] == 0
    assert client.get(file_url(job, "transcript.txt")).status_code == 200


def test_short_valid_source_is_clean_and_legacy_unknown_is_not_certified(workbench):
    client, outputs, settings, calls, _ = workbench
    settings.update(raw="你好，开始吧。", duration=2, edit=lambda text: text)
    job = submit(client, format="html")
    assert job["status"] == "succeeded", job
    assert job["quality"]["status"] == "clean"
    assert "自动检查未发现明显异常" in client.get(file_url(job, "transcript.txt")).text
    raw = {"source": "bilibili-subtitle", "language": "zh", "segments": [{"start": 0, "end": 2, "text": "你好，开始吧。"}]}
    bundle = build_content_bundle(metadata={"title": "旧记录"}, transcript=raw,
                                  artifact_paths=[], platform="bilibili", source_id="legacy", part_id="p1")
    assert bundle["quality"]["status"] == "unknown"
    records = build_nabaichuan_records(bundle)
    assert all(record["quality"]["status"] == "unknown" for record in records)
    assert "内容已核实" not in quality_text(bundle["quality"])
    assert "未检查" in quality_text(bundle["quality"])


def test_regeneration_keeps_historical_report_bytes_and_download_routes(workbench):
    client, outputs, settings, calls, _ = workbench
    job = submit(client, format="html")
    run = outputs / job["run_key"]
    historical = {"report.html": b"<html>Historical interpretation</html>",
                  "report.pdf": b"%PDF-1.4 historical report", "chapters.json": b'{"chapters":[{"summary":"Old conclusion"}]}'}
    for name, content in historical.items():
        (run / name).write_bytes(content)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in historical.items()}
    settings["edit"] = lambda text: text
    response = client.post(f"/api/runs/{job['run_key']}/retry", json={"from_stage": "summarization", "format": "html"})
    assert response.status_code == 200
    result = client.get(f"/api/jobs/{response.json()['job_id']}").json()
    assert result["status"] == "succeeded", result
    for name in historical:
        assert hashlib.sha256((run / name).read_bytes()).hexdigest() == hashes[name]
        response = client.get(file_url(job, name))
        assert response.status_code == 200
        assert response.content == historical[name]
    bundle = json.loads((run / "content_bundle.json").read_text())
    assert bundle["summary"]["status"] == "not_generated"
    assert bundle["summary"]["chapters"] == []
    assert "Old conclusion" not in json.dumps(bundle)
    item = next(item for item in client.get("/api/history").json()["items"] if item["run_key"] == job["run_key"])
    assert item["artifacts"]["html"].split("?", 1)[0] == file_url(job, "report.html")
    assert item["artifacts"]["pdf"].split("?", 1)[0] == file_url(job, "report.pdf")


def test_export_recheck_preserves_explicit_audio_language_evidence(workbench):
    client, outputs, settings, calls, _ = workbench
    settings.update(raw="Today we explain how reliable backups preserve original records and allow careful recovery after failures.",
                    language="en", description="English audio, spoken in English.", edit=lambda text: text)
    job = submit(client, format="html")
    assert job["status"] == "succeeded"
    assert job["quality"]["status"] == "clean"
    exported = client.post(export_url(job))
    assert exported.status_code == 200, exported.text
    records = [json.loads(line) for line in client.get(exported.json()["artifact"]).text.splitlines()]
    assert all(record["quality"] == job["quality"] for record in records)
