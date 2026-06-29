# Bilifan Feishu Intake P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Bilifan-side Feishu intake foundation: a local API accepts one Feishu message containing one or more video links, enqueues one Bilifan task per accepted link in order, records Feishu origin metadata, exposes the tasks in the existing web task center, and returns an idempotent intake result for repeated Feishu message delivery.

**Architecture:** Hermes remains the owner of Feishu app runtime, webhook verification, message parsing, credentials, outbound replies, and completion watching. Bilifan adds a local `POST /api/intake/feishu` endpoint plus queue-level intake-batch persistence. Existing web batch submission remains unchanged for browser users. The new endpoint uses the same local consent gate and the same pipeline request model as the web UI. Queue jobs gain an optional `origin` object so the web UI can show `来自飞书`.

**Tech Stack:** Python, FastAPI, Pydantic, existing `BatchQueueManager`, existing `PipelineRequest`, pytest, Starlette `TestClient`, existing embedded web UI JavaScript tests.

---

## Scope

This plan implements P1 only.

In scope:

- Add `POST /api/intake/feishu` in `src/bilifan/web/app.py`.
- Support multiple URLs in one payload and enqueue accepted URLs one by one in message order.
- Reject unsupported or empty URLs at the item level while still accepting valid URLs.
- Skip duplicate URLs within the same Feishu message.
- Make repeated `external_batch_id` calls idempotent: replay the original intake result without creating new jobs.
- Persist Feishu origin metadata on queue jobs.
- Show Feishu origin label in the web task center.
- Cover the behavior with focused tests.

Out of scope:

- No Hermes code changes.
- No Feishu app credentials, webhook configuration, or outbound message sending.
- No Cloudflare tunnel, launchd service, deployment, or external account writes.
- No Nabaichuan file edits.
- No unrelated refactors of the processing pipeline.

## Expected API Contract

Request:

```json
{
  "source": "feishu",
  "external_batch_id": "feishu:message_123",
  "submitted_by": {
    "display_name": "Jack"
  },
  "reply_target": {
    "platform": "feishu",
    "chat_id_ref": "chat_ref_opaque",
    "thread_id_ref": "thread_ref_opaque",
    "message_id_ref": "message_ref_opaque"
  },
  "urls": [
    "https://www.bilibili.com/video/BV1xx411c7mD",
    "https://youtu.be/dQw4w9WgXcQ"
  ],
  "defaults": {
    "format": "markdown",
    "force_whisper": false,
    "language": "zh",
    "summary_template": "default",
    "with_frames": false,
    "with_diagrams": false,
    "require_pdf": false,
    "allow_long_video": false
  }
}
```

Successful response:

```json
{
  "ok": true,
  "batch_id": "feishu:message_123",
  "idempotent": false,
  "accepted": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD",
      "job_id": "queue-job-id",
      "status": "queued"
    }
  ],
  "rejected": [
    {
      "url": "notaurl",
      "index": 2,
      "reason": "unsupported_url"
    }
  ],
  "duplicates": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD",
      "index": 3,
      "first_index": 1,
      "reason": "duplicate_in_batch"
    }
  ]
}
```

Consent failure response:

```json
{
  "detail": "Local processing consent is required before starting a Feishu intake."
}
```

HTTP status for consent failure: `409`.

---

## Tasks

- [x] Task 1: Add queue support for persisted origin metadata and idempotent intake batches.
- [x] Task 2: Add the Feishu intake endpoint and shared request-building helper.
- [x] Task 3: Render Feishu source labels in the web task center.
- [x] Task 4: Add focused tests for queue persistence, API behavior, and UI rendering.
- [x] Task 5: Run the minimum verification suite and document any existing dirty-tree interference.

---

## Task 1: Queue Origin Metadata And Intake Idempotency

Files:

- `src/bilifan/web/queue.py`
- `tests/test_queue.py`

Implementation steps:

1. Add imports:

```python
from copy import deepcopy
from typing import Any
```

2. Extend `QueueJob` with an origin field:

```python
origin: dict[str, Any] = field(default_factory=dict)
```

3. Include `origin` in `QueueJob.as_dict()`:

```python
"origin": dict(self.origin),
```

4. Add an intake-batch store to `BatchQueueManager.__init__`:

```python
self._intake_batches: dict[str, dict[str, Any]] = {}
```

