# Bilifan

Bilifan is a local Bilibili video learning-note generator.

The current implementation is a local MVP. It accepts Bilibili or YouTube public
video URLs, processes only the current P/video, prefers platform subtitles,
downloads audio only when Whisper is needed, chunks the transcript, asks
`codex exec` for a cleaned transcript article and structured learning-note
chapters, and renders offline `transcript.html` and `report.html`. If Chrome is
available it also tries to export `transcript.pdf` and `report.pdf`.

## Boundaries

- Bilifan runs locally and processes only URLs you provide.
- Bilifan does not provide a hosted scraping service.
- Bilifan does not include Bilibili cookies.
- Bilifan does not bypass login, payment, region, risk-control, DRM, or access controls.
- You are responsible for having permission to access and summarize the content.
- If you provide cookies, they must only be used locally for content your account can already view.
- Codex-backed article generation and summarization send transcript/article
  content to the model service configured in your local Codex environment.
- SVG diagrams and frame screenshots are experimental helpers, not stable
  evidence. The Web UI includes a local sequential task center for batch jobs.

## Usage

From an installed package:

```bash
python -m bilifan summarize "https://www.bilibili.com/video/BV...?p=2" \
  --yes-i-understand \
  --out ./outputs
```

From a source checkout without installing the package:

```bash
PYTHONPATH=src python -m bilifan summarize "https://www.bilibili.com/video/BV...?p=2" \
  --yes-i-understand \
  --out ./outputs
```

Common options:

```bash
python -m bilifan summarize "https://www.bilibili.com/video/BV...?p=1" \
  --format html,pdf \
  --transcriber auto \
  --language auto \
  --llm-provider codex-exec \
  --llm-model gpt-5.5 \
  --yes-i-understand \
  --out ./outputs
```

Useful flags:

- `--force-whisper`: skip Bilibili subtitles and force local Whisper.
- `--language auto|zh|en`: control Whisper fallback language/model selection. Bilibili subtitles are still preferred unless `--force-whisper` is used.
- `--require-pdf`: return non-zero if Chrome cannot export PDF.
- `--allow-long-video`: allow videos longer than 180 minutes.
- `--cookies-file` / `--cookies-from-browser`: pass cookies to `yt-dlp`; Bilifan does not store the cookie file name in reports or config.
- `--overwrite`: replace a run if the timestamp collides.

Known video duration is checked immediately after metadata, before subtitles,
audio download, Whisper, or AI generation. Videos over 180 minutes require
`--allow-long-video` (Web: Advanced settings → allow long videos). Videos from
90 through 180 minutes retain the existing explicit confirmation behavior;
`--yes-i-understand` supplies that confirmation. The chunking stage also checks
the measured audio duration when audio was downloaded. On the subtitle-only
path it uses metadata duration, or the last subtitle timestamp if duration is
missing. Incorrect metadata on a subtitle-only run is not independently
verified by this duration gate.
For an old over-limit failure, change the option and submit the URL again:
the queue's requeue action retains the original options.

This creates a run directory like:

```text
outputs/
  BV..._p2/
    latest.json
    runs/
      <timestamp>/
        transcript.html
        report.html
        transcript.pdf
        report.pdf
        content_bundle.json        # hidden machine contract
        metadata.json              # hidden internal
        transcript.json            # hidden raw transcript
        transcript_article.json    # hidden article source
        chunks.json                # hidden internal
        chapters.json              # hidden report summary
        diagnostics.json           # hidden internal
        media/
          audio.mp3        # present only when audio was needed
```

The command prints a relative run path such as:

```text
Prepared Bilifan run: BV..._p2/runs/<timestamp>
```

`transcript.html` is the cleaned transcript article for reading. `report.html`
is the main report. `transcript.pdf` and `report.pdf` are best effort unless
`--require-pdf` is passed. Internal JSON files remain in the run directory for
debugging and retry, but ordinary Web result cards only show the two HTML files,
the available PDFs, and the local folder entry.

## Content Bundle

Successful runs write `content_bundle.json`.
`content_bundle.json` is the stable integration artifact for downstream tools.
It contains source metadata, the cleaned transcript article, chapter summaries,
transcript provenance, artifact links, and provenance without local absolute
paths. `nabaichuan.jsonl` is produced only by explicit single-run or batch export
from that bundle, not by every successful run.

## Retry

Use retry to regenerate downstream artifacts without downloading audio or
rerunning Whisper:

```bash
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from bundle
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from render
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from summarization
```

Supported retry stages are `bundle`, `render`, and `summarization`.

Retries generate in an isolated copy of the run. If generation fails, the
previous article, report, PDFs, bundle, and successful diagnostics remain
unchanged. The latest failed retry is recorded separately in
`retry_diagnostics.json`; the Web task shows the failed attempt while history
continues to offer the previous delivery. A successful retry replaces the run's
artifact set, preserving its run key and history pointer. Previously exported
`nabaichuan.jsonl` is invalidated; export again to obtain the updated content.
HTML-only or best-effort PDF failures never reuse PDFs from the previous result.

