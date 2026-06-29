# Bilifan Context

## Product Boundary

Bilifan is a local, permission-bound video knowledge workbench. It accepts
supported video URLs, creates transcript/article/report artifacts under the
local `outputs/` tree, and exposes task state through the Web UI.

Bilifan is not a hosted scraping service, not a Feishu/Lark bot runtime, and not
the owner of Feishu credentials. External chat systems should submit clean task
requests into Bilifan rather than making Bilifan handle chat-platform events
directly.

## Terms

- **Run**: one completed or failed processing attempt for one video URL. A run
  writes artifacts such as `transcript.html`, `report.html`,
  `content_bundle.json`, and diagnostics under `outputs/<output_id>/runs/<run_id>/`.
- **Task**: the Web UI representation of work in progress or queued work. A
  task eventually points to a run when processing reaches a run directory.
- **Task Center**: the Web UI queue/history surface backed by Bilifan's job and
  queue state. It is the local source of truth for user-visible processing
  status.
- **Feishu Intake**: a message from the dedicated Feishu app that contains one
  or more supported video URLs and asks Bilifan to process them.
- **Hermes Intake Gateway Hook**: the Hermes-side deterministic routing layer
  that intercepts Feishu intake messages before the general agent conversation,
  submits the batch to Bilifan, and sends the immediate acknowledgement.
- **External Job**: a Bilifan task created from an external intake channel such
  as Feishu. It still runs through the same local queue and pipeline as Web UI
  jobs.
- **Intake Batch**: the group of links extracted from one Feishu message. Batch
  links are accepted together but processed sequentially as independent Bilifan
  tasks.
- **Completion Notification**: the final reply sent back to the originating
  Feishu chat or thread after each external job succeeds, fails, or is canceled.

## Confirmed Feishu Intake Semantics

When Jack sends one or more supported video URLs to the dedicated Feishu app,
that message authorizes Bilifan to enqueue those URLs for local processing and
send completion notifications back to the same Feishu conversation.

This authorization does not cover batch configuration changes, Hermes profile
or gateway changes, credential changes, service restarts, external publishing,
or cross-project writes.