5. In `_load`, read `intake_batches` from persisted state:

```python
raw_batches = data.get("intake_batches")
if isinstance(raw_batches, dict):
    self._intake_batches = deepcopy(raw_batches)
```

6. In `_load`, restore each job origin safely:

```python
raw_origin = raw_job.get("origin")
origin = raw_origin if isinstance(raw_origin, dict) else {}
```

Pass `origin=origin` when constructing `QueueJob`.

7. In `_persist_locked`, write the batch store:

```python
"intake_batches": deepcopy(self._intake_batches),
```

8. Add a public method on `BatchQueueManager`:

```python
def submit_intake_batch(
    self,
    *,
    batch_id: str,
    requests: list[PipelineRequest],
    origins: list[dict[str, Any]],
    rejected: list[dict[str, Any]] | None = None,
    duplicates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if len(requests) != len(origins):
        raise ValueError("requests and origins must have the same length")

    rejected_items = deepcopy(rejected or [])
    duplicate_items = deepcopy(duplicates or [])
    should_start = False

    with self._lock:
        existing = self._intake_batches.get(batch_id)
        if existing is not None:
            replay = deepcopy(existing)
            replay["idempotent"] = True
            return replay

        accepted: list[dict[str, Any]] = []
        for request, origin in zip(requests, origins, strict=True):
            job = QueueJob(
                job_id=uuid.uuid4().hex,
                status="queued",
                request=_request_to_payload(request),
                origin=deepcopy(origin),
            )
            self._jobs.append(job)
            accepted.append(
                {
                    "url": request.url,
                    "job_id": job.job_id,
                    "status": job.status,
                }
            )

        result = {
            "ok": True,
            "batch_id": batch_id,
            "idempotent": False,
            "accepted": accepted,
            "rejected": rejected_items,
            "duplicates": duplicate_items,
        }
        self._intake_batches[batch_id] = deepcopy(result)
        self._persist_locked()
        should_start = bool(accepted)

    if should_start:
        self._ensure_worker()
    return deepcopy(result)
```

9. Preserve origin on retry jobs in the existing retry method:

```python
origin=deepcopy(job.origin),
```

Add it to the `QueueJob` constructor call that creates the retry job.

10. Add a focused queue test to `tests/test_queue.py`:

```python
def test_intake_batch_persists_origin_metadata_and_replays_idempotent_result(tmp_path: Path) -> None:
    queue = BatchQueueManager(
        state_path=tmp_path / "jobs.json",
        history_dir=tmp_path / "history",
        runner=lambda request, callbacks: None,
        run_inline=True,
        paused=True,
    )
    requests = [
        _request(tmp_path, url="https://www.bilibili.com/video/BV1xx411c7mD"),
        _request(tmp_path, url="https://youtu.be/dQw4w9WgXcQ"),
    ]
    origins = [
        {
            "source": "feishu",
            "label": "来自飞书",
            "external_batch_id": "feishu:message_123",
            "external_item_id": "feishu:message_123:1",
            "submitted_by": "Jack",
            "reply_target_ref": "feishu:message_123",
        },
        {
            "source": "feishu",
            "label": "来自飞书",
            "external_batch_id": "feishu:message_123",
            "external_item_id": "feishu:message_123:2",
            "submitted_by": "Jack",
            "reply_target_ref": "feishu:message_123",
        },
    ]

    first = queue.submit_intake_batch(
        batch_id="feishu:message_123",
        requests=requests,
        origins=origins,
        rejected=[{"url": "notaurl", "index": 3, "reason": "unsupported_url"}],
        duplicates=[
            {
                "url": "https://www.bilibili.com/video/BV1xx411c7mD",
                "index": 4,
                "first_index": 1,
                "reason": "duplicate_in_batch",
            }
        ],
    )
    second = queue.submit_intake_batch(
        batch_id="feishu:message_123",
        requests=requests,
        origins=origins,
    )

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["accepted"] == first["accepted"]
    assert len(queue.state()["items"]) == 2
    assert queue.state()["items"][0]["origin"]["label"] == "来自飞书"

    restored = BatchQueueManager(
        state_path=tmp_path / "jobs.json",
        history_dir=tmp_path / "history",
        runner=lambda request, callbacks: None,
        run_inline=True,
        paused=True,
    )
    replay = restored.submit_intake_batch(
        batch_id="feishu:message_123",
        requests=requests,
        origins=origins,
    )

    assert replay["idempotent"] is True
    assert replay["accepted"] == first["accepted"]
    assert len(restored.state()["items"]) == 2
    assert restored.state()["items"][1]["origin"]["external_item_id"] == "feishu:message_123:2"
```

