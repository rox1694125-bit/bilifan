# Bilifan Web UI MVP Design

## Goal

Add a local Web UI for Bilifan so a user can start one Bilibili video summary job from a browser instead of typing the full Terminal command.

The UI is a local workbench, not a hosted service and not a desktop app. It should preserve the current MVP boundary: one URL, current P only, local processing, Codex-backed summarization, offline `report.html`, and best-effort `report.pdf`.

## Confirmed Decisions

- Startup: `bilifan serve`.
- Browser behavior: automatically open the local page after server startup.
- Server bind: `127.0.0.1` only.
- Security: startup generates a random token; browser URL includes it and API requests must include it.
- Backend framework: FastAPI + uvicorn.
- Pipeline integration: extract the existing CLI summary flow into a shared Python pipeline function; CLI and Web UI both call it.
- Job concurrency: one running job at a time.
- Progress: stage-level progress, polled every 1 second.
- Task recovery: page refresh can restore the in-memory current job while the server process is alive; service restart does not recover unfinished jobs.
- History: simple latest-report list, reading `outputs/*/latest.json`; one latest run per video.
- Cookies: not exposed in Web UI MVP. CLI keeps cookies support.
- Output directory: fixed to `./outputs` for Web UI MVP.
- Settings exposed in UI: URL, output format, force Whisper, require PDF, allow long video.
- Cancel: not in MVP.
- Layout: compact workbench with history on the left and current task on the right.
- Report opening: open `report.html`, `report.pdf`, diagnostics, and file list through local service routes in a new browser tab.
- Failure display: failed stage, sanitized error summary, diagnostics link.

## Non-Goals

- Hosted deployment.
- User accounts, login, or password auth.
- LAN access.
- Batch queue or parallel jobs.
- Task cancellation.
- Cookies input in Web UI.
- Changing output directory from Web UI.
- Full logs or raw subprocess output in UI.
- Finder integration or OS-level "open folder" actions.
- Embedded report preview.
- Editing generated reports.

## User Flow

1. User runs:

   ```bash
   bilifan serve
   ```

2. Bilifan starts a local server on `127.0.0.1`. Default preferred port is `8765`; if unavailable, choose the next available port.
3. Bilifan opens:

   ```text
   http://127.0.0.1:<port>/?token=<random-token>
   ```

   If automatic browser opening fails, the command prints the same URL.

4. User confirms local processing/Codex consent if not already accepted.
5. User pastes a public Bilibili URL.
6. User selects basic settings:
   - HTML only or HTML + PDF.
   - Force Whisper.
   - Require PDF.
   - Allow long video.
7. User clicks start.
8. UI shows progress through:
   - `preflight`
   - `metadata`
   - `audio`
   - `transcript`
   - `chunking`
   - `summarization`
   - `render`
9. On success, UI links to `report.html`, optional `report.pdf`, diagnostics, and file list.
10. On failure, UI shows failed stage, sanitized message, and diagnostics link.

## UI Design

The first screen is the app workbench, not a landing page.

### Left Panel: History

Reads latest runs from `outputs/*/latest.json`.

Display each item with:

- output id, for example `BV1xx_p1`.
- title if available from `metadata.json`.
- run timestamp.
- status derived from `diagnostics.json`.
- links for successful artifacts when present.

MVP only shows the latest run for each output id. It does not show all historical runs.

### Right Panel: Current Task

Contains:

- URL input.
- Format selector:
  - `html`
  - `html,pdf`
- Toggles:
  - Force Whisper.
  - Require PDF.
  - Allow long video.
- Start button.
- Consent banner if local processing consent is missing.
- Stage progress list.
- Result links.
- Failure summary.

The UI should be quiet and utilitarian: dense enough for repeated use, with clear status and predictable controls.

## API Design

All API endpoints require the startup token. The frontend may send it as an `X-Bilifan-Token` header. Direct file links may include the token query parameter because they open in a new tab.

### `GET /`

Returns the Web UI HTML. The page reads `token` from the URL and stores it in memory for API requests.

### `GET /api/config`

Returns:

```json
{
  "consent": {
    "local_processing": true
  },
  "defaults": {
    "format": "html,pdf",
    "force_whisper": false,
    "require_pdf": false,
    "allow_long_video": false
  }
}
```

### `POST /api/consent`

Writes the same local processing consent used by CLI. Web UI does not support cookies consent because cookies input is out of scope.

### `GET /api/history`

Returns latest runs:

```json
{
  "items": [
    {
      "run_key": "BV1xx_p1/runs/2026-06-08_120000",
      "output_id": "BV1xx_p1",
      "title": "Video title",
      "status": "succeeded",
      "stage": "render",
      "generated_at": "2026-06-08T12:00:00+00:00",
      "artifacts": {
        "html": "/api/runs/.../files/report.html?token=...",
        "pdf": "/api/runs/.../files/report.pdf?token=...",
        "diagnostics": "/api/runs/.../files/diagnostics.json?token=..."
      }
    }
  ]
}
```

### `POST /api/jobs`

Starts a job. If another job is running, return `409`.

Request:

```json
{
  "url": "https://www.bilibili.com/video/BV...?p=1",
  "format": "html,pdf",
  "force_whisper": false,
  "require_pdf": false,
  "allow_long_video": false
}
```

Response:

```json
{
  "job_id": "uuid",
  "status": "running"
}
```

