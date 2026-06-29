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
- **Transcription Routing**: the decision step that chooses transcript source,
  Whisper language, and Whisper model before audio transcription. It should be
  explainable from recorded signals, not only inferred from the final artifact
  label.
- **Routing Decision**: the structured record of why Transcription Routing chose
  a model and language. It includes the selected route, confidence, reason, and
  relevant metadata signals.
- **Transcript Quality Check**: the post-transcription validation step that
  checks whether the transcript looks compatible with the expected language and
  normal speech, separate from completeness checks such as segment coverage.
- **Auto-Correction Retry**: one automatic retry with the alternate Whisper
  language/model route when the first Whisper transcript likely used the wrong
  route.
- **Succeeded With Warning**: a terminal user-visible outcome where Bilifan has
  produced artifacts, but the transcript quality or route confidence still needs
  user attention. Queue accounting may remain `succeeded`, but the Task Center
  and completion notification must not present it as an ordinary clean success.

## Confirmed Feishu Intake Semantics

When Jack sends one or more supported video URLs to the dedicated Feishu app,
that message authorizes Bilifan to enqueue those URLs for local processing and
send completion notifications back to the same Feishu conversation.

This authorization does not cover batch configuration changes, Hermes profile
or gateway changes, credential changes, service restarts, external publishing,
or cross-project writes.

## Confirmed Transcription Routing Semantics

When Bilifan uses Whisper fallback and the selected model appears wrong after
transcription, Bilifan should automatically try one alternate Whisper
language/model route once before surfacing the result.

If the alternate route passes quality checks, Bilifan should use the corrected
transcript and record that an auto-correction retry happened. If the alternate
route is still suspicious, Bilifan should not silently present the task as an
ordinary clean success. It should finish as Succeeded With Warning or fail with
a plain-language diagnostic, depending on how usable the artifacts are.
