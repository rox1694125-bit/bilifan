# Bilifan Export, Language, and Folder Actions Design

## Goal

Improve the local Bilifan MVP after the first successful real-video tests by adding user-friendly transcript exports, better Whisper language selection, and a Web UI action to open each run's local output folder.

This design intentionally stays within the current local-workbench boundary: one Bilibili URL, current P only, local media/transcription, Codex-backed summarization, offline reports, and token-protected local Web UI.

## Confirmed Decisions

- Implement the lightweight export-layer approach, not a full artifact registry.
- Add `src/bilifan/exports.py` for user-facing file generation.
- Generate:
  - `transcript.txt`
  - `transcript.srt`
  - `notes.md`
- Keep `transcript.json` and `chapters.json` as stable structured intermediates.
- For English videos, transcript exports keep the source-language transcript; summaries and notes remain Chinese learning notes.
- Add `language = auto | zh | en` to CLI and Web UI.
- Language selection only affects Whisper fallback. Bilibili subtitles remain preferred when available unless `Force Whisper` is enabled.
- Web UI shows new artifact links in each run card.
- Web UI adds `打开本地文件夹` for successful and failed runs.
- Folder opening supports macOS only in this slice.
- Folder opening uses `output_id + run_id`, never an arbitrary frontend-supplied path.
- No productized historical backfill button.
- After implementation, run one one-off local backfill for the existing local history under `outputs/`.

## Non-Goals

- Batch queue management.
- Hosted or LAN access.
- Cross-platform folder opening.
- `vtt`, `docx`, translated transcript exports, or bilingual transcript exports.
- Re-running from existing artifacts.
- Full artifact registry abstraction.
- Web UI preview/editor for transcript or notes.
- Automatic historical backfill on every `bilifan serve` startup.

## Architecture

### Export Module

Add `src/bilifan/exports.py`.

Responsibilities:

- Convert `transcript.json` data to `transcript.txt`.
- Convert `transcript.json` data to `transcript.srt`.
- Convert `metadata.json + chapters.json` data to `notes.md`.
- Return relative artifact names for pipeline diagnostics and Web UI links.

It should not:

- Download media.
- Call Whisper.
- Call Codex.
- Read or write arbitrary directories.
- Own Web UI routing.

### Pipeline Integration

The pipeline writes export files as early as possible:

1. After transcript succeeds:
   - `transcript.json`
   - `transcript.txt`
   - `transcript.srt`

2. After summarization succeeds:
   - `chapters.json`
   - `notes.md`

3. After rendering succeeds:
   - `report.html`
   - `report.pdf` if requested and Chrome export succeeds.

If summarization or rendering later fails, earlier transcript exports remain available and should appear in `artifact_paths`.

## Export Formats

### `transcript.txt`

Plain UTF-8 text.

Recommended structure:

```text
视频标题
URL: https://www.bilibili.com/video/...
Source: whisper
Model: turbo
Language: zh

[00:00] 第一段文字
[00:02] 第二段文字
```

For English audio, keep English transcript text.

### `transcript.srt`

SubRip UTF-8 subtitle file.

Each cue uses:

```text
1
00:00:00,000 --> 00:00:02,180
Hello 大家好

2
00:00:02,180 --> 00:00:04,200
下一段
```

Time format is `HH:MM:SS,mmm --> HH:MM:SS,mmm`.

### `notes.md`

Markdown learning note generated from metadata and chapters.

Recommended structure:

```markdown
# 视频标题

- UP:
- 当前 P:
- 时长:
- 转写来源:
- 原视频:

## 总摘要

## 目录

## 1. 章节标题

时间戳: 0:00
链接: https://www.bilibili.com/video/...

### 摘要

### 要点

- ...

### 关键引用

> ...

### 视觉锚点

- ...
```

Use basic Markdown headings, lists, links, and blockquotes so the file works well in Obsidian, GitHub, Notion imports, and ordinary editors.

## Language Strategy

### Public Interface

CLI:

```bash
bilifan summarize <url> --language auto
bilifan summarize <url> --language zh
bilifan summarize <url> --language en
```

Web UI:

- Add a visible `语言` select.
- Options:
  - `auto`
  - `中文`
  - `英文`
- Default: `auto`.
- Hint text: `只影响 Whisper；已有字幕默认优先使用。`

### Behavior

