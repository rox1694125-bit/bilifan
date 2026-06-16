# Bilifan 产物收敛设计

## 背景

Bilifan 当前一次 run 会产出多类文件：`report.html`、`report.pdf`、
`notes.md`、`transcript.txt`、`transcript.srt`、`content_bundle.json`、
`nabaichuan.jsonl`，以及多个内部调试 JSON。这个结构对调试有用，但对普通用户
来说结果过多，阅读入口不够清楚。

新的产品边界是把“用户直接阅读的交付物”和“内部状态/机器契约”分开。新 run
成功后，普通 Web 页面只展示 4 个用户文件：

- `transcript.html`
- `report.html`
- `transcript.pdf`
- `report.pdf`

其他文件默认隐藏；用户仍可通过“打开文件夹”查看本地完整 run 目录。

## 目标

- 把清洗后的逐字稿文章作为用户内容的唯一章节真源。
- 在逐字稿文章生成阶段修正常见 Whisper 错别字、同音误识别和断句问题。
- 保持 `report.html` 作为主报告，但让它基于同一套逐字稿文章章节生成。
- 普通 Web 结果列表只展示 4 个用户文件，不展示机器文件和调试文件。
- 保留内部 JSON、provenance 和导出契约，方便调试、重试和下游导出。
- 兼容旧 run，但不批量迁移旧 run。

## 非目标

- 不迁移全部历史 run。
- 不在普通 Web 结果列表暴露 `content_bundle.json` 等机器文件。
- 不再默认生成 `notes.md`、`transcript.txt`、`transcript.srt`。
- 不再默认生成 `nabaichuan.jsonl`。
- 不在本轮实现逐字级纠错 diff。
- 不移除普通 Web 页面里的“打开文件夹”入口。

## 内容链路

新 run 的内容链路如下：

1. 生成 `transcript.json`。
   这是原始转写层，来自 Bilibili 字幕、YouTube 字幕或 Whisper。它默认隐藏，
   用于追溯、调试和必要时复查。

2. 生成 `transcript_article.json`。
   这是新的内容真源。它包含智能纠错、清洗、断句、分段、章节、重点标注、
   原始 segment 范围和 warnings。

3. 渲染 `transcript.html`。
   这是用户阅读的逐字稿文章。正文不展示逐句时间戳，保留章节级“回到视频”
   链接，并用排版突出重点。

4. 渲染 `report.html`。
   主报告保持不变的定位，但摘要、要点、引用和证据都基于
   `transcript_article.json` 的章节生成，不再直接基于原始 transcript 或旧
   摘要章节。

5. 生成 PDF。
   `transcript.pdf` 从 `transcript.html` 导出，`report.pdf` 从 `report.html`
   导出。

6. 写入内部契约文件。
   `content_bundle.json` 默认生成但在普通 Web 页面隐藏。`nabaichuan.jsonl`
   只在用户主动导出时生成。

## `transcript_article.json` 契约

`transcript_article.json` 是用户内容的章节真源，需要有 schema 版本，并稳定服务
`transcript.html`、`report.html` 和 `content_bundle.json`。

建议结构：

```json
{
  "schema_version": 1,
  "source": "whisper",
  "cleaning_level": "strong",
  "sections": [
    {
      "section_index": 1,
      "title": "章节标题",
      "start": 0.0,
      "end": 120.0,
      "timestamp_url": "https://example.com?t=0",
      "source_segment_start_index": 0,
      "source_segment_end_index": 12,
      "paragraphs": [
        {
          "text": "清洗后的正文段落。",
          "emphasis": [
            {"text": "重点词", "kind": "strong"}
          ]
        }
      ],
      "key_terms": ["重点词"],
      "warnings": []
    }
  ],
  "warnings": []
}
```

实现时可以增加字段，但必须满足这些约束：

- 每个 section 都有稳定序号、标题、起止时间和原始 segment 范围。
- 段落文本是清洗后的可读正文，但不能新增视频里没有表达的信息。
- 重点标注使用结构化数据，不直接存 HTML。
- warnings 只保留轻量追溯信息，例如不确定术语或低置信清洗提醒，不记录完整
  逐字 diff。

## 智能清洗规则

所有转写来源都生成 `transcript_article.json`，但清洗力度不同：

- Whisper：强清洗。重点修正明显错别字、同音错词、术语误转写、重复词、口头禅、
  标点、断句和分段。
- Bilibili / YouTube 字幕：轻清洗。主要优化标点、段落、章节和重点标注，少改词。

共同规则：

- 能从上下文确定的错误直接修正。
- 不确定的词不强猜。
- 不新增原视频没有表达的信息。
- `transcript.html` 不展示逐项纠错对照。
- 原始 `transcript.json` 继续保留，用于追溯。

## 报告生成

