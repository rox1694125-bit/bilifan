# Bilifan Context

## Product Boundary

Bilifan is a local video transcript workbench. It accepts supported video URLs,
keeps the original subtitle or speech-recognition transcript, and creates a
readable edited transcript under `outputs/`. Editing may correct transcription
errors, remove repeated fillers, punctuate, segment, and add section titles;
it must preserve meaning and uncertainty, without adding interpretations,
conclusions, or action advice.

New processing does not generate a template-based main report, chapter summary,
diagram, or screenshot. Existing reports remain readable and downloadable.
Local operation describes the service and artifact storage: the configured
Codex provider may receive transcript text after local-processing consent.

Bilifan does not own Feishu credentials or implement the chat-platform runtime.
External systems submit task requests; Bilifan exposes their state and results
through the Web UI. Export creates local files, not writes into an external
knowledge base.

## Terms and Deliverables

- **Original transcript**: acquired subtitles or speech-recognition text with
  time positions, saved as `transcript.json`, TXT, and standard SRT before AI
  editing. It may contain recognition errors; it is a comparison source, not
  a guarantee of verbatim accuracy. The SRT download package includes a separate
  quality explanation rather than inserting warnings as subtitle lines.
- **Edited transcript**: the readable, source-linked article represented by
  `transcript_article.json` and `transcript.html`, with PDF when requested.
  Its sections support comparing the original text and returning to the video.
- **Historical main report**: an existing `report.html`, `report.pdf`, or
  `chapters.json`. Article retries preserve these files. A new article bundle
  does not treat old report conclusions as newly generated content.
- **Run**: a stable artifact directory at
  `outputs/<output_id>/runs/<run_id>/`. Explicit retries reuse this identity
  while generating replacement article outputs in an isolated workspace.
- **Task**: a durable operation with its own job ID, input snapshot, source,
  status, and run binding. It can process a URL or retry an existing run.
- **Task Center**: the Web queue and history surface. Single-video, collection,
  batch, Feishu, and retry requests share one persistent task ledger.
- **Successful delivery**: original transcript, valid edited transcript,
  article HTML, and content bundle have been completed and validated. PDF
  retains its best-effort or required behavior. A missing main report is normal.
- **Content bundle**: the additive v1 interchange format. New deliveries use
  `output_profile=transcript_article_v1`, with summary `not_generated`, empty
  chapters, and summary validation `not_applicable`.

The original transcript remains available if editing fails. Retries publish a
replacement only after validating its delivery; failure preserves previous
results. The latest-success pointer advances only for a successful delivery
and does not replace a newer valid success when an older run is retried.

## Quality and Export Semantics

Quality is separate from execution success. Shared checks distinguish
`clean` (no obvious issue found by automatic checks), `needs_review`, `unusable`,
and `unknown`. They check language, coverage, and edits to numbers, units, code,
and substantive content; they do not establish factual accuracy or human approval.
Missing historical evidence is not a passing check.

Warnings follow newly generated Web results, article HTML/PDF, original TXT,
SRT packages, bundles, and every JSONL record. Unusable raw text stops AI editing
while preserving available originals and diagnostics. Readable but suspicious
content can finish with a visible review warning.

Single-run export defaults to withholding content that needs review; batch
export skips it and records why. Explicit inclusion preserves the warning and
does not mark the content reviewed. Historical exports rerun checks supported
by the existing local evidence. Bilifan guarantees its exported quality fields,
not that the receiving knowledge base interprets them. History is not rewritten
in bulk when the application or quality rules change.

## Execution, Recovery, and Reuse

The JSON v2 ledger has one writer, atomic replacement, and a last-valid backup.
Unreadable or unwritable state stops dispatch visibly instead of becoming an
empty queue. A shared execution lock permits at most one computation per output
root, including CLI operations. CLI reports a busy resource; Web tasks wait and
continue automatically when it is released.

Pausing stops later dispatch, not the active computation. Waiting tasks cancel
immediately. Running tasks remain `canceling` until computation has stopped;
a late cancellation can finish as success if publication already completed.
The supervisor checks execution identity and descendants, and preserves the
execution claim when termination cannot be confirmed.

After restart, unpaused waiting tasks continue. Interrupted tasks keep their
run binding, originals, and available recovery actions, and require explicit
resumption. Durable run bindings and matching completion evidence close the
IPC and status-write gaps; an already published result must not be generated
again. Historical terminal records retain their original delivery profile.

Valid article blocks are saved outside retry workspaces and reused after a
failure, cancellation, or restart. Keys cover the current source text, actual
prompt, provider/model, and validation-rule versions. Force regeneration starts
a fresh cache generation; ordinary recovery resumes that generation's completed
blocks. Cache reuse is not quality approval. Attempt metrics record processing,
model calls, failures, cache reuse, and available token usage; unknown usage
stays unknown. Queue timestamps keep waiting time separate. Caches, metrics, and
process-control files are not customer deliverables or knowledge-base exports.

## Feishu Boundary

A Feishu intake batch is the set of supported URLs extracted from one message.
Items enter the same queue sequentially, with their source information and
idempotency keys retained. Hermes owns the gateway hook and immediate chat
acknowledgement; Bilifan owns processing and Web-visible task state.

The prior authorization for messages to the dedicated Feishu app covers local
processing and completion notifications to the same conversation. This release
adds no chat commands, short-link support, or notification delivery. That intake
authorization does not itself authorize Hermes configuration, credentials,
service restarts, external publishing, or cross-project changes.

## Transcription Routing

Explicit language selection takes precedence. Metadata URLs, inline/fenced
code, and command snippets including shell continuations are not strong evidence
of spoken English. Recorded routing signals must explain the selected route.

Whisper may make at most one automatic retry using an alternate language/model
route when the first result appears wrong. A corrected result retains that
history. English-looking output alone cannot resolve conflicting Chinese
metadata; unresolved evidence stays visible for review. Neither short-audio
prechecks nor an additional AI review pass are enabled by default.
