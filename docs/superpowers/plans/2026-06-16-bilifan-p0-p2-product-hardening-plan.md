# Bilifan P0-P2 Product Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Bilifan's existing local MVP more reliable and product-ready by prioritizing subtitles before audio downloads, unifying task presentation, improving recovery guidance, strengthening Nabaichuan exports, and clearly marking visuals as experimental.

**Architecture:** Keep the current local-first pipeline and public interfaces. Use small behavior changes around existing modules instead of a broad rewrite: pipeline orchestration in `src/bilifan/pipeline.py`, transcript behavior in `src/bilifan/transcript.py`, task state in `src/bilifan/web/jobs.py` and `src/bilifan/web/queue.py`, Web UI rendering in `src/bilifan/web/ui.py`, and export contracts in `src/bilifan/bundle.py` and `src/bilifan/exports.py`.

**Tech Stack:** Python 3.12, Typer, FastAPI, uvicorn, yt-dlp, openai-whisper, ffmpeg/ffprobe, Jinja2, pytest.

---

## File Map

- `src/bilifan/pipeline.py`: orchestrates metadata, optional audio download, transcript, chunking, summarization, rendering, bundle, diagnostics.
- `src/bilifan/transcript.py`: subtitle-first and Whisper fallback transcript generation.
- `src/bilifan/web/jobs.py`: current single-job state and user-facing failure/retry metadata.
- `src/bilifan/web/queue.py`: persistent sequential queue state.
- `src/bilifan/web/app.py`: Web API endpoints and request payload mapping.
- `src/bilifan/web/ui.py`: local Web UI HTML/CSS/JS.
- `src/bilifan/bundle.py`: stable `content_bundle.json` contract.
- `src/bilifan/exports.py`: `nabaichuan.jsonl` and export records.
- `src/bilifan/visuals.py`: optional diagrams and frame extraction.
- `README.md` and `docs/nabaichuan-integration.md`: user-facing behavior and integration boundaries.

## Task 0: Baseline Commit

**Files:**
- Existing modified files from the prior approved work.

- [x] **Step 1: Verify baseline tests**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [x] **Step 2: Commit baseline**

Run:

```bash
git add src/bilifan/media.py src/bilifan/summarizer.py src/bilifan/web/app.py src/bilifan/web/queue.py src/bilifan/web/ui.py tests/test_media.py tests/test_queue.py tests/test_summarizer.py tests/test_web_jobs.py tests/test_web_ui.py
git commit -m "feat: stabilize web queue and media handling"
git push -u origin codex/bilifan-foundation
```

Expected: commit `285c019` pushed to `origin/codex/bilifan-foundation`.

## Task 1: Subtitle-First Pipeline and Lazy Audio

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify if needed: `src/bilifan/transcript.py`
- Test: `tests/test_pipeline.py`
- Test if needed: `tests/test_transcript.py`

- [x] **Step 1: Add failing pipeline test for subtitle-only path**

Add a test in `tests/test_pipeline.py` that sets metadata with a usable subtitle, monkeypatches `pipeline.build_transcript` to return `source="bilibili-subtitle"` without needing audio, and monkeypatches `pipeline.download_current_part_audio` to raise if called. The expected result is successful `report.html`, `transcript.txt`, `content_bundle.json`, and no `media/audio.mp3` artifact.

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline.py::test_run_summarize_pipeline_uses_subtitles_without_downloading_audio -q
```

Expected before implementation: FAIL because the pipeline currently downloads audio before transcript.

- [x] **Step 2: Add failing pipeline test for forced Whisper**

Add a test in `tests/test_pipeline.py` where subtitles exist but `PipelineRequest(force_whisper=True)` is used. The expected behavior is that `download_current_part_audio` is called before `build_transcript`, and `media/audio.mp3` is present after success.

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline.py::test_run_summarize_pipeline_force_whisper_downloads_audio_before_transcript -q
```

Expected before implementation: may pass today; keep it as a regression guard after reordering.

- [x] **Step 3: Implement minimal lazy-audio orchestration**

