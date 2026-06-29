# Bilifan Feishu Integration Design

## Goal

Let the user send one or more supported video links to a dedicated Feishu app,
have those links processed by Bilifan through the existing local pipeline, show
the same work in the Bilifan Web UI task center, and send final results back to
the originating Feishu conversation.

The first useful behavior is:

1. User sends one or more Bilibili or supported YouTube links in Feishu.
2. Hermes receives the Feishu message and submits a clean intake request to
   Bilifan.
3. Bilifan creates one queue task per accepted URL and processes them
   sequentially.
4. The Web UI task center shows those tasks alongside manually submitted tasks.
5. After each task finishes, Hermes sends a concise success, failure, or
   cancellation message back to the same Feishu chat or thread.

## Non-Goals

- Do not make Bilifan a Feishu SDK client.
- Do not store Feishu App ID, App Secret, tenant tokens, open IDs, or chat tokens
  in Bilifan job files.
- Do not modify Hermes profile, gateway, allowlist, `.env`, launchd, or service
  behavior as part of the Bilifan implementation.
- Do not expose Bilifan directly to the public internet.
- Do not add parallel video processing in the first version.
- Do not add Feishu card buttons for cancel/retry in the first version.
- Do not automatically export to Nabaichuan or write any other external system.

## Current Baseline

Bilifan already has the pieces needed for the processing side:

- `POST /api/jobs` starts a single local job.
- `POST /api/jobs/batch` submits a list of URLs into a persistent sequential
  queue.
- `GET /api/jobs/queue` powers the Web UI task center.
- Queue jobs persist under `outputs/_jobs/jobs.json`.
- Successful runs expose user-facing artifacts through token-protected run file
  endpoints.
- Failures already have a `friendly_error` structure suitable for Feishu final
  replies.

Hermes already has the pieces needed for the Feishu side:

- Feishu message normalization into `MessageEvent`.
- Feishu message ID deduplication.
- user/group admission and mention gating.
- per-chat serial handling.
- Feishu send/reply behavior, including thread-aware replies.
- processing reactions for in-progress and failed inbound messages.

Therefore, the integration should connect these systems through a narrow local
HTTP/API contract, not by duplicating Feishu runtime logic inside Bilifan.

## Recommended Architecture

Use Hermes as the Feishu runtime and Bilifan as the local task engine:

```text
Feishu message
  -> Hermes Feishu adapter
  -> Bilifan Feishu intake gateway hook
  -> Bilifan local intake API
  -> Bilifan BatchQueueManager
  -> Bilifan pipeline
  -> Bilifan Web UI task center
  -> Hermes completion watcher
  -> Feishu completion notification
```

Responsibilities:

- Feishu adapter: receive, normalize, authorize, deduplicate, and send replies.
- Hermes Bilifan intake gateway hook: deterministically intercept supported
  Feishu URL messages before the general agent conversation, call Bilifan
  intake API, and send the immediate acknowledgement.
- Bilifan intake API: validate the submitted batch and enqueue accepted URLs.
- Bilifan queue: persist task state and run jobs sequentially.
- Bilifan Web UI: display tasks, progress, artifacts, and failure details.
- Hermes completion watcher: observe task terminal states and send final Feishu
  messages.

## Alternatives Considered

### A. Hermes Runtime, Bilifan Task API

This is the recommended path.

Benefits:

- Reuses Hermes Feishu auth, dedup, admission, threading, and reply behavior.
- Keeps Bilifan free of Feishu credentials.
- Keeps Web UI and local queue as the processing source of truth.
- Matches the Nabaichuan pattern: Feishu is the human-facing entry layer, while
  the local project remains the auditable truth layer.

Tradeoff:

- Requires a small Hermes-side integration skill/tool and watcher in addition to
  Bilifan API work.

### B. Bilifan Directly Handles Feishu Webhooks

Rejected for the first version.

This would make Bilifan receive Feishu events and send Feishu replies directly.
It duplicates Hermes Feishu adapter responsibilities and forces Bilifan to own
Feishu credential, webhook, retry, and security logic.

### C. Hermes Runs Bilifan CLI Commands Only

Rejected as the durable architecture.

This can work for an early smoke, but it does not give clean queue state,
idempotency, or Web UI integration. It also makes terminal output parsing part
of the product contract.

## Batch Intake Semantics

One Feishu message can contain multiple URLs. Bilifan treats this as one intake
batch with multiple independent queue jobs.

Rules:

- Extract all supported video URLs from the message text.
- Preserve message order.
- Enqueue one task per accepted URL.
- Process tasks sequentially through the existing queue worker.
- Return one immediate Feishu acknowledgement for the whole batch.
- Send one final Feishu completion notification per task.
- If the same URL appears multiple times in the same Feishu message, enqueue it
  once and report the later occurrences as skipped duplicates.
- If a Feishu message is delivered more than once with the same platform
  `message_id`, the intake API must return the previously created batch result
  without adding duplicate tasks.
- If the user sends the same URL again in a later Feishu message, enqueue it as
  a new intentional task. Cross-message URL deduplication is not part of v1.
