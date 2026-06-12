# Bilifan

Bilifan is a local Bilibili video learning-note generator.

The current implementation is a first-stage local MVP. It accepts one Bilibili
or YouTube public video URL, processes only the current P/video, downloads audio, builds a transcript,
chunks the transcript, asks `codex exec` for structured learning-note chapters,
and renders an offline `report.html`. If Chrome is available it also tries to
export `report.pdf`.

## Boundaries

- Bilifan runs locally and processes only URLs you provide.
- Bilifan does not provide a hosted scraping service.
- Bilifan does not include Bilibili cookies.
- Bilifan does not bypass login, payment, region, risk-control, DRM, or access controls.
- You are responsible for having permission to access and summarize the content.
- If you provide cookies, they must only be used locally for content your account can already view.
- Codex-backed summarization sends transcript chunks to the model service configured in your local Codex environment.
- First-stage MVP does not generate SVG diagrams, extract video screenshots, or run a batch queue.

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

This creates a run directory like:

```text
outputs/
  BV..._p2/
    latest.json
    runs/
      <timestamp>/
        diagnostics.json
        metadata.json
        transcript.json
        transcript.txt
        transcript.srt
        chunks.json
        partial_summaries/
          chunk_001.json
        chapters.json
        notes.md
        report.html
        report.pdf
        content_bundle.json
        media/
          audio.mp3
```

The command prints a relative run path such as:

```text
Prepared Bilifan run: BV..._p2/runs/<timestamp>
```

`report.html` is the success artifact. `report.pdf` is best effort unless
`--require-pdf` is passed. Successful transcript and summarization stages may
also write `transcript.txt`, `transcript.srt`, and `notes.md` for easier reading
or reuse outside Bilifan. Successful runs also publish the final audio as
`media/audio.mp3`; incomplete runs keep intermediate audio under the hidden
`.bilifan/cache/` directory.

## Content Bundle

Successful runs write `content_bundle.json`. This is the stable integration
artifact for downstream tools such as Nabaichuan. It contains source metadata,
chapter summaries, transcript segments, artifact links, and provenance without
local absolute paths.

## Retry

Use retry to regenerate downstream artifacts without downloading audio or
rerunning Whisper:

```bash
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from bundle
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from render
python -m bilifan retry outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000 --from summarization
```

Supported retry stages are `bundle`, `render`, and `summarization`.

## YouTube Scope

YouTube support is limited to public ordinary videos with `youtube.com/watch`
or `youtu.be` URLs. Bilifan prefers subtitles and falls back to Whisper when
needed. Playlists, private videos, members-only videos, age-restricted videos,
cookies, live streams, and Shorts-specific behavior are outside this phase.

## Nabaichuan

See `docs/nabaichuan-integration.md` for the bundle mapping and JSONL converter:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan.jsonl
```

## Local Web UI

Start the local Web UI with:

```bash
python -m bilifan serve --no-open
```

By default `bilifan serve` binds only to `127.0.0.1`, uses `./outputs` as the
fixed history/output directory, generates a one-time access token, and prints a
URL like:

```text
http://127.0.0.1:8765/
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
  served page; treat the server as local-only and do not expose it on a shared
  network.
- The server only supports local `127.0.0.1` binding in this MVP.
- Web UI job outputs are always read from and written to `./outputs`.
- The Web UI can show HTML/PDF/TXT/SRT/MD/Bundle/audio export links and can ask
  macOS to open a run's local folder.
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
