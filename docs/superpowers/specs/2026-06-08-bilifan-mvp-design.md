# Bilifan MVP Design

## 背景

Bilifan 是一个本地运行的 Bilibili 视频总结生成器。目标不是做公开视频抓取服务，而是让用户在自己的电脑上、用自己有权访问的视频和账号权限，生成离线可读的学习报告。

第一版只做一个窄闭环：

- 输入一个 Bilibili 视频 URL。
- 获取视频元数据和音频。
- 优先读取已有字幕，没有字幕时再用 Whisper 转写。
- 生成章节化中文总结。
- 输出离线 HTML 和 PDF。
- 做最小渲染校验，确认 HTML/PDF 关键资产存在且页面能打开。

长图、复杂截图筛选、高级动态 SVG、批量队列和 Web UI 暂不进入 MVP。

## 用户边界

项目默认用于个人学习、研究和归档。公开项目需要明确：

- 不提供托管抓取服务。
- 不内置 Bilibili cookies。
- 不绕过登录、付费、地区、风控或 DRM 限制。
- 用户自行保证自己有权访问、处理和保存相关内容。
- 默认只处理用户显式传入的单个 URL，不做平台级批量抓取。

## CLI 形态

MVP 提供一个 Python CLI：

```bash
bilifan summarize "https://www.bilibili.com/video/BV..." \
  --cookies-from-browser chrome \
  --format html,pdf \
  --out ./outputs
```

关键参数：

- `url`: 必填，单个 Bilibili 视频 URL。
- `--cookies-from-browser`: 可选，透传给 `yt-dlp`。
- `--cookies-file`: 可选，读取用户提供的 cookies 文件。
- `--format`: 可选，默认 `html,pdf`。
- `--out`: 可选，默认 `./outputs/<video-id>/`。
- `--transcriber`: 可选，默认 `auto`，优先字幕，fallback 到本地 Whisper。

## 输出结构

每个视频生成一个独立目录：

```text
outputs/<video-id>/
  metadata.json
  transcript.json
  chapters.json
  report.html
  report.pdf
  assets/
    cover.jpg
    diagrams/
```

MVP 阶段不保存完整视频。音频缓存默认放在工作目录下的 `.bilifan/cache/`，后续可加 `bilifan clean` 清理。

## 模块设计

### `ingest`

职责：

- 调用 `yt-dlp` 获取元数据。
- 保存标题、UP、分 P、简介、标签、封面、时长、章节、字幕列表。
- 下载封面到 `assets/cover.jpg`。

约束：

- 不在日志里打印 cookies。
- 只处理用户输入的 URL。
- 遇到需要登录或权限不足时返回明确错误，不尝试绕过。

### `media`

职责：

- 下载最佳音频。
- 用 `ffprobe` 读取实际时长。
- 将音频标准化为 Whisper 友好的中间文件。

校验：

- `metadata.duration` 与 `ffprobe.duration` 差异超过 5% 时标记 `duration_mismatch`。
- 不自动无限重试。MVP 只重试 1 次，仍失败就终止并保留诊断信息。

### `transcript`

职责：

- 优先使用 Bilibili/yt-dlp 提供的字幕。
- 没有字幕时调用本地 Whisper。
- 输出 segment 级时间戳、文本、语言、来源。

模型策略：

- 中文默认 `turbo` + `language=Chinese`。
- 英文默认 `small.en` 转写，再交给后续总结阶段翻译成中文。
- 不用 `turbo` 做翻译任务。

校验：

- 最后一个 segment 的结束时间与音频时长接近。
- 差异超过阈值时标记 `transcript_incomplete`，报告中展示警告。

### `chapter`

职责：

- 根据原始章节、字幕时间间隔和内容主题切分章节。
- 每章生成问题、关键步骤、陷阱、结论、关键引用和可回跳时间戳。
- 输出结构化 `chapters.json`，供 HTML/PDF 共用。

原则：

- 不机械套固定模板。
- 每章至少包含一个时间戳锚点。
- 关键引用必须来自 transcript segment。
- 总结文本以中文白话短句为主。

### `visual`

MVP 只生成基础 SVG 图解，不做真实帧截图。

职责：

- 让模型输出 `diagram_spec`，而不是直接自由生成 SVG。
- 程序根据 spec 渲染 SVG。
- SVG 类型支持流程、对比、时间线、检查表、因果链五类。

校验：

- 每张图必须引用本章关键词和关系。
- 图中节点数小于 3 时不生成图，避免装饰图。
- SVG 为空或布局失败时，报告中降级为文字要点。

### `render`

职责：

- 用同一份结构化数据渲染 `report.html`。
- 提供 `print.css` 生成 `report.pdf`。
- HTML 内联 CSS，SVG 内联或本地相对路径，保证离线打开。

PDF 要求：

- A4 纵向。
- 章节尽量不跨页切断标题。
- 保留目录、元数据、章节时间戳和图解说明。
- 不使用长图式窄屏排版作为 PDF 基础。

### `verify`

职责：

- 检查 `metadata.json`、`transcript.json`、`chapters.json` 是否存在且可解析。
- 检查 HTML 引用的本地资产是否存在。
- 用 headless Chrome 打开 HTML 并生成 PDF。
- 检查 PDF 文件非空。

MVP 不做像素级重叠检测。后续版本再加入 Playwright 截图和视觉检查。

## 数据流

```text
URL
  -> ingest: metadata.json, cover
  -> media: audio cache, duration check
  -> transcript: transcript.json
  -> chapter: chapters.json
  -> visual: diagram specs / SVG
  -> render: report.html, report.pdf
  -> verify: validation report
```

## 错误处理

错误分为四类：

- `InputError`: URL 不支持、参数冲突、输出目录不可写。
- `AccessError`: 需要登录、cookies 无效、权限不足。
- `MediaError`: 下载失败、音频损坏、时长异常。
- `GenerationError`: 转写失败、章节生成失败、渲染失败。

CLI 默认失败即退出并返回非 0 状态码。可恢复异常写入 `diagnostics.json`，方便用户提交 issue。

## 技术选型

- 语言：Python。
- CLI：Typer 或 Click，优先 Typer。
- 下载：`yt-dlp` Python API 或子进程封装，MVP 优先子进程，便于隔离参数和日志。
- 媒体：`ffmpeg` / `ffprobe`。
- 转写：本地 Whisper，后续可扩展 faster-whisper。
- 渲染：Jinja2 HTML 模板 + Chrome headless PDF。
- 测试：pytest。

## 验收标准

MVP 完成时应满足：

- 对一个公开 Bilibili 视频生成 `report.html` 和 `report.pdf`。
- 元数据、转写、章节、报告四个中间文件都可复用。
- 无字幕视频能通过 Whisper fallback 生成 transcript。
- 时长差异和 transcript 末尾差异能被检测并写入诊断。
- README 明确写出合规边界和 cookies 安全提示。
- 最小测试覆盖 URL 参数校验、时长差异计算、章节 JSON schema、HTML 资产检查。

## 暂不做

- 批量总结。
- Web UI。
- 登录态管理。
- 自动发布到云端。
- 完整视频保存。
- 高级长图切片。
- UI 视频真实帧智能筛选。
- 像素级重叠检测。

## 下一步

如果这个设计通过，下一轮进入实现计划：

1. 初始化 Python 项目和 CLI 骨架。
2. 实现 `ingest` 和 `media` 的单视频闭环。
3. 加入 transcript 读取和 Whisper fallback。
4. 生成基础 HTML/PDF。
5. 增加最小验证和 README 合规说明。
