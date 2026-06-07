# Bilifan MVP Design

## 背景

Bilifan 是一个本地运行的 Bilibili 视频学习笔记生成器。目标不是做公开视频抓取服务，而是让用户在自己的电脑上、用自己有权访问的视频和账号权限，生成离线可读、可复查来源的学习报告。

第一版服务对象是作者本人和同类高级本地用户：他们可以接受本机已经安装或配置 Codex、`yt-dlp`、`ffmpeg`、Chrome headless 等依赖。公开项目 README 需要把这点写清楚，后续再把默认后端扩展成更通用的 OpenAI-compatible API。

MVP 只做一个窄闭环：

- 输入一个 Bilibili 视频 URL。
- 只处理 URL 指向的当前 P；URL 未指定 `p=` 时默认 P1。
- 获取当前 P 的元数据、封面、字幕和音频。
- 优先读取已有字幕，没有字幕时再用 Whisper 转写。
- 用本机 `codex exec` 生成结构化学习笔记 JSON。
- 输出离线 HTML，并尽量输出 PDF。
- 保留可复用中间文件和 provenance，便于调试、重跑和复查。

长图、真实视频截图、批量队列、Web UI、完整视频保存和高级动态 SVG 暂不进入默认 MVP。

## 用户边界

项目默认用于个人学习、研究和归档。公开项目需要明确：

- 不提供托管抓取服务。
- 不内置 Bilibili cookies。
- 不绕过登录、付费、地区、风控或 DRM 限制。
- 用户自行保证自己有权访问、处理和保存相关内容。
- 默认只处理用户显式传入的单个 URL 和当前 P，不做平台级批量抓取。
- 允许用户本机通过 cookies 处理自己账号已经有权访问的视频，但不承诺支持会员、付费或登录后可见视频。
- README 和 CLI 首次运行都要提示合规边界。

MVP 验收只使用公开公开视频，不使用会员、付费或登录后可见视频作为公开验收样例。

## 首次确认

CLI 首次运行或首次使用 cookies 时，需要用户确认本地处理和权限边界。确认文案保持短，不引入法律解释：

```text
Bilifan runs locally and processes only URLs you provide.
You are responsible for having permission to access and summarize the content.
Bilifan does not bypass access controls or store cookies in reports.
Continue? [y/N]
```

确认后写入本机配置，例如 `.bilifan/config.json`。自动化场景可用 `--yes-i-understand` 跳过交互确认。

## CLI 形态

MVP 提供一个 Python CLI：

```bash
bilifan summarize "https://www.bilibili.com/video/BV...?p=2" \
  --cookies-from-browser chrome \
  --format html,pdf \
  --llm-provider codex-exec \
  --out ./outputs
```

关键参数：

- `url`: 必填，单个 Bilibili 视频 URL，只处理当前 P。
- `--cookies-from-browser`: 可选，透传给 `yt-dlp`。
- `--cookies-file`: 可选，读取用户提供的 cookies 文件。
- `--format`: 可选，默认 `html,pdf`。
- `--out`: 可选，默认 `./outputs`。
- `--transcriber`: 可选，默认 `auto`，优先字幕，fallback 到本地 Whisper。
- `--force-whisper`: 可选，忽略已有字幕并重新转写。
- `--llm-provider`: 可选，MVP 默认 `codex-exec`。
- `--llm-model`: 可选，MVP 默认 `gpt-5.5`，允许用户覆盖。
- `--with-diagrams`: 可选，生成基础 SVG 图解。
- `--require-pdf`: 可选，PDF 失败时让命令返回非 0。
- `--allow-long-video`: 可选，允许处理超过 3 小时的视频。
- `--yes-i-understand`: 可选，跳过首次确认和长视频确认。
- `--overwrite`: 可选，覆盖当前 run 输出。
- `--debug-log`: 可选，保存脱敏策略之外的深度调试日志，默认关闭。

MVP 不支持本地音视频文件输入。本地文件会把产品边界扩大成通用视频总结器，后续可通过 `summarize-file` 单独设计。

## 输出结构

目录名使用稳定 ID，不使用视频标题。标题只写入报告和元数据：