Verification command for this task:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_queue.py::test_intake_batch_persists_origin_metadata_and_replays_idempotent_result -q
```

Expected result:

```text
1 passed
```

---

## Task 2: Feishu Intake Endpoint

Files:

- `src/bilifan/web/app.py`
- `tests/test_web_jobs.py`

Implementation steps:

1. Update imports:

```python
from pydantic import BaseModel, Field

from bilifan.sources import SourceAdapterError, resolve_source_adapter
```

2. Add Pydantic models near the existing web payload models:

```python
class FeishuIntakeSubmittedByPayload(BaseModel):
    display_name: str | None = None


class FeishuIntakeReplyTargetPayload(BaseModel):
    platform: str = "feishu"
    chat_id_ref: str | None = None
    thread_id_ref: str | None = None
    message_id_ref: str | None = None


class FeishuIntakeDefaultsPayload(BaseModel):
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str | None = WEB_DEFAULTS["language"]
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


class FeishuIntakePayload(BaseModel):
    source: str = "feishu"
    external_batch_id: str
    submitted_by: FeishuIntakeSubmittedByPayload | None = None
    reply_target: FeishuIntakeReplyTargetPayload | None = None
    urls: list[str]
    defaults: FeishuIntakeDefaultsPayload = Field(default_factory=FeishuIntakeDefaultsPayload)
```

3. Add a shared helper that can be used by both `/api/jobs/batch` and `/api/intake/feishu`:

```python
def _pipeline_request_from_web_defaults(
    url: str,
    *,
    defaults: BatchJobCreatePayload | FeishuIntakeDefaultsPayload,
    output_dir: Path,
    data_dir: Path,
) -> PipelineRequest:
    return PipelineRequest(
        url=url,
        output_dir=output_dir,
        data_dir=data_dir,
        output_format=defaults.format,
        force_whisper=defaults.force_whisper,
        language=defaults.language or None,
        summary_template=_validated_summary_template(defaults.summary_template),
        with_frames=defaults.with_frames,
        with_diagrams=defaults.with_diagrams,
        require_pdf=defaults.require_pdf,
        allow_long_video=defaults.allow_long_video,
    )
```

4. Replace the repeated request construction inside the existing `/api/jobs/batch` endpoint with:

```python
requests = [
    _pipeline_request_from_web_defaults(
        url,
        defaults=payload,
        output_dir=output_dir,
        data_dir=data_dir,
    )
    for url in urls
]
```

5. Add URL validation and reply-target helpers:

```python
def _intake_url_rejection_reason(url: str) -> str | None:
    if not url:
        return "empty_url"
    try:
        adapter = resolve_source_adapter(url)
        adapter.parse_url(url)
    except (SourceAdapterError, ValueError):
        return "unsupported_url"
    return None


def _reply_target_ref(reply_target: FeishuIntakeReplyTargetPayload | None) -> str | None:
    if reply_target is None:
        return None
    for value in (
        reply_target.message_id_ref,
        reply_target.thread_id_ref,
        reply_target.chat_id_ref,
    ):
        if value:
            return value
    return None
