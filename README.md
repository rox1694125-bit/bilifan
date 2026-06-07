# Bilifan

Bilifan is a local Bilibili video learning-note generator.

The current implementation is an early foundation slice. It prepares a local run
directory for one Bilibili current-P URL, records consent in your user config
directory, and writes sanitized diagnostics. It does not yet download media,
transcribe audio, call Codex, or render HTML/PDF reports.

## Boundaries

- Bilifan runs locally and processes only URLs you provide.
- Bilifan does not provide a hosted scraping service.
- Bilifan does not include Bilibili cookies.
- Bilifan does not bypass login, payment, region, risk-control, DRM, or access controls.
- You are responsible for having permission to access and summarize the content.
- If you provide cookies in future versions, they must only be used locally for content your account can already view.
- Future Codex-backed summarization may send transcript text to the model service configured in your local Codex environment.

## First Slice Usage

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

This creates:

```text
outputs/
  BV..._p2/
    latest.json
    runs/
      <timestamp>/
        diagnostics.json
```

The command prints a relative run path such as:

```text
Prepared Bilifan run: BV..._p2/runs/<timestamp>
```

## Not Implemented Yet

- `yt-dlp` metadata extraction.
- Audio download.
- Whisper transcription.
- `codex exec` summarization.
- HTML/PDF rendering.