- Unsupported or invalid URLs should not fail the whole batch. They should be
  reported as rejected items while valid links are still queued.

The acknowledgement should be concise:

```text
已收到 3 个链接：2 个已入队，1 个不支持。
可以在 Bilifan 任务中心查看进度：<public_url or local entrypoint>
```

## Bilifan Intake API

Add a local, token-protected endpoint for external intake:

```text
POST /api/intake/feishu
```

Request shape:

```json
{
  "source": "feishu",
  "external_batch_id": "feishu:<message_id>",
  "submitted_by": {
    "display_name": "Jack"
  },
  "reply_target": {
    "platform": "feishu",
    "chat_id_ref": "opaque-hermes-ref",
    "thread_id_ref": "opaque-hermes-ref",
    "message_id_ref": "opaque-hermes-ref"
  },
  "urls": [
    "https://www.bilibili.com/video/BV1xx411c7mD?p=1",
    "https://youtu.be/dQw4w9WgXcQ"
  ],
  "defaults": {
    "format": "html,pdf",
    "summary_template": "AI 自动判断",
    "language": "auto",
    "force_whisper": false,
    "with_frames": false,
    "with_diagrams": false,
    "require_pdf": false,
    "allow_long_video": false
  }
}
```

Response shape:

```json
{
  "ok": true,
  "batch_id": "feishu:<message_id>",
  "accepted": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1",
      "job_id": "queue-job-id",
      "status": "queued"
    }
  ],
  "rejected": [
    {
      "url": "https://example.com/not-supported",
      "reason": "unsupported_url"
    }
  ],
  "duplicates": [
    {
      "url": "https://www.bilibili.com/video/BV1xx411c7mD?p=1",
      "reason": "duplicate_in_batch"
    }
  ]
}
```

The endpoint should validate local processing consent the same way Web UI job
creation does. If consent has not been accepted, reject the whole batch with a
clear error so Hermes can reply with the required local setup action.

## Queue Metadata

Extend queue jobs with an optional external metadata block:

```json
{
  "origin": {
    "source": "feishu",
    "label": "来自飞书",
    "external_batch_id": "feishu:<message_id>",
    "external_item_id": "feishu:<message_id>:1",
    "submitted_by": "Jack",
    "reply_target_ref": "opaque-hermes-owned-ref"
  }
}
```

Important boundary:

- Bilifan can store opaque reply references needed by Hermes, but it should not
  store Feishu credentials or raw access tokens.
- The Web UI should display only a human label such as `来自飞书`, not raw
  Feishu object identifiers.

The Web UI task card can add one source metadata entry:

```text
来源：飞书
```

No larger UI redesign is required for v1.

## Idempotency

Use `external_batch_id` plus per-item index as the first idempotency key.

Behavior:

- Repeating the same `external_batch_id` must not create new queue jobs.
- The response should replay the original accepted/rejected/duplicate result if
  available.
- If Bilifan has restarted and only queue jobs remain, it should still avoid
  obvious duplicates by matching stored `origin.external_batch_id`.
- A later Feishu message with a different `external_batch_id` is a new user
  request even if the URL is identical.

This keeps accidental delivery retries safe without blocking intentional reruns.

## Completion Notifications

The first version should send two kinds of Feishu replies.

Immediate acknowledgement:

- Sent by Hermes after the intake API returns.
- One message per Feishu intake batch.
- Includes accepted, rejected, and duplicate counts.
- Includes the Bilifan task center entrypoint when available.

Final completion notification:

- Sent by Hermes after each accepted job reaches `succeeded`, `failed`, or
  `canceled`.
- One message per job, because different videos finish at different times.
- Reply to the same chat/thread as the original message when Hermes has that
  context.

Success message content:

- video title if known;
- status;
- task/run link in Bilifan Web UI;
- `transcript.html` and `report.html` links when available;
- warnings only if they affect user action.

Failure message content:

- video title or original URL;
- failed stage;
- `friendly_error.title`;
- `friendly_error.cause`;
- `friendly_error.next_action`;
- Bilifan task center link.

Do not stream every progress update to Feishu in v1. The Web UI is the detailed
progress surface. Feishu should stay quiet between acknowledgement and terminal
state.

## Completion Watcher Choice

Use a Hermes-side watcher in the first version.

Reason:

- Bilifan remains local-only and does not need outbound Feishu logic.
- Hermes already owns Feishu send/reply behavior.
- The watcher can poll `GET /api/jobs/queue` and detect terminal states for
  jobs with `origin.source == "feishu"`.

A later version can add an explicit Bilifan callback/event stream if polling is
too slow or too indirect. That should still call a Hermes-owned endpoint rather
than Feishu directly.

## Security And Authorization

The confirmed user-facing authorization rule:

> When Jack sends one or more supported video URLs to the dedicated Feishu app,
> that message authorizes Bilifan to enqueue those URLs for local processing and
> send completion notifications back to the same Feishu conversation.

This authorization does not allow:

- batch changes beyond the submitted links;
- Hermes profile, gateway, memory, SOUL, `.env`, credential, or allowlist
  changes;