```

6. Add the endpoint inside `create_app`, after `/api/jobs/batch`:

```python
    @app.post("/api/intake/feishu")
    def create_feishu_intake(payload: FeishuIntakePayload, _: None = Depends(require_token)) -> dict[str, Any]:
        if payload.source != "feishu":
            raise HTTPException(status_code=400, detail="Only source=feishu is supported.")

        batch_id = payload.external_batch_id.strip()
        if not batch_id:
            raise HTTPException(status_code=400, detail="external_batch_id is required.")

        if not consent_store.has_consent():
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before starting a Feishu intake.",
            )

        if not payload.urls:
            raise HTTPException(status_code=400, detail="At least one URL is required.")

        requests: list[PipelineRequest] = []
        origins: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        seen: dict[str, int] = {}
        reply_target_ref = _reply_target_ref(payload.reply_target)
        submitted_by = payload.submitted_by.display_name if payload.submitted_by else None

        for index, raw_url in enumerate(payload.urls, start=1):
            url = raw_url.strip()
            if url in seen:
                duplicates.append(
                    {
                        "url": url,
                        "index": index,
                        "first_index": seen[url],
                        "reason": "duplicate_in_batch",
                    }
                )
                continue
            seen[url] = index

            reason = _intake_url_rejection_reason(url)
            if reason is not None:
                rejected.append({"url": url, "index": index, "reason": reason})
                continue

            requests.append(
                _pipeline_request_from_web_defaults(
                    url,
                    defaults=payload.defaults,
                    output_dir=output_dir,
                    data_dir=data_dir,
                )
            )
            origins.append(
                {
                    "source": "feishu",
                    "label": "来自飞书",
                    "external_batch_id": batch_id,
                    "external_item_id": f"{batch_id}:{index}",
                    "submitted_by": submitted_by,
                    "reply_target_ref": reply_target_ref,
                }
            )

        return queue.submit_intake_batch(
            batch_id=batch_id,
            requests=requests,
            origins=origins,
            rejected=rejected,
            duplicates=duplicates,
        )