旧的 `chapters.json` 不再作为章节真源。新的章节真源是
`transcript_article.json.sections`。

实现时可以选择：

- 暂时保留 `chapters.json`，但把它降级为由 article sections 派生的内部报告摘要
  文件。
- 或者新建一个更明确的报告摘要内部文件。

无论采用哪种实现，都必须保持这个不变量：

- 逐字稿文章章节定义用户看到的章节边界。
- `transcript.html` 渲染这些章节。
- `report.html` 总结这些章节。
- `report.html` 可以保留证据锚点和时间范围，因为它承担校验和复查职责。

## 用户可见文件

普通 Web 任务卡片和历史记录只展示：

- `transcript.html`
- `report.html`
- `transcript.pdf`，如果生成成功
- `report.pdf`，如果生成成功

同时保留“打开文件夹”入口。

普通结果列表不展示这些文件的直接链接：

- `metadata.json`
- `transcript.json`
- `transcript_article.json`
- `chunks.json`
- `chapters.json` 或后续替代的报告摘要 JSON
- `partial_summaries/*.json`
- `diagnostics.json`
- `content_bundle.json`
- `nabaichuan.jsonl`
- `notes.md`
- `transcript.txt`
- `transcript.srt`
- `media/audio.mp3`
- `media/frames/*.jpg`

失败任务展示人话错误原因和合适的重试操作，但普通结果列表不直接展示
`diagnostics.json` 链接。

## CLI 和 PDF 行为

新默认行为：

- `transcript.html` 和 `report.html` 必须生成；任一失败则 run 失败。
- `transcript.pdf` 和 `report.pdf` 在启用 PDF 输出时默认尝试生成；PDF 失败只记录
  warning，不让 run 失败。
- `--require-pdf` 开启后，任一 PDF 失败都让 run 失败。
- `--output-format html` 只生成两个 HTML，不尝试 PDF。
- Web UI 默认生成两个 HTML，并 best-effort 尝试两个 PDF。

可以保留现有 `--output-format` 解析以兼容旧命令，但产品主模型变成“两份 HTML +
best-effort PDF”。

## 机器契约和导出

`content_bundle.json` 默认生成并隐藏。它要改成以清洗后的 article sections 为主，
同时继续保留 source metadata、artifact 映射、transcript provenance 和脱敏路径。

`nabaichuan.jsonl` 不再随每次成功 run 自动生成。它只在用户主动执行单 run 导出或
批量导出时，从 `content_bundle.json` 派生。

`outputs/_exports/` 下的批量导出文件仍然是用户主动导出的结果，不属于普通 run
结果文件。

## 历史 run 兼容

历史 run 不批量迁移。

兼容规则：

- 新 run 使用新产物结构。
- 旧 run 保持现有文件不变。
- 旧 run 没有 `transcript.html` 时，不伪造逐字稿文章。
- 旧成功 run 可以继续展示已有的 `report.html` 和 `report.pdf`，按 legacy 格式处理。
- 旧失败或半成品 run 不能因为磁盘上有残留文件，就把机器/调试文件展示成用户结果。

兼容测试选择 6 类本地旧 run：

- 早期成功 run，无 `content_bundle.json`。
- 成功 run，有 `content_bundle.json`，无 `nabaichuan.jsonl`。
- 较新成功 run，旧全量产物齐全。
- transcript 阶段半成品。
- diagnostics-only 失败 run。
- YouTube 旧成功 run。

实现时可以从本地 `outputs/` 中按类型挑具体目录。这 6 个样本只用于兼容验证，不是
迁移对象。

## 验证

需要覆盖这些测试：

- `transcript_article.json` schema 和规范化。
- Whisper 强清洗、字幕轻清洗的 prompt/runner 行为。
- 章节边界和原始 segment 范围保留。
- `transcript.html` 不展示逐句时间戳。
- `transcript.html` 有章节级回视频链接。
- `report.html` 基于 article sections 生成。
- PDF best-effort 行为和 `--require-pdf` 失败行为。
- 新 run 的 Web artifact 只展示 4 个用户文件和 open-folder。
- 6 类旧 run 的兼容展示。
- `content_bundle.json` 使用清洗后的 article sections，同时在普通 Web 结果里隐藏。
- 显式导出 `nabaichuan.jsonl` 仍然可用。

沿用项目现有验证命令：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

## 风险

- 清洗可能过度修正专业术语。设计约束是“能确定就修，不确定不猜”。
- 章节真源从报告摘要迁移到逐字稿文章，会影响 pipeline、渲染、bundle 和 Web
  artifact 链接，需要测试锁住新不变量。
- PDF 仍然依赖本机 Chrome。HTML 是必需内容产物，PDF 只有在 `--require-pdf` 时才
  成为硬性要求。
- 旧 run 兼容容易因为新 artifact 集合而回归，需要用真实旧 run 类型做覆盖。
