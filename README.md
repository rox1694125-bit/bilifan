# Bilifan 逐字稿工作台

把你提供的 B 站当前分 P 或公开 YouTube 视频，转换为可追溯的原始稿和忠于原意的整理逐字稿。下载、转录和文件保存在本机，文章整理使用本机配置的 Codex CLI 模型服务。

## 默认交付

1. 优先平台字幕，必要时下载音频并用本地 Whisper 识别。
2. 先保留原始 `transcript.json`、`transcript.txt`、标准 `transcript.srt`。
3. 纠错、去重复口癖、断句、分段，生成 `transcript_article.json` 与 `transcript.html`；按选项生成整理稿 `transcript.pdf`。
4. 写入 `content_bundle.json`。知识库 JSONL 只在主动导出时生成。

新任务**不再生成解读式主报告、模板摘要、图解或截图**。旧 `report.html`、`report.pdf` 与 `chapters.json` 保留，网页标为历史主报告；新整理稿不混入旧结论。

原稿与 AI 整理稿是不同材料。质量状态分为“自动检查未发现明显异常”“需复查”“不可用”“未检查”，均不代表事实已经人工核实。数字、单位、代码或大段内容变化会给出定位提示；整理稿可展开对照原稿并跳回视频。

## 使用

```bash
uv sync --extra dev
python -m bilifan summarize "https://www.bilibili.com/video/BV...?p=2" --yes-i-understand --out ./outputs
python -m bilifan serve --no-open
```

未安装包时可用 `PYTHONPATH=src python -m bilifan ...`。需要 Python 3.11+、yt-dlp、ffmpeg/ffprobe、Whisper、已配置的 Codex CLI；PDF 使用 Chrome。Apple Silicon 支持 MLX Whisper。

常用选项：

- `--language auto|zh|en`：控制语音识别语言，优先已有字幕。
- `--force-whisper`：跳过字幕，重新识别。
- `--format html|pdf|html,pdf`：HTML 始终保留；PDF 按需生成。
- `--require-pdf`：整理稿 PDF 失败则整个本次交付失败；默认 PDF 尽力生成。
- `--allow-long-video`：允许超过180分钟；已知时长在昂贵步骤前检查。
- `--yes-i-understand`：接受本地处理与模型服务告知，并确认90–180分钟的处理。
- CLI 的 cookies 仅用于用户本来有权查看的内容，Web 不接收 cookies。

旧 `--summary-template`、`--with-frames`、`--with-diagrams` 兼容接受但提示停用，不再驱动主报告。

## 恢复与复用

```bash
python -m bilifan retry outputs/<output_id>/runs/<run_id> --from article
python -m bilifan retry outputs/<output_id>/runs/<run_id> --from render
python -m bilifan retry outputs/<output_id>/runs/<run_id> --from bundle
python -m bilifan retry outputs/<output_id>/runs/<run_id> --from article --force-article
```

旧 `--from summarization` 是 `article` 的兼容别名。文章恢复从当前原稿重新分块，复用同一 run 内已验证的文章块；原稿、模型、提示或规则变更会失效。`--force-article` 开启新缓存代；该次失败后的普通恢复继续本代已完成块，不混回之前的旧块。

新稿在隔离副本生成，成功验收后才发布；普通生成/发布失败保住旧成果，失败另写 `retry_diagnostics.json`。旧主报告和章节文件不删除。成功后旧的显式 JSONL 失效，需要重新导出。

重试需要额外临时磁盘空间；发布使用两次同文件系统重命名并可回滚普通异常，不是断电原子交换。强制中断的极端情况可能留下 `runs/.<run_id>.backup-<id>` 原成果备份，不要删除或在缺失原目录位置另建新目录。

## 任务与取消

Web 单条、合集、批量、飞书和历史重试共用持久 FIFO，一次一项。忙时仍可入队，刷新可按任务ID继续查看。暂停仅停止后续调度。

网页“允许长视频”默认开启，可在高级设置中关闭；单条、批量与合集使用当前开关。飞书/API 未指定该选项时也默认允许，显式关闭与已有任务保存的选项仍有效。

- 等待任务立即取消；运行任务先显示取消中，实际计算退出后才取消并开始下一项。
- 受控进程先请求退出，5秒仍不退出再终止；测试目标10秒内停止。发布短暂关键段不强杀，发布完成后取消视为过晚。
- 未暂停队列在服务重启后继续未开始项；原先暂停保持；中断项人工恢复，不自动整项重算。
- CLI 共用 outputs 执行锁，遇忙会说明，CLI 不进入 Web 队列。
- 执行身份不明或任务账本损坏时暂停，不静默清空。只有明确点恢复才核对旧执行身份；无法确认不会误杀其他进程。

执行器跟踪受控进程的随机标记和启动身份。主动清空环境、脱离会话且早于任何归属观测的任意后台程序，不属于非特权 POSIX 可以绝对证明的范围；本项目不声称提供操作系统沙箱隔离。

账本升级为 JSON v2，保留历史任务ID、来源与飞书幂等数据；旧等待项标明新版只整理逐字稿。只在空闲、备份后升级，异常保留现场。

## 质量与导出

新字幕与语音识别执行本地质量检查。明显不可用的原稿停止后续AI整理，但保留已取得的文本；可读的可疑内容继续生成带警告整理稿。

单条需复查内容默认不导出；批量默认跳过并列原因。可明确选择“仍然导出并保留警告”，这不等于人工审核通过。每条 JSONL 都带质量字段，原稿 TXT 带说明；SRT 下载包 `transcript_source.zip` 含标准字幕、质量 JSON 与说明。

整理块检查点与每次尝试指标保存在 run 外的隐藏侧车目录，失败/取消后保留，不暴露为客户文件。指标区分排队、处理、缓存和失败，记录真实调用次数与可得 token 用量；未知不是0，不伪造费用。

详见 [纳百川文件契约](docs/nabaichuan-integration.md)。本项目只生成本地文件，不调用纳百川接口；外部系统是否使用质量字段需独立确认。

## 远程访问与边界

公网入口为 `https://bilifan.buyaoting.top/`，Cloudflare Access 登录后操作本机服务。所有计算依然依赖这台 Mac、外接SSD、网络和本机工具。API使用每次服务启动的token，旧页面失效后刷新。

```bash
scripts/bilifan-remote.sh status
scripts/bilifan-remote.sh restart
```

部署细节及自启恢复见 [远程运行文档](docs/remote-access-cloudflare.md)。不得绕过登录、付费、地区、风控、DRM 或访问控制；只处理用户指定且有权访问的内容。公开视频范围仍为 B站当前P和普通 YouTube 视频，不扩展受限资源、直播和播放列表抓取。

飞书只负责提交现有支持链接，任务使用同一队列并在网页查看；本版本没有新增手机短链、聊天指令或完成通知。

## 验证

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -p no:cacheprovider -q
BILIFAN_METADATA_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -p no:cacheprovider tests/test_metadata_smoke.py -q
```

完整套件包含可终止的真实测试进程，需要允许查询本用户进程身份；默认3个联网元数据测试跳过。真实模型调用、PDF视觉检查、公网与迁移验收分别记录，不把替代函数测试当成真实模型验收。
