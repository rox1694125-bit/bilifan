# Bilifan

Bilifan is a local Bilibili video learning-note generator.

The current implementation is a first-stage local MVP. It accepts one Bilibili
video URL, processes only the current P, downloads audio, builds a transcript,
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
  --llm-provider codex-exec \
  --llm-model gpt-5.5 \
  --yes-i-understand \
  --out ./outputs
```

Useful flags:

- `--force-whisper`: skip Bilibili subtitles and force local Whisper.
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
        chunks.json
        partial_summaries/
          chunk_001.json
        chapters.json
        report.html
        report.pdf
```

The command prints a relative run path such as:

```text
Prepared Bilifan run: BV..._p2/runs/<timestamp>
```

`report.html` is the success artifact. `report.pdf` is best effort unless
`--require-pdf` is passed.

## Local Web UI

Start the local Web UI with:

```bash
python -m bilifan serve --no-open
```

By default `bilifan serve` binds only to `127.0.0.1`, uses `./outputs` as the
fixed history/output directory, generates a one-time access token, and prints a
URL like:

```text
http://127.0.0.1:8765/?token=<token>
```

Open that URL in your browser. Without `--no-open`, the CLI will try to open it
automatically with your local default browser.

Current MVP boundaries:

- Web UI access is protected by the printed token in the URL.
- The server only supports local `127.0.0.1` binding in this MVP.
- Web UI job outputs are always read from and written to `./outputs`.
- The Web UI does not support entering cookies.
- The CLI still supports `--cookies-file` and `--cookies-from-browser` for
  local runs.

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