### `GET /api/jobs/current`

Returns current in-memory job state, or idle:

```json
{
  "status": "running",
  "stage": "transcript",
  "message": "Transcribing audio.",
  "progress": [
    {"stage": "metadata", "status": "done"},
    {"stage": "audio", "status": "done"},
    {"stage": "transcript", "status": "running"},
    {"stage": "chunking", "status": "pending"},
    {"stage": "summarization", "status": "pending"},
    {"stage": "render", "status": "pending"}
  ],
  "run_key": "BV1xx_p1/runs/2026-06-08_120000",
  "artifacts": {}
}
```

### `GET /api/runs/{output_id}/runs/{run_id}/files`

Returns a file list for a run. Only include whitelisted files that exist.

### `GET /api/runs/{output_id}/runs/{run_id}/files/{file_path:path}`

Serves a whitelisted artifact from the run directory.

Allowed paths:

- `metadata.json`
- `transcript.json`
- `chunks.json`
- `chapters.json`
- `diagnostics.json`
- `report.html`
- `report.pdf`
- `partial_summaries/*.json`

The server must reject absolute paths, `..`, path traversal, backslashes, and files outside `outputs/`.

## Pipeline Refactor

Move the existing `summarize` command flow from `cli.py` into a shared module, likely `src/bilifan/pipeline.py`.

Suggested types:

```python
@dataclass(frozen=True)
class PipelineRequest:
    url: str
    out: Path
    output_format: str
    transcriber: str
    force_whisper: bool
    llm_provider: str
    llm_model: str
    require_pdf: bool
    allow_long_video: bool
    yes_i_understand: bool
    overwrite: bool
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None

@dataclass(frozen=True)
class PipelineResult:
    run_key: str
    run_dir: Path
    diagnostics_path: Path
    artifact_paths: list[str]
    warnings: list[str]
```

Progress callback:

```python
ProgressCallback = Callable[[str, str, str], None]
```

Where arguments are:

- stage
- status: `pending`, `running`, `done`, `failed`
- sanitized message

The CLI should keep its existing behavior and output, but delegate to the pipeline. This keeps CLI and Web UI behavior consistent.

## Job Runner

Add a small in-memory job manager.

Rules:

- Only one job can be `running`.
- Completed or failed job remains available as current job until another job starts or server exits.
- Job state is protected by a lock.
- Worker runs in a background thread.
- Worker catches known pipeline exceptions and stores sanitized failure state.
- Worker does not expose raw stderr/stdout.

MVP does not support cancellation. A second `POST /api/jobs` while running returns `409`.

## Security

The server runs only on `127.0.0.1`.

The startup token is random per server process and not persisted. It protects API calls from accidental cross-origin localhost requests.

Token validation applies to:

- all `/api/*` routes;
- report/file routes.

The Web UI does not accept cookies. It does not expose arbitrary local paths. It does not call Finder or OS open commands from the server.

File serving must be rooted under the configured Web UI output directory, fixed to `./outputs` for MVP.

`./outputs` is resolved relative to the current working directory where `bilifan serve` was started.

## Consent

The Web UI reuses existing Bilifan local processing consent.

If missing, the UI displays a concise notice:

```text
Bilifan downloads current-P audio, may run local Whisper, and uses your configured Codex CLI to summarize transcript chunks. Transcript text may be sent to the model service behind that Codex account.
```

The user must accept once before starting a job. Acceptance writes the same config used by CLI. The UI does not show cookies consent because cookies are not supported in Web UI MVP.

## Testing

Unit and integration tests should cover:

- Existing CLI tests still pass after pipeline extraction.
- `PipelineRequest` produces the same artifacts as CLI behavior in mocked tests.
- `bilifan serve` command exists and starts with host `127.0.0.1`.
- Token required for API routes.
- `GET /api/config` reports consent/defaults.
- `POST /api/consent` writes local processing consent.
- `GET /api/history` reads `outputs/*/latest.json` and ignores invalid runs.
- `POST /api/jobs` starts one job.
- Second `POST /api/jobs` while running returns `409`.
- `GET /api/jobs/current` returns stage progress.
- Successful worker state includes artifact links.
- Failed worker state includes failed stage, sanitized message, and diagnostics link.
- File routes only serve whitelisted run artifacts.
- Path traversal attempts are rejected.
- UI HTML includes URL input, basic settings, history area, stage list, result links, and polling script.

Manual smoke:

1. Run `bilifan serve`.
2. Browser opens automatically.
3. Accept consent.
4. Submit a short public Bilibili URL.
5. Watch stage progress update.
6. Open `report.html`.
7. Open `report.pdf` if generated.
8. Confirm history shows the latest run.

## Acceptance Criteria

- `bilifan summarize` remains compatible with existing usage.
- `bilifan serve` starts a local Web UI and opens the browser.
- The Web UI can start one public Bilibili URL summary job.
- The UI displays stage-level progress.
- The UI blocks a second simultaneous job with a clear message.
- The UI shows success artifact links.
- The UI shows failed stage, sanitized summary, and diagnostics link on failure.
- The UI reads simple history from `outputs/*/latest.json`.
- File routes cannot read outside `outputs/`.
- Cookies are not available from Web UI.
- Output directory is fixed to `./outputs`.
- No cancel button exists in MVP.
- Full tests pass.
