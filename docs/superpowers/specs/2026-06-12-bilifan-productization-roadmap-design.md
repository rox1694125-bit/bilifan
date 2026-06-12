# Bilifan Productization Roadmap Design

## Goal

Turn Bilifan from a working local MVP into a reliable local video knowledge
workbench that can serve two primary workflows:

1. Personal video learning-note generation from Bilibili and public YouTube URLs.
2. Structured video knowledge extraction for downstream systems such as
   Nabaichuan.

This design covers P0 through P4 as a single product roadmap. Implementation
should be continuous but staged. Each phase must be independently shippable,
reviewed from a senior product-manager perspective, and verified before the next
phase begins.

## Product Positioning

Bilifan is not a hosted scraping service and not a generic media downloader. It
is a local, permission-bound video knowledge extraction layer.

Primary users:

- The project owner using Codex locally.
- Advanced local users who can run Python tools and understand local processing.
- Nabaichuan or similar knowledge-base workflows that need structured bundles.

Primary value:

- Convert one video URL into transcript, notes, report, and structured bundle.
- Keep source backlinks and timestamps.
- Make failures understandable and recoverable.
- Avoid repeated expensive work by allowing downstream retry and export.

## Current Baseline

Already available:

- Bilibili current-P processing.
- Public ordinary YouTube video support.
- Local Web UI.
- CLI `summarize`.
- CLI `retry` for `summarization`, `render`, and `bundle`.
- `metadata.json`, `transcript.json`, `chunks.json`, `chapters.json`.
- `report.html`, best-effort `report.pdf`.
- `transcript.txt`, `transcript.srt`, `notes.md`.
- `content_bundle.json`.
- Fixed Web UI entrypoint with token embedded in the HTML page.

Known gaps:

- README still needs to be aligned with the fixed Web UI entrypoint.
- Web UI cannot cancel a running job.
- Web UI cannot retry a failed run from the appropriate downstream stage.
- Web UI does not explain diagnostics in user language.
- Audio artifacts are still treated as hidden cache rather than user-visible
  evidence.
- Nabaichuan integration is currently a file contract plus example converter,
  not a first-class UI workflow.
- Jobs are in-memory; service restart loses the current running job state.
- Batch queue is intentionally absent.
- SVG diagrams and real frame screenshots are not implemented.

## Roadmap Principles

- Keep the product local-first.
- Preserve legal and access-control boundaries.
- Prefer recoverability over automatic retries that hide problems.
- Treat `content_bundle.json` as the downstream contract.
- Do not add batch queue before single-job cancel/retry/recovery is stable.
- Do not add SVG diagrams before real screenshots and report quality controls
  are usable.
- Ship each phase behind simple interfaces and tests.

## Delivery Method

Use subagent-driven development, but not broad parallel implementation.

Allowed parallel work:

- Product/spec review.
- Code review.
- Test design.
- Isolated research into existing modules.

Sequential implementation:

1. P0 implementation.
2. P0 product-manager acceptance review.
3. P0 code quality review.
4. P0 verification and commit.
5. Repeat for P1 through P4.

Reason: P0 through P4 touch shared surfaces: Web UI, JobManager, pipeline state,
artifact listing, and documentation. Parallel code changes would conflict and
make acceptance harder.

Each implementation phase uses:

- Implementer agent.
- Product/spec reviewer agent.
- Code-quality reviewer agent.
- Controller integration and final verification.

The product/spec reviewer must review from the perspective of a senior product
manager, not merely check that tests pass.

## P0: Local Workbench Stabilization

### Objective

Make Bilifan usable without watching Terminal logs. A user should be able to
understand, cancel, retry, and inspect a task from Web UI.

### Features

1. README and docs update.
   - Web UI docs must show fixed entrypoint `http://127.0.0.1:<port>/`.
   - Explain that API remains token-protected.
   - Explain where outputs, transcript, bundle, and audio are located.

2. Cancel running job.
   - Add `POST /api/jobs/current/cancel`.
   - Web UI shows a cancel button only while a job is running.
   - Cancellation must mark job as failed or canceled with a clear status.
   - Long-running subprocesses should be given a bounded opportunity to stop.

3. Retry from failure.
   - If a failed run has enough artifacts, Web UI shows retry actions:
     - Retry summarization.
     - Retry render.
     - Retry bundle.
   - Retry should reuse the existing CLI retry behavior where possible.
   - Retry should not redownload audio or rerun Whisper unless explicitly
     designed later.

4. User-friendly diagnostics.
   - Add a small error explanation layer mapping known sanitized errors to
     user-facing causes and next actions.
   - Examples:
     - Codex executable missing.
     - Audio duration mismatch.
     - Audio stream timeout.
     - Summarization timestamp validation failure.
     - Unsupported URL.
   - Preserve raw `diagnostics.json` link for advanced debugging.

