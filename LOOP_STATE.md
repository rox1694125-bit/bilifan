# LOOP_STATE

## Objective

实施用户确认的逐字稿工作台v2：raw+忠实整理稿，停新主报告；质量闭环；统一持久任务/快速取消/恢复；分块复用与指标；独立review、测试、迁移和公网交付。

## Scope and authority

完整范围见 docs/superpowers/specs/2026-09-29-transcript-workbench-v2-prd.md；分批计划见同日期plan。用户已明确授权计划内源码/测试/文档推送与正式升级。无新增Hermes交互、外部消息、模型替换、历史全量重跑、外部知识库写入或凭据变更。

## Stop conditions

- [ ] PRD/方案/10固定样本契约和基线。
- [ ] 新任务raw+article、零新report，原稿先保留、旧report/chapters/hash/入口保留。
- [ ] 路由冲突/忠实度定位，统一质量贯穿交付与导出策略。
- [ ] 所有入口持久FIFO，v1迁移/原子账本/损坏可见/latest成功指针/完成凭证。
- [ ] 真实计算快速取消、父退出无双执行、CLI共享锁、发布安全。
- [ ] 缓存跨失败/取消/重启复用，规则变化失效，指标准确。
- [ ] 11端到端验收有直接证据，独立总review无阻塞、完整测试通过。
- [ ] 空闲备份迁移、公网验证，GitHub/main/部署一致且工作区干净。

## Verification

隔离工作树使用主项目venv和PYTHONPATH=src。所有故障注入在tmp；真实资料不入Git。公网只走bilifan.buyaoting.top并先查Web/Tunnel。

## Progress

### 0 - 契约与基线
- 已核实main=91fc135、干净；已创建隔离分支/工作树，生产源码未改。
- PRD、开发计划与进度已落库；基线558 passed、3 skipped（5.79s），一项既有Starlette弃用提示。quality、queue、executor互不冲突模块已分派，root集成默认交付。

## Current status

active。保持用户完整范围，不以局部通过代替交付。