In `src/bilifan/pipeline.py`, move transcript generation before audio download when `request.force_whisper` is false and `request.transcriber` is not `"whisper"`. Build a media placeholder from metadata:

```python
def _metadata_media(metadata: dict[str, Any]) -> dict[str, Any]:
    duration = metadata.get("duration")
    return {
        "audio_path": "",
        "audio_source": "not-downloaded",
        "duration_seconds": duration if isinstance(duration, int | float) and not isinstance(duration, bool) else None,
        "duration_check": {
            "status": "not_required",
            "metadata_seconds": duration,
            "audio_seconds": None,
            "difference_ratio": None,
            "tolerance_ratio": None,
            "attempts": 0,
        },
    }
```

If `build_transcript` returns a non-Whisper source, skip audio download. If it raises because Whisper needs missing audio, download audio and call `build_transcript` again. If `force_whisper` or `transcriber == "whisper"`, download audio first.

- [x] **Step 4: Make artifact assembly tolerate missing audio**

In `src/bilifan/pipeline.py`, only include `media["audio_path"]` in artifact lists when it is a non-empty string. Only call `publish_audio_artifact` when a real audio path exists.

- [x] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_pipeline.py tests/test_transcript.py -q
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit and push**

Run:

```bash
git add src/bilifan/pipeline.py src/bilifan/transcript.py tests/test_pipeline.py tests/test_transcript.py
git commit -m "feat: prefer subtitles before audio download"
git push
```

## Task 2: Unified Task Center and Queue UX

**Files:**
- Modify: `src/bilifan/web/app.py`
- Modify: `src/bilifan/web/jobs.py`
- Modify: `src/bilifan/web/queue.py`
- Modify: `src/bilifan/web/ui.py`
- Test: `tests/test_web_jobs.py`
- Test: `tests/test_queue.py`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Add failing Web API/UI tests**

Add tests proving that a single URL submission is represented in the same visible task center as queue jobs, that finished queue items keep the latest 3 completed items, and that replaced failed attempts are hidden once the same URL succeeds later.

Run:

```bash
.venv/bin/python -m pytest tests/test_web_jobs.py tests/test_queue.py tests/test_web_ui.py -q
```

Expected before implementation: at least one new test fails.

- [ ] **Step 2: Implement minimal unified representation**

Keep existing `/api/jobs/current` for compatibility. Add a combined task view from the Web UI by rendering current job and queue jobs under one "任务中心" section, using the same Chinese stage labels and artifact action groups. Do not remove persistent queue storage.

- [ ] **Step 3: Improve queue cleanup semantics**

Keep `RECENT_COMPLETED_LIMIT = 3`. Hide failed/canceled jobs when a later successful job with the same normalized URL exists. Keep `clear_completed` for manual cleanup.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_jobs.py tests/test_queue.py tests/test_web_ui.py -q
git add src/bilifan/web/app.py src/bilifan/web/jobs.py src/bilifan/web/queue.py src/bilifan/web/ui.py tests/test_web_jobs.py tests/test_queue.py tests/test_web_ui.py
git commit -m "feat: unify web task center"
git push
```

## Task 3: Recovery Guidance and Transcript Source Visibility

**Files:**
- Modify: `src/bilifan/web/jobs.py`
- Modify: `src/bilifan/web/files.py`
- Modify: `src/bilifan/web/ui.py`
- Test: `tests/test_web_jobs.py`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Add tests for recovery classification**

Add tests for user-facing failure cases:

```python
assert explain_failure(stage="audio", message="Bilibili audio stream download failed.", warnings=[])["title"] == "音频下载超时或中断"
assert explain_failure(stage="summarization", message="chunk summary chapter start was not anchored to a transcript segment.", warnings=[])["title"] == "总结时间戳校验失败"
```

Also add a UI snapshot/assertion that successful run cards show transcript source text such as `逐字稿：B站字幕` or `逐字稿：Whisper turbo`.

- [ ] **Step 2: Expose transcript source metadata in history/task payloads**

When listing runs in `src/bilifan/web/files.py`, read `transcript.json` and expose a small `transcript_source_label`.

- [ ] **Step 3: Render transcript source in UI cards**

In `src/bilifan/web/ui.py`, show `逐字稿：...` in history and task cards. Keep raw JSON links under "更多".

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_jobs.py tests/test_web_ui.py -q
git add src/bilifan/web/jobs.py src/bilifan/web/files.py src/bilifan/web/ui.py tests/test_web_jobs.py tests/test_web_ui.py
git commit -m "feat: clarify recovery and transcript source"
git push
```