- Bilifan service restarts;
- Cloudflare or DNS changes;
- external publishing or posting;
- Nabaichuan writes;
- commits, pushes, or deploys.

The integration must keep Bilifan's existing token protection. Hermes needs a
local Bilifan API token or equivalent local credential, but that credential
belongs to the Hermes-to-Bilifan local integration, not to Feishu.

## Phased Delivery

### P0: Design And Contract

- Land this design document.
- Keep the architecture decision in project docs.
- Do not change runtime code.

Acceptance:

- The design covers single-link and multi-link Feishu messages.
- The design defines ownership of Feishu runtime versus Bilifan task state.
- The design defines idempotency, final notification, and non-goals.

### P1: Bilifan Intake API And Queue Metadata

- Add `POST /api/intake/feishu`.
- Add optional origin metadata to queue jobs.
- Add per-batch idempotency.
- Show `来源：飞书` in the Web UI task center.
- Add focused tests for accepted, rejected, duplicate, consent-required, and
  idempotent repeated-message cases.

Acceptance:

- A local test can submit two valid URLs and one unsupported URL.
- The Web UI task center shows two queued tasks from Feishu.
- Repeating the same `external_batch_id` does not create duplicate tasks.
- Existing Web UI batch submission still works.

### P2: Hermes Intake Gateway Hook And Runtime Profile

- Add a Hermes-side Bilifan intake workflow for the dedicated Feishu app.
- Prefer a profile-enabled project plugin using Hermes'
  `pre_gateway_dispatch` hook over model-inferred tool use, so Feishu URL
  messages are routed deterministically.
- Extract URLs from Feishu text.
- Call Bilifan intake API.
- Send immediate acknowledgement to Feishu.
- Create or update the dedicated Bilifan Hermes profile only after confirming
  the exact profile, credential source, restart scope, and real-message smoke
  target.

Acceptance:

- A Feishu message with multiple links produces one acknowledgement with counts.
- No Bilifan code contains Feishu credentials.
- Unsupported links are reported without blocking valid links.
- The real-runtime smoke is limited to the dedicated Bilifan profile and does
  not modify shared Feishu adapter behavior.

### P3: Completion Watcher And Final Replies

- Add Hermes-side watcher for Feishu-origin queue jobs.
- Poll Bilifan task state.
- Send one terminal message per accepted job.
- Mark notified jobs so terminal messages are not repeated after watcher restart.

Acceptance:

- Successful jobs send report/transcript links.
- Failed jobs send `friendly_error` details.
- Restarting the watcher does not duplicate already-sent completion messages.

### P4: Operator Controls

Add only after P1-P3 are stable:

- Feishu cancel for queued jobs.
- Feishu retry for failed jobs.
- richer interactive cards.
- batch-level summary after all jobs in one intake batch finish.
- optional event stream instead of polling.

## Test Matrix

Core Bilifan tests:

- intake rejects when local processing consent is missing;
- one valid URL creates one queue job;
- multiple valid URLs create multiple queue jobs in order;
- mixed valid and invalid URLs partially accept;
- duplicate URL inside the same message is skipped after the first occurrence;
- repeated `external_batch_id` is idempotent;
- queue persistence preserves origin metadata;
- Web UI renders Feishu source label;
- existing `/api/jobs/batch` behavior is unchanged.

Hermes integration tests:

- text URL extraction handles multiple links and surrounding prose;
- Feishu duplicate message delivery does not duplicate Bilifan tasks;
- acknowledgement summarizes accepted, rejected, and duplicate items;
- completion watcher sends one terminal notification per accepted job;
- watcher restart does not resend notifications.

Manual smoke:

- Send one Bilibili URL from Feishu.
- Send three URLs in one Feishu message.
- Confirm Bilifan Web UI shows each accepted URL as a queue task.
- Confirm Feishu receives final success/failure replies.

## Risks

### R1: Feishu Chat Becomes Too Noisy

Mitigation: v1 sends only an immediate batch acknowledgement and terminal
messages. Detailed progress stays in the Web UI.

### R2: Duplicate Task Creation

Mitigation: use `external_batch_id` and per-item origin metadata for idempotency.

### R3: Credential Boundary Drift

Mitigation: Bilifan never stores Feishu app credentials or tenant tokens. Hermes
owns Feishu runtime and reply behavior.

### R4: Long Task Latency

Mitigation: do not keep the Feishu request waiting for the full pipeline. Send
an immediate acknowledgement, then use a watcher for terminal notification.

### R5: Batch Failure Semantics Become Ambiguous

Mitigation: treat each URL as an independent queue job. Batch acknowledgement is
only intake status; completion is per job.

## Implementation Starting Point

Start with P1 only. The likely files are:

- `src/bilifan/web/app.py`
- `src/bilifan/web/queue.py`
- `src/bilifan/web/ui.py`
- `tests/test_web_jobs.py`
- `tests/test_queue.py`
- `tests/test_web_ui.py`

Do not touch Hermes, Feishu credentials, Cloudflare scripts, or Nabaichuan in
P1. Hermes work starts only after the Bilifan intake API is locally verified.