The isolated copy temporarily needs additional disk space. Retries of the same
run are serialized on macOS/Linux and runs containing symbolic links are
rejected. Publication uses two same-filesystem directory renames and rolls back
ordinary failures. It is not a crash-atomic exchange: an interruption between
the renames may leave the original in `runs/.<run_id>.backup-<id>`. Keep that
backup for recovery; do not create a new directory over the missing run or
delete the backup. This recovery protects prior results without downloading
audio or repeating Whisper.

## YouTube Scope

YouTube support is limited to public ordinary videos with `youtube.com/watch`
or `youtu.be` URLs. Bilifan prefers subtitles and falls back to Whisper when
needed. Playlists, private videos, members-only videos, age-restricted videos,
cookies, live streams, and Shorts-specific behavior are outside this phase.

## Nabaichuan

CLI and Web UI runs do not automatically generate `nabaichuan.jsonl`. Use the
single-run or batch export action when you need a ready-to-import JSONL file.
Bilifan does not write directly into Nabaichuan or any other external system.

See `docs/nabaichuan-integration.md` for the record schema and manual JSONL
converter:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan.jsonl
```

Transcript records are included by default. `--include-transcript` remains
accepted for older commands, and `--no-transcript` omits transcript records.

## Local Web UI

Start the local Web UI with:

```bash
python -m bilifan serve --no-open
```

By default `bilifan serve` binds only to `127.0.0.1`, uses `./outputs` as the
fixed history/output directory, generates a one-time access token, and prints a
URL like:

```text
Local URL: http://127.0.0.1:8765/
```

Open that URL in your browser. The HTML page embeds the current local token and
uses it for API calls; API routes remain token-protected against stale pages and
unauthenticated API calls. This is a local workbench guard, not a security
boundary against other processes on the same machine that can read
`http://127.0.0.1:<port>/`. If you keep an old browser tab after restarting the
server, that tab will stop polling once its old token is rejected. Without
`--no-open`, the CLI will try to open the fixed entry URL automatically with your
local default browser.

Current MVP boundaries:

- Web UI API access is protected by a per-server local token embedded in the
  served page; for remote use, put Cloudflare Access in front of the local
  server instead of binding Bilifan directly to a public interface.
- The server intentionally supports only local `127.0.0.1` binding. Remote
  access should be provided by a tunnel or private network that forwards to the
  local server.
- Web UI job outputs are always read from and written to `./outputs`.
- The Web UI shows the cleaned transcript article, main report, available PDFs,
  and can ask macOS to open a run's local folder. Machine-readable artifacts are
  hidden from ordinary result cards but remain available through token-protected
  direct file access.
- The Web UI can export a single successful run to `nabaichuan.jsonl` and
  batch-export all successful history runs to a local JSONL file plus a
  `.report.json` summary.
- The Web UI can cancel the current task cooperatively. If a subprocess is
  currently downloading, transcribing, or summarizing, cancellation is applied at
  the next safe stage boundary.
- The Web UI can retry downstream failed runs from `summarization`, `render`, or
  `bundle` without redownloading audio or rerunning Whisper.
- The Web UI does not support entering cookies.
- The CLI still supports `--cookies-file` and `--cookies-from-browser` for
  local runs.

中文快速开始：

```bash
cd /path/to/bilifan
.venv/bin/python -m bilifan serve --no-open --port 8792
```

然后打开 Terminal 打印的固定地址，例如 `http://127.0.0.1:8792/`。输出文件在
`./outputs`，每个视频的最新成功结果会显示在左侧历史记录里。

## Cloudflare Remote Access

For remote access from other computers, keep Bilifan local and expose it through
Cloudflare Tunnel plus Cloudflare Access:

```bash
cd /Volumes/mySSD/projects/bilifan
scripts/bilifan-remote.sh restart
```

Default public URL:

```text
https://bilifan.buyaoting.top
```

See `docs/remote-access-cloudflare.md` for the required Cloudflare Tunnel, DNS,
and Access configuration. Do not expose Bilifan by router port forwarding or
`--host 0.0.0.0`.

Daily remote commands:

```bash
scripts/bilifan-remote.sh status
scripts/bilifan-remote.sh logs
scripts/bilifan-remote.sh stop
```

## Runtime Requirements

- Python 3.11+
- `yt-dlp`
- `ffmpeg` and `ffprobe`
- `openai-whisper` for local fallback transcription
- Codex CLI authenticated in the local environment
- Chrome for PDF export

Project dependencies are declared in `pyproject.toml` and can be installed with
`uv sync --extra dev`.

## Verification

Unit tests:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Live metadata smoke for the three public test URLs:

```bash
BILIFAN_METADATA_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -p no:cacheprovider tests/test_metadata_smoke.py -q
```

End-to-end smoke uses the real network, Bilibili, Whisper/Codex if needed, and
Chrome PDF export. Prefer a short public video first.