## Task 4: Nabaichuan Contract and Export Status

**Files:**
- Modify: `src/bilifan/bundle.py`
- Modify: `src/bilifan/exports.py`
- Modify: `src/bilifan/web/app.py`
- Modify: `src/bilifan/web/ui.py`
- Modify: `docs/nabaichuan-integration.md`
- Test: `tests/test_bundle.py`
- Test: `tests/test_exports.py`
- Test: `tests/test_web_jobs.py`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Add failing contract tests**

Add tests that `content_bundle.json` contains stable contract metadata:

```python
assert bundle["contract"]["name"] == "bilifan.content_bundle"
assert bundle["contract"]["schema_version"] == 1
assert bundle["contract"]["compatibility"] == "additive"
```

Add tests that Nabaichuan records include `schema_version`, `bundle_id`, and deterministic `content_hash`.

- [ ] **Step 2: Add batch export summary artifact**

When Web UI batch exports Nabaichuan JSONL, also write a JSON summary next to it with exported/skipped counts and run keys. Return both links from the API.

- [ ] **Step 3: Update docs**

Update `docs/nabaichuan-integration.md` to say Bilifan writes local files only, treats `content_bundle.json` as the stable contract, and provides a batch export summary JSON.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_bundle.py tests/test_exports.py tests/test_web_jobs.py tests/test_web_ui.py -q
git add src/bilifan/bundle.py src/bilifan/exports.py src/bilifan/web/app.py src/bilifan/web/ui.py docs/nabaichuan-integration.md tests/test_bundle.py tests/test_exports.py tests/test_web_jobs.py tests/test_web_ui.py
git commit -m "feat: strengthen nabaichuan export contract"
git push
```

## Task 5: Visuals as Experimental Capability

**Files:**
- Modify: `src/bilifan/web/ui.py`
- Modify: `README.md`
- Modify if needed: `src/bilifan/visuals.py`
- Test: `tests/test_web_ui.py`
- Test if needed: `tests/test_visuals.py`

- [ ] **Step 1: Add UI tests for experimental wording**

Add a test that the Web UI labels `with_diagrams` and `with_frames` as experimental and does not present them as default polished output.

- [ ] **Step 2: Update UI copy**

Move diagram/frame controls into advanced settings with labels:

```text
实验：基础图解
实验：尝试截图
```

Keep default unchecked.

- [ ] **Step 3: Update README boundary**

Update README to remove the stale statement that the first-stage MVP does not run a batch queue. State that diagrams and frames are optional experimental features, not the original high-quality dynamic SVG/screenshot pipeline.

- [ ] **Step 4: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_web_ui.py tests/test_visuals.py -q
git add src/bilifan/web/ui.py src/bilifan/visuals.py README.md tests/test_web_ui.py tests/test_visuals.py
git commit -m "docs: mark visual evidence experimental"
git push
```

## Task 6: Final Verification and Review

**Files:**
- No planned production changes.

- [ ] **Step 1: Run full suite**

Run:

```bash
.venv/bin/python -m pytest -q
git diff --check
git status --short
```

Expected: full tests pass, no whitespace errors, only intended files changed or clean after commits.

- [ ] **Step 2: Final code review**

Dispatch final reviewer with the full commit range from `285c019` to HEAD. Fix Critical/Important findings before final response.

- [ ] **Step 3: Final push**

Run:

```bash
git push
```

Expected: `origin/codex/bilifan-foundation` contains all task commits.