5. Audio artifact visibility.
   - Copy the successful MP3 to `media/audio.mp3` in successful runs.
   - Expose `media/audio.mp3` as a visible artifact link named `audio`.
   - File list should show audio when present.
   - Hidden `.bilifan/cache` remains for intermediate files and incomplete
     downloads.

6. Stage timing.
   - Show elapsed time for the current job.
   - Track `job_started_at`, `stage_started_at`, and per-stage elapsed seconds
     in the in-memory job state.
   - Warn if a single stage has had no progress update for more than 10 minutes.

### Non-Goals

- Batch queue.
- Background daemon.
- Persistent job database.
- Web UI cookies input.
- SVG or screenshot generation.

### Acceptance Criteria

- A user can cancel a running task from Web UI.
- A failed downstream task can be retried from Web UI when required artifacts
  exist.
- A successful task exposes report, transcript, notes, bundle, diagnostics,
  folder, and audio where available.
- Common failures show plain-language next steps.
- README matches actual Web UI behavior.
- Existing CLI behavior remains compatible.

## P1: Nabaichuan Export Workflow

### Objective

Make Bilifan a practical video ingestion front-end for Nabaichuan without
directly coupling Bilifan to Nabaichuan internals.

### Features

1. Bundle stability.
   - Document `content_bundle.json` schema version 1.
   - Add required and optional field descriptions.
   - Add compatibility rules for future schema changes.

2. Source fingerprint.
   - Add stable fingerprint fields for duplicate detection:
     - platform.
     - source id.
     - part id.
     - transcript checksum.
     - summary checksum.
   - Do not use local absolute paths in fingerprints.

3. Web UI export action.
   - Add "Export Nabaichuan JSONL" for a successful run.
   - Output should be written into the run directory or a dedicated export
     directory.
   - UI exposes the generated file link.

4. Batch export of historical successful runs.
   - Let user export multiple latest successful runs into one JSONL file.
   - Failed or incomplete runs should be skipped with a clear summary.

5. Converter hardening.
   - Keep `examples/content_bundle_to_nabaichuan.py`.
   - Ensure converter validates required bundle fields and gives actionable
     errors.

### Non-Goals

- Direct writes into Nabaichuan production storage.
- Nabaichuan authentication.
- Nabaichuan UI changes.
- Cross-repository modification in this phase.

### Acceptance Criteria

- A single successful Bilifan run can produce Nabaichuan-compatible JSONL from
  Web UI.
- Multiple historical successful runs can be exported into one JSONL.
- Duplicate detection metadata exists in the bundle or export records.
- Export errors are explained without exposing local secrets.

## P2: Summary Quality and Control

### Objective

Give users control over output style and make generated notes more trustworthy.

### Features

1. Report templates.
   - Support at least:
     - 学习笔记.
     - 教程步骤.
     - 观点提炼.
     - 会议纪要.
   - Default remains 学习笔记.

2. Re-summarize mode.
   - Web UI allows rerunning summarization with a different template using
     existing transcript and chunks.
   - No audio redownload.
   - No Whisper rerun.

3. Evidence anchoring.
   - Chapters include references to transcript segment ids or time ranges.
   - Report makes it easy to jump from a claim to the relevant transcript
     region.

4. Long-video estimate.
   - Before starting a long video, show estimated chunks and rough expected
     stages.
   - Keep the existing long-video gate.

5. Summary QA metadata.
   - Store validation outcomes:
     - timestamp anchored.
     - chapter timestamps within chunk.
     - required fields present.
   - UI can show whether the summary passed validation.

### Non-Goals

- Human editing of chapters in Web UI.
- Multi-model comparison.
- Automatic hallucination detection beyond structural checks.

### Acceptance Criteria

- User can choose a summary template.
- Existing successful runs can be re-summarized without redownloading audio or
  rerunning Whisper.
- Report and bundle preserve evidence anchors.
- Summary validation status is visible enough for debugging.

## P3: Visual Evidence and Diagram Enhancements

### Objective

Add visuals only where they improve understanding and can be verified.

### Delivery Order

1. Real video frame screenshots.
2. Basic SVG diagrams.
3. Visual QA.

### Features

1. Frame extraction.
   - Optional `--with-frames` and Web UI toggle.
   - Extract frames only after transcript/chapter structure exists.
   - For each chapter, select a representative timestamp within the chapter
     range.
   - Use `ffmpeg` from locally available media or redownload minimal video only
     if explicitly designed and accepted later.