- `transcriber=auto` plus usable Bilibili subtitle: use subtitle first.
- `Force Whisper` or no usable subtitle: choose Whisper model by `language`.
- `language=zh`: use Whisper `turbo` and language `zh`.
- `language=en`: use Whisper `small.en` and language `en`.
- `language=auto`: inspect metadata to choose.

Auto detection inputs:

- `part_title`
- `title`
- `description`
- `tags`
- subtitle language metadata if present but Whisper is still required

English signals should include obvious mixed-language metadata seen in real tests, such as:

- `英语原声`
- `英文`
- `English`
- English-heavy title/description text
- common English-course/person signals such as `Andrew Ng`

Keep the existing ASCII-letter ratio rule as one signal, but do not rely on it exclusively because Bilibili titles often contain Chinese translations for English videos.

## Web UI

### Artifact Links

Each run card displays all available artifacts.

Successful run example:

```text
HTML  PDF  TXT  SRT  MD  diagnostics  file list  打开本地文件夹
```

Failed run example:

```text
diagnostics  file list  打开本地文件夹
```

Late-stage failed run example:

```text
TXT  SRT  diagnostics  file list  打开本地文件夹
```

The history panel and current-job result area should use the same artifact-link shape.

### Open Folder Endpoint

Add:

```text
POST /api/runs/{output_id}/runs/{run_id}/open-folder
```

Security rules:

- Require the existing Web UI token.
- Accept only `output_id` and `run_id`.
- Resolve server-side to `outputs/<output_id>/runs/<run_id>`.
- Require the directory to exist.
- Resolve symlinks and confirm the final path remains under the configured Bilifan `outputs/` root.
- Do not accept arbitrary paths or query-string paths.
- On macOS, call `open <run_dir>`.
- On non-macOS, return a clear unsupported-platform error.

This action should be available for both successful and failed runs.

## Error Handling

- Export failures should not discard already generated core artifacts.
- If transcript exports fail after `transcript.json` is written, write diagnostics warning `transcript_export_failed`.
- If `notes.md` export fails after `chapters.json` is written, write diagnostics warning `notes_export_failed`.
- Folder opening failures return an API error and do not mutate the run.
- Existing sanitization rules still apply to diagnostics.

## Historical Backfill

Do not add a UI button or server-startup automation for historical backfill.

After implementation, run a one-off local backfill for current `outputs/`:

- If `transcript.json` exists, generate missing `transcript.txt` and `transcript.srt`.
- If `metadata.json` and `chapters.json` exist, generate missing `notes.md`.
- Skip existing files.
- Skip runs missing required inputs.
- Report a short summary to the user.

This is an operational step for this development round, not a permanent product feature.

## Testing

### Unit Tests

- `transcript.txt` formatting.
- `transcript.srt` cue numbering and timestamp formatting.
- `notes.md` metadata, chapter, list, quote, and timestamp-link formatting.
- `language=auto|zh|en` model selection.
- English metadata examples including `英语原声` and mixed Chinese/English titles.
- Folder-open path validation rejects traversal and symlink escape.

### Pipeline Tests

- Transcript-stage success writes `transcript.json`, `transcript.txt`, and `transcript.srt`.
- Summarization success writes `chapters.json` and `notes.md`.
- Summarization failure after transcript still exposes transcript exports in diagnostics/artifacts.
- Render success still includes existing HTML/PDF behavior.

### Web Tests

- `GET /api/history` includes `txt`, `srt`, `md`, and folder action metadata when files exist.
- Current job result includes the new artifact links.
- Open-folder endpoint requires token.
- Open-folder endpoint opens only real run directories.
- Unsupported platform returns a clear error.
- Web UI renders the language select and artifact/folder actions.

### Verification

- Run full pytest suite.
- Run one real sample with `language=auto` Chinese.
- Run one real or existing English sample with `language=en` or auto-detected English.
- One-off backfill current local history and confirm expected files appear.

## References

- SRT/SubRip uses sequential cues and `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamps.
  Reference: https://subtitleedit.github.io/subtitleedit/reference/subrip.html
- OpenAI Whisper supports multilingual and English-only model variants such as `small.en`.
  Reference: https://github.com/openai/whisper
- macOS `open` opens files, directories, or URLs similarly to double-clicking them.
  Reference: https://www.unix.com/man_page/osx/1/open/
- Basic Markdown syntax includes headings, lists, links, and blockquotes.
  Reference: https://www.markdownguide.org/basic-syntax/