```text
outputs/
  BV1xx_p2/
    latest.json
    runs/
      2026-06-08_011530/
        metadata.json
        transcript.json
        chunks.json
        partial_summaries/
          chunk_001.json
        chapters.json
        diagnostics.json
        report.html
        report.pdf
        assets/
          cover.jpg
          diagrams/
```

默认不覆盖旧 run。同一个 `BV_p` 重跑时创建新的时间戳目录，并更新 `latest.json`。只有用户显式传入 `--overwrite` 时，才覆盖当前 run。

默认保留这些中间文件：

- `metadata.json`
- `transcript.json`
- `chunks.json`
- `partial_summaries/*.json`
- `chapters.json`
- `diagnostics.json`

MVP 不保存完整视频。音频缓存默认放在工作目录下的 `.bilifan/cache/`，后续提供 `bilifan clean-cache` 清理。

## Provenance

每个 run 的 `metadata.json`、`chapters.json` 和报告末尾都记录 provenance：

- `bilifan_version`
- `generated_at`
- `input_url_sanitized`
- `video_id`
- `part_index`
- `cid`
- `title`
- `part_title`
- `owner_name`
- `yt_dlp_version`
- `ffmpeg_version`
- `transcript_source`
- `whisper_model`
- `llm_provider`
- `llm_model`
- `prompt_version`
- `chunking_strategy`

这些字段用于调试和结果复查。不要写入 cookies 内容、Codex token、完整本机用户路径或未脱敏的原始 URL。

## 模块设计

### `ingest`

职责：

- 调用 `yt-dlp` 获取当前 P 元数据。
- 保存标题、UP、当前 P 标题、分 P 列表、简介、标签、封面、时长、章节、字幕列表。
- 下载封面到 `assets/cover.jpg`。
- 生成干净的 Bilibili 时间戳链接基础信息：`BV`、`p`、`cid`。

约束：

- 只处理当前 P；不默认处理整个多 P 视频。
- 如果 URL 未指定 `p=`，默认处理 P1。
- 不在日志里打印 cookies。
- 遇到需要登录或权限不足时返回明确错误，不尝试绕过。
- 对登录后可见内容只做 best effort，不作为公开验收范围。

### `media`

职责：

- 下载当前 P 的最佳音频。
- 用 `ffprobe` 读取实际时长。
- 将音频标准化为 Whisper 友好的中间文件。

校验：

- `metadata.duration` 与 `ffprobe.duration` 差异超过 5% 时标记 `duration_mismatch`。
- 不自动无限重试。MVP 只重试 1 次，仍失败就终止并保留诊断信息。

长视频策略：

- `<= 90` 分钟：直接运行。
- `90-180` 分钟：交互模式提示预计耗时、分块数和可能的 Codex 用量，并询问是否继续。
- `> 180` 分钟：默认拒绝，除非用户传入 `--allow-long-video`。
- 自动化模式可用 `--yes-i-understand` 跳过确认。

### `transcript`

职责：

- 优先使用 Bilibili/yt-dlp 提供的字幕。
- 没有字幕时调用本地 Whisper。
- 用户传入 `--force-whisper` 时忽略已有字幕并重新转写。
- 输出 segment 级时间戳、文本、语言、来源。

模型策略：

- 中文默认 `turbo` + `language=Chinese`。
- 英文默认 `small.en` 转写，再交给总结阶段翻译成中文。
- 不用 `turbo` 做翻译任务。

校验：

- 最后一个 segment 的结束时间与音频时长接近。
- 差异超过阈值时标记 `transcript_incomplete`，报告中展示警告。
- `transcript_source` 必须写入 provenance，取值例如 `bilibili_subtitle`、`whisper`。

### `chunk`

职责：

- 将 transcript 切成可稳定交给 Codex 的上下文块。
- 记录每个 chunk 的 segment 范围、起止时间、估算 token、文本来源。

策略：

- `<= 45` 分钟的视频优先单次 summary pass。
- `45-180` 分钟的视频按动态 chunk 处理，默认每块约 30-45 分钟。
- chunk 不按分钟硬切，最终以 token budget 兜底。
- 访谈、慢语速内容可以自动放大到接近 60 分钟。
- 密集教程、代码讲解、字幕文本密度高时自动收缩。
- 每个 chunk 保留少量相邻 segment 作为上下文重叠，避免章节边界断裂。

