# LOOP_STATE

## Objective

实施用户确认的逐字稿工作台v2：raw+忠实整理稿，停新主报告；质量闭环；统一持久任务/快速取消/恢复；分块复用与指标；独立review、测试、迁移和公网交付。

## Scope and authority

完整范围见 docs/superpowers/specs/2026-09-29-transcript-workbench-v2-prd.md；分批计划见同日期plan。用户已明确授权计划内源码/测试/文档推送与正式升级。无新增Hermes交互、外部消息、模型替换、历史全量重跑、外部知识库写入或凭据变更。

## Stop conditions

- [x] PRD/方案/10固定样本契约和基线。
- [x] 新任务raw+article、零新report，原稿先保留、旧report/chapters/hash/入口保留。
- [x] 路由冲突/忠实度定位，统一质量贯穿交付与导出策略。
- [x] 所有入口持久FIFO，v1迁移/原子账本/损坏可见/latest成功指针/完成凭证。
- [x] 真实计算快速取消、父退出无双执行、CLI共享锁、发布安全。
- [x] 缓存跨失败/取消/重启复用，规则变化失效，指标准确。
- [ ] 11端到端验收有直接证据，独立总review无阻塞、完整测试通过。
- [ ] 空闲备份迁移、公网验证，GitHub/main/部署一致且工作区干净。

## Verification

隔离工作树使用主项目venv和PYTHONPATH=src。所有故障注入在tmp；真实资料不入Git。公网只走bilifan.buyaoting.top并先查Web/Tunnel。

## Progress

### 0 - 契约与基线
- 已核实main=91fc135、干净；已创建隔离分支/工作树，生产源码未改。
- PRD、开发计划与进度已落库；基线558 passed、3 skipped（5.79s），一项既有Starlette弃用提示。quality、queue、executor互不冲突模块已分派，root集成默认交付。

### 1–2 - 默认交付与质量（完成）
- 默认pipeline/retry已移除主报告/图解调用，raw先落盘；历史report/chapters保留；bundle v1标not_generated。
- quality统一模型、原稿对照、TXT/SRT质量包、JSONL字段与默认过滤已接入。10个合成/历史形态脱敏重构fixture明确标来源，不冒称真实快照。
- 独立review发现并已修：bundle半成品假成功、unusable原稿下载清单遗漏、retry门槛不一致、bundle警告包不同步、完成hash验证。
- 新契约/旧测试迁移完成；旧报告仅验证保留与访问。

### 3–4 - 持久队列与可取消计算（完成）
- queue v2 39项定向测试通过；真实queue/executor退出后串行推进测试通过。
- executor14项真实进程测试通过后，独立review额外找到detach+closefds即时退出的漏追踪窗口，已补齐归属追踪和回归，真实进程完整套件已通过。
- Web已统一到queue/current同账本，支持按ID跟踪、运行时继续提交；原成功latest仅完成后推进。

### 5 - 分块与指标（完成）
- article/cache/metrics及质量相关86项通过。已按review补raw-only变更绑定、force新缓存代、模型调用前持久计数。
- 硬终止指标收口、retry缺chunks补建、成功重试latest推进均完成。

### 6 - 总验收与上线（进行中）
- 冻结代码全套709 passed、3 skipped（49.96s），独立review已收口。
- 真实资料副本迁移7任务/4批次/56产物哈希保留；历史重渲染4文件哈希不变；真实Chrome PDF视觉检查通过。
- 六批实现已推送开发分支；生产main仍为91fc135。公网确认空闲后已暂停队列，正在备份升级。
- 详见 docs/transcript-workbench-v2-acceptance.md。

## Current status

active。保持用户完整范围，不以局部通过代替交付。