2. Screenshot artifact model.
   - Store screenshots under `media/frames/`.
   - Add relative paths to `content_bundle.json`.
   - Render screenshots in `report.html`.

3. Basic SVG diagrams.
   - Optional `--with-diagrams` and Web UI toggle.
   - Generate SVG from chapter content, not as decoration.
   - Diagrams can be:
     - flow.
     - timeline.
     - comparison.
     - checklist.
     - concept map.

4. Visual QA.
   - Verify report renders non-empty images.
   - Avoid broken image links.
   - Keep pixel-perfect QA out of scope unless later required.

### Non-Goals

- Full video download by default.
- Decorative illustrations.
- Long image slicing as default output.
- Pixel-level screenshot selection model.

### Acceptance Criteria

- If frames are enabled, each selected chapter has a visible frame when a frame
  can be extracted.
- If diagrams are enabled, each diagram is based on actual chapter content and
  contains meaningful labels.
- Missing visual assets degrade gracefully and do not fail HTML generation unless
  explicitly required.

## P4: Batch Queue and Persistent Jobs

### Objective

Support unattended processing of multiple URLs after single-job reliability is
stable.

### Features

1. Job persistence.
   - Store job state in a local file or lightweight SQLite database.
   - Preserve submitted, running, succeeded, failed, canceled statuses.
   - Recover visible status after service restart.

2. Queue.
   - User can submit multiple URLs.
   - Jobs run sequentially by default.
   - One active worker in this phase.

3. Batch controls.
   - Pause queue.
   - Resume queue.
   - Cancel pending job.
   - Retry failed job.

4. Batch import.
   - Textarea paste of multiple URLs.
   - Optional file import can be added later.

5. Batch reporting.
   - Summary counts:
     - queued.
     - running.
     - succeeded.
     - failed.
     - canceled.
   - Per-job links to artifacts.

### Non-Goals

- Parallel workers.
- Hosted scheduler.
- User accounts.
- Distributed queue.

### Acceptance Criteria

- User can paste multiple URLs and leave Bilifan running.
- Each job has independent status and artifacts.
- Service restart does not hide completed and failed jobs.
- Failed jobs can be retried without losing previous artifacts.

## Product Acceptance Process Per Phase

After each phase, the controller must perform a senior PM acceptance review:

1. Does the feature solve the user workflow, not just expose an endpoint?
2. Can a non-developer understand the main success and failure states?
3. Is the next action obvious after success, failure, or cancellation?
4. Does the feature preserve the local-only and permission-bound product
   boundary?
5. Does the phase avoid pulling in later-phase complexity?

If any answer is no, the phase is not accepted and requires an improvement plan
before proceeding.

## Engineering Acceptance Process Per Phase

Each phase must pass:

- Focused tests for new behavior.
- Full test suite.
- Documentation update if public behavior changed.
- Manual Web UI smoke when the change touches Web UI.
- Artifact inspection for at least one successful run when artifact shape
  changes.

## Agent Task Structure

For each phase:

1. Controller writes a phase implementation plan.
2. Implementer agent executes the plan with TDD.
3. Spec reviewer agent checks product/spec compliance.
4. Code-quality reviewer agent checks maintainability and integration risk.
5. Controller runs verification and commits.
6. Controller performs senior PM acceptance review and records gaps.

Agent prompts must include:

- Exact phase scope.
- Files likely involved.
- Non-goals.
- Acceptance criteria.
- Instruction to avoid unrelated refactors.
- Expected output summary.

## Risk Register

### R1: Scope Creep

P0-P4 is too large for one unreviewed implementation pass.

Mitigation: staged implementation and acceptance gates.

### R2: Web UI State Complexity

Cancel, retry, persistent jobs, and batch queue all touch job state.

Mitigation: implement cancel/retry first in memory, then add persistence in P4.

### R3: Platform Instability

Bilibili and YouTube extraction can fail due to platform, network, or cookie
changes.

Mitigation: expose clear diagnostics and retry paths rather than hiding failures.

### R4: Visual Feature Cost

Screenshots and SVG diagrams can consume time without improving user value.

Mitigation: delay visual work until P0-P2 are stable and make visuals optional.

### R5: Nabaichuan Coupling

Direct integration can make Bilifan depend on another repository's internals.

Mitigation: keep bundle and JSONL as the boundary in P1.

## Recommended First Implementation Slice

Start with P0 only.

Suggested P0 task order:

1. README and Web UI entrypoint docs.
2. User-friendly diagnostics mapping.
3. Audio artifact visibility.
4. Cancel running job.
5. Retry failed run from Web UI.
6. Stage timing and stuck-stage messaging.

Reason: these items reduce daily testing friction immediately and create the
foundation for P1-P4.