### `llm`

MVP 默认后端是本机 `codex exec`，面向已经登录 Codex 的高级本地用户。公开项目中要明确这是本地高级模式，不是所有用户都能零配置运行的通用 API。

职责：

- 调用 `codex exec` 处理 chunk summary 和 merge summary。
- 使用 `--ephemeral`，避免长期会话污染。
- 使用 `--output-schema` 强制 JSON Schema。
- 尽量使用只读沙箱，避免视频内容触发工具写入。
- 对 stdout/stderr 做脱敏后再写入诊断。

建议命令形态：

```bash
codex exec \
  --ephemeral \
  --json \
  --model gpt-5.5 \
  --output-schema ./schemas/chunk_summary.schema.json \
  "Summarize the transcript chunk according to the schema."
```

MVP 需要两类 schema：

- `chunk_summary.schema.json`: 单个 chunk 的结构化学习笔记。
- `chapters.schema.json`: merge pass 后的最终章节报告。

后续可增加 OpenAI-compatible API、本地模型或 Codex SDK 后端，但渲染层只能依赖最终 JSON schema，不能依赖某个具体 LLM 实现。

### `chapter`

职责：

- 根据原始章节、字幕时间间隔、chunk summary 和内容主题生成最终章节。
- 每章生成问题、关键步骤、陷阱、结论、关键引用和可回跳时间戳。
- 输出结构化 `chapters.json`，供 HTML/PDF 共用。

原则：

- 默认报告风格是学习笔记，不是快速摘要。
- 不机械套固定模板，但字段结构必须稳定。
- 每章至少包含一个时间戳锚点。
- 关键引用必须来自 transcript segment，不能被改写。
- 引用旁边可以有中文解释或白话版。
- 总结文本以中文白话短句为主。
- HTML 和 PDF 都保留可点击 Bilibili 时间戳链接。

建议最终结构：

```text
video_summary
audience_fit
not_for
chapters[]
  title
  start_sec
  end_sec
  timestamp_url
  question
  key_points[]
  steps[]
  pitfalls[]
  conclusion
  quotes[]
    text
    start_sec
    timestamp_url
    explanation
    confidence
  diagram_spec optional
warnings[]
provenance
```

### `visual`

MVP 默认不生成 SVG 图解。用户传入 `--with-diagrams` 时，生成基础 SVG 图解。

职责：

- 让 Codex 输出 `diagram_spec`，而不是直接自由生成 SVG。
- 程序根据 spec 渲染 SVG。
- SVG 类型支持流程、对比、时间线、检查表、因果链五类。

校验：

- 每张图必须引用本章关键词和关系。
- 图中节点数小于 3 时不生成图，避免装饰图。
- SVG 为空或布局失败时，报告中降级为文字要点。

真实视频截图不进入 MVP。下一版可通过 `--with-frames` 增加，只在界面演示类视频里启用。

### `render`

职责：

- 用同一份结构化数据渲染 `report.html`。
- 用 Chrome headless 和 print CSS 生成 `report.pdf`。
- HTML 内联 CSS，SVG 内联或本地相对路径，保证离线打开。

HTML 要求：

- 首屏是报告内容，不做营销落地页。
- 保留视频标题、UP、当前 P、时长、标签、封面缩略图和一句话结论。
- 每章显示学习笔记、关键引用、时间戳链接和 warnings。

PDF 要求：

- A4 纵向。
- 首页包含标题、UP、当前 P、发布时间或时长、标签、封面缩略图、一句话结论和目录入口。
- 章节尽量不跨页切断标题。
- 保留目录、元数据、章节时间戳和 provenance。
- 不使用长图式窄屏排版作为 PDF 基础。

PDF 失败策略：

- HTML 生成成功即主流程成功。
- PDF 生成失败时默认记录 warning，并提示安装或配置 Chrome。
- 只有用户传入 `--require-pdf` 时，PDF 失败才返回非 0。

### `verify`

职责：

