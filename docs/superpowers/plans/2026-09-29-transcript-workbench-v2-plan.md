# 逐字稿工作台 v2 开发计划

依据同日期PRD，基线91fc135。隔离工作树 `.worktrees/transcript-workbench-v2`，分支 `codex/transcript-workbench-v2`；生产工作树先不改。

| 批次 | 内容 | 验收 |
|---|---|---|
| 0 | PRD/方案/LOOP/10样本契约 | 术语与完成条件无歧义、基线测试 |
| 1 | raw+article、无新report、bundle/JSONL/历史兼容 | 零报告调用、原稿先保存、旧report不变 |
| 2 | quality/路由/忠实度/原稿对照/导出 | A1–A8及跨产物传播 |
| 3 | 统一队列/v2原子账本/latest/凭证/迁移 | B1–B4/B8及重启故障 |
| 4 | 可取消执行器/进程看护/CLI锁 | B5–B7及孤儿/发布安全 |
| 5 | 分块缓存/强制重整/attempt指标 | C1–C5及跨失败取消 |
| 6 | 独立总review/全套/备份迁移/公网 | 11项直接证据、远端一致 |

主agent负责pipeline/retry/呈现导出集成与进度。独立可并行开发quality、queue、executor；按批次集成，明确文件清单暂存，未验收代码不混入批次；reviewer不参与对应实现。

技术约定：JSON v2保留历史，损坏停调度；output_profile=transcript_article_v1。队列/CLI共用实际执行锁和取消控制；子进程退出前不释放资格；发布临界区尊重retry_workspace保护。缓存绑定稳定原run，不能绑定临时副本。

测试：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /Volumes/mySSD/projects/bilifan/.venv/bin/python -m pytest -p no:cacheprovider -q`。模型/下载用固定输入及可挂起测试进程；故障只在tmp，不发送通知、不启动真实服务。历史资料只在副本上注入故障。

每批先推开发分支。最终空闲/备份后快进main、重启并公网验收。用户已明确授权计划内推送/升级；不强推、不删历史，不公开outputs/日志/配置/凭据。