```

7. Add API tests:

```python
def test_feishu_intake_accepts_valid_urls_rejects_unsupported_and_skips_duplicates(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(request: PipelineRequest, callbacks: PipelineCallbacks) -> PipelineResult:
        calls.append(request.url)
        return _result(request)

    app = create_app(
        output_dir=tmp_path / "out",
        data_dir=tmp_path / "data",
        runner=runner,
        run_queue_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/intake/feishu",
        json={
            "source": "feishu",
            "external_batch_id": "feishu:message_123",
            "submitted_by": {"display_name": "Jack"},
            "reply_target": {"platform": "feishu", "message_id_ref": "msg_ref"},
            "urls": [
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "notaurl",
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "https://youtu.be/dQw4w9WgXcQ",
            ],
            "defaults": {"summary_template": "default", "with_diagrams": True},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["idempotent"] is False
    assert [item["url"] for item in body["accepted"]] == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://youtu.be/dQw4w9WgXcQ",
    ]
    assert body["rejected"] == [{"url": "notaurl", "index": 2, "reason": "unsupported_url"}]
    assert body["duplicates"] == [
        {
            "url": "https://www.bilibili.com/video/BV1xx411c7mD",
            "index": 3,
            "first_index": 1,
            "reason": "duplicate_in_batch",
        }
    ]
    assert calls == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://youtu.be/dQw4w9WgXcQ",
    ]

    queue_response = client.get("/api/jobs/queue")
    queue_body = queue_response.json()
    assert queue_body["items"][0]["origin"]["label"] == "来自飞书"
    assert queue_body["items"][0]["origin"]["reply_target_ref"] == "msg_ref"
```

```python
def test_feishu_intake_requires_local_processing_consent(tmp_path: Path) -> None:
    app = create_app(
        output_dir=tmp_path / "out",
        data_dir=tmp_path / "data",
        runner=lambda request, callbacks: _result(request),
        run_queue_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/intake/feishu",
        json={
            "source": "feishu",
            "external_batch_id": "feishu:message_123",
            "urls": ["https://www.bilibili.com/video/BV1xx411c7mD"],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Local processing consent is required before starting a Feishu intake."
```

```python
def test_feishu_intake_is_idempotent_by_external_batch_id(tmp_path: Path) -> None:
    calls: list[str] = []

    def runner(request: PipelineRequest, callbacks: PipelineCallbacks) -> PipelineResult:
        calls.append(request.url)
        return _result(request)

    app = create_app(
        output_dir=tmp_path / "out",
        data_dir=tmp_path / "data",
        runner=runner,
        run_queue_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    payload = {
        "source": "feishu",
        "external_batch_id": "feishu:message_123",
        "urls": ["https://www.bilibili.com/video/BV1xx411c7mD"],
    }

    first = client.post("/api/intake/feishu", json=payload).json()
    second = client.post("/api/intake/feishu", json=payload).json()

    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert second["accepted"] == first["accepted"]
    assert calls == ["https://www.bilibili.com/video/BV1xx411c7mD"]
```

Verification command for this task:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_jobs.py::test_feishu_intake_accepts_valid_urls_rejects_unsupported_and_skips_duplicates tests/test_web_jobs.py::test_feishu_intake_requires_local_processing_consent tests/test_web_jobs.py::test_feishu_intake_is_idempotent_by_external_batch_id -q
```

Expected result:

```text
3 passed
```

---

## Task 3: Web Task Center Source Label

Files:

- `src/bilifan/web/ui.py`
- `tests/test_web_ui.py`

Implementation steps:

1. In the embedded JavaScript, add a helper near `renderQueue(queue)`:

```javascript
function queueSourceLabel(item) {
  if (item && item.source === "current") {
    return "当前任务";
  }
  if (item && item.origin && typeof item.origin.label === "string" && item.origin.label.trim()) {
    return item.origin.label.trim();
  }
  return "队列任务";
}
```

2. Replace the existing inline source label logic in `renderQueue(queue)`:

```javascript
const sourceLabel = queueSourceLabel(item);
```

3. Add a UI test:

```python
def test_render_app_script_queue_item_shows_feishu_origin_label() -> None:
    html = render_app(config=_config(), initial_consent=True)
    assert "function queueSourceLabel(item)" in html
    assert 'return "当前任务";' in html
    assert 'return item.origin.label.trim();' in html
    assert 'return "队列任务";' in html
```

Verification command for this task:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_ui.py::test_render_app_script_queue_item_shows_feishu_origin_label -q
```

Expected result:

```text
1 passed
```

---

## Task 4: Regression Verification

Run the focused existing suites touched by this plan:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_queue.py tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected result:

```text
all selected tests pass
```

If an existing test fails due to pre-existing dirty-tree changes, capture:

- the failing test name,
- the assertion or exception,
- whether the failure reproduces before this feature branch changes,
- the file already dirty before implementation.

Do not rewrite unrelated tests or source files to make this feature look passing.

---

## Task 5: Manual Local API Smoke Test

Start Bilifan locally only after the tests above pass:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m bilifan.web.app --port 8711
```

In another shell, after accepting local processing consent through the web UI or existing consent API, call:

```bash
curl -sS \
  -X POST http://127.0.0.1:8711/api/intake/feishu \
  -H 'Content-Type: application/json' \
  -d '{
    "source": "feishu",
    "external_batch_id": "feishu:manual_message_001",
    "submitted_by": {"display_name": "Jack"},
    "reply_target": {"platform": "feishu", "message_id_ref": "manual_ref_001"},
    "urls": [
      "https://www.bilibili.com/video/BV1xx411c7mD",
      "notaurl",
      "https://www.bilibili.com/video/BV1xx411c7mD"
    ],
    "defaults": {"summary_template": "default"}
  }'
```

Expected response shape:

```json
{
  "ok": true,
  "batch_id": "feishu:manual_message_001",
  "idempotent": false,
  "accepted": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD",
      "job_id": "non-empty",
      "status": "queued"
    }
  ],
  "rejected": [
    {
      "url": "notaurl",
      "index": 2,
      "reason": "unsupported_url"
    }
  ],
  "duplicates": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD",
      "index": 3,
      "first_index": 1,
      "reason": "duplicate_in_batch"
    }
  ]
}
```

Run the same `curl` command again. Expected difference:

```json
{
  "idempotent": true
}
```

The `accepted[0].job_id` value must match the first response.

---

## Completion Criteria

- `POST /api/intake/feishu` exists and is token-protected through the existing web token dependency.
- The endpoint enforces the same local consent gate as browser job creation.
- A single Feishu message with multiple valid URLs creates multiple queue jobs in order.
- Duplicate URLs inside the same Feishu message are skipped and reported.
- Unsupported URLs are reported in `rejected` without preventing valid URLs from queuing.
- Repeated `external_batch_id` calls do not create new queue jobs and return the original accepted job IDs.
- Queue state persists `origin` metadata and `intake_batches`.
- Web task center can render `来自飞书` for Feishu-origin queue items.
- Focused tests and touched regression suites pass, or any unrelated pre-existing failures are documented with evidence.

## Handoff Notes For P2 And P3

P2 should live in the Hermes/Nabaichuan side and call this endpoint. It should parse links from Feishu text, construct `external_batch_id` from Feishu message identity, and send one immediate acknowledgement per Feishu message.

P3 should add completion notification delivery from Hermes after observing Bilifan queue completion. It should use persisted `origin.reply_target_ref` and Bilifan job state, and it should define notification idempotency separately from intake idempotency.
