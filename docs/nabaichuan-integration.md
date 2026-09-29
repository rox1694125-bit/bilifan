# 纳百川导出文件契约

Bilifan 只在用户主动操作时，从 content_bundle.json 生成本地 JSONL。它不自动写入纳百川，也不调用外部知识库接口。

## Bundle v1

保留 schema_version=1、contract、bundle_id、source、transcript、transcript_article、artifacts、provenance。新增 output_profile=transcript_article_v1 和统一 quality。

新结果的 summary 表示未生成：status=not_generated、style为空、chapters为空，summary_validation.status=not_applicable。没有主报告不算缺失。旧带 summary.chapters 的 bundle 仍可读取，但新的逐字稿导出不复制其解读章节。

## JSONL记录

| 类型 | 内容 |
|---|---|
| video | 视频来源、标题、稳定ID与质量信息 |
| transcript_segment | 优先整理稿段落，缺整理稿时原稿段落；时间链接、text_source和质量信息 |

不再新导出 chapter 记录。段落的 parent_record_id 指向 video，chapter_id=null。保持 schema_version=1、export_contract=bilifan.nabaichuan.records.v1，以及既有 record_id 生成方式。run_key 仅在从run导出时可得。

每条记录携带 quality；text_source 明确 transcript_article 或 raw_transcript。content_hash 按正文和质量等记录内容计算，忽略run_key等导出元数据；质量变化可以改变hash，记录身份不变。外部已经导入的旧chapter不会被本项目自动删除。

## 复查策略

默认不导出 review_required 内容；单条明确返回未导出，批量跳过并列出原因。显式include_review_required=true仅允许本次纳入，文件仍带警告，不标人工审核通过。

历史导出使用已有原稿和完整metadata执行能做的本地检查；缺失依据保留unknown。升级不批量重写旧HTML/PDF，也不承诺外部纳百川已经消费质量字段。

Web批量导出生成JSONL和report.json，记录exported/skipped、原因、数量与文件链接。

```bash
python examples/content_bundle_to_nabaichuan.py /path/to/content_bundle.json --out /tmp/nabaichuan.jsonl
# 只有明确选择纳入需复查内容时加以下选项
python examples/content_bundle_to_nabaichuan.py /path/to/content_bundle.json --out /tmp/nabaichuan.jsonl --include-review-required
```

--include-transcript保留兼容；--no-transcript仅输出video记录。转换器在同目录原稿/metadata可得时会重检，并只向--out指定位置写JSONL。重新整理后原先显式导出的JSONL失效，请重新导出。

## Bilifan Feishu Runtime Boundary

Bilifan follows the same Hermes-owned Feishu runtime pattern as the Nabaichuan
integration, but it does not write to Nabaichuan and does not copy Nabaichuan's
archive workflow.

For Bilifan, Hermes owns the Feishu app, profile, credentials, gateway hook, and
outbound chat replies. Bilifan owns only the local intake API, queue, processing
state, and Web UI task center.