- 检查 `metadata.json`、`transcript.json`、`chunks.json`、`chapters.json` 是否存在且可解析。
- 检查最终 JSON 是否符合 schema。
- 检查 HTML 引用的本地资产是否存在。
- 用 headless Chrome 打开 HTML 并尽量生成 PDF。
- 检查 PDF 文件非空；未要求 PDF 时，PDF 失败只记 warning。

MVP 不做像素级重叠检测。后续版本再加入 Playwright 截图和视觉检查。

## 数据流

```text
URL
  -> ingest: metadata.json, cover, current part info
  -> media: audio cache, duration check
  -> transcript: transcript.json
  -> chunk: chunks.json
  -> llm: partial_summaries/*.json
  -> chapter: chapters.json
  -> visual optional: diagram specs / SVG
  -> render: report.html, report.pdf optional
  -> verify: diagnostics.json
```

## 错误处理和诊断

错误分为四类：

- `InputError`: URL 不支持、参数冲突、输出目录不可写。
- `AccessError`: 需要登录、cookies 无效、权限不足。
- `MediaError`: 下载失败、音频损坏、时长异常。
- `GenerationError`: 转写失败、Codex 总结失败、schema 校验失败、渲染失败。

默认 `diagnostics.json` 只保存脱敏后的结构化诊断：

- `error_type`
- `exit_code`
- `stage`
- `video_id`
- `part_index`
- `duration_check`
- `transcript_check`
- `artifact_paths`
- `sanitized_message`
- `warnings`

默认不保存：

- cookies 内容
- cookies 文件路径
- Codex auth/token
- 完整 stdout/stderr
- 带追踪参数的原始 URL
- 可能含用户名的本机绝对路径

用户显式传入 `--debug-log` 时，可以保存更完整的调试日志到 `.bilifan/logs/`。README 要提醒用户不要直接把 debug log 贴到 GitHub issue。

## 技术选型

- 语言：Python。
- CLI：Typer 或 Click，优先 Typer。
- 下载：`yt-dlp` Python API 或子进程封装，MVP 优先子进程，便于隔离参数和日志。
- 媒体：`ffmpeg` / `ffprobe`。
- 转写：本地 Whisper，后续可扩展 faster-whisper。
- 总结：本机 `codex exec`，默认模型 `gpt-5.5`，用 JSON Schema 约束输出。
- 渲染：Jinja2 HTML 模板 + Chrome headless PDF。
- 测试：pytest。

## 验收标准

MVP 完成时应满足：

- 对一个公开 Bilibili 当前 P 生成 `report.html`。
- 有 Chrome 时尽量生成 `report.pdf`；没有 Chrome 时 HTML 仍然成功。
- 元数据、转写、分块、章节、诊断文件都可复用。
- 无字幕视频能通过 Whisper fallback 生成 transcript。
- 已有字幕视频默认不强制 Whisper，除非传入 `--force-whisper`。
- `codex exec` 输出必须通过 JSON Schema 校验。
- 90-180 分钟视频会在交互模式提示继续确认。
- 超过 180 分钟默认拒绝，除非传入 `--allow-long-video`。
- 时长差异和 transcript 末尾差异能被检测并写入诊断。
- 报告显示 provenance、转写来源、LLM 后端和 prompt 版本。
- README 明确写出合规边界、cookies 安全提示和 Codex 本地高级模式。
- 最小测试覆盖 URL 当前 P 解析、时长差异计算、chunk 策略、JSON schema、HTML 资产检查、诊断脱敏。

## 暂不做

- 批量总结。
- Web UI。
- 本地音视频文件输入。
- 登录态管理。
- 自动发布到云端。
- 完整视频保存。
- 高级长图切片。
- UI 视频真实帧智能筛选。
- 默认 SVG 图解。
- 像素级重叠检测。

## 下一步

如果这个设计通过，下一轮进入实现计划：

1. 初始化 Python 项目和 CLI 骨架。
2. 实现 URL 当前 P 解析、首次确认和输出目录版本化。
3. 实现 `ingest` 和 `media` 的单视频闭环。
4. 加入 transcript 读取和 Whisper fallback。
5. 实现 chunk 策略和 `codex exec` JSON Schema 调用。
6. 生成基础 HTML/PDF。
7. 增加最小验证、诊断脱敏和 README 合规说明。
