# P1/P2 可靠性治理验证记录

日期：2026-11-11（Asia/Shanghai）。基线提交：`0e69f74`；实施分支：`codex/reliability-hardening`。

本轮修复审查清单和原 TODO 中可本地实施的 P1/P2 软件问题，并补齐其数据库前置、测试和发布流程。**T07 真实历史行情全面修复及权威点时分母仍未完成**，不能将代码测试通过表述为所有数据/生产门槛已关闭。逐项状态见 [TODO](../TODO.md)。

## 交付范围与主要文件

| 范围 | 结果 | 主要入口 |
|---|---|---|
| 核心计算/行情 | 最新窗口及历史截止、按指标历史长度、本地行情优先及不足/源失败语义、价格写入闸门、量额NULL警告、配置内单源降级、主数据非空/权威状态合并 | `monitor_engine.py`、`strategy_service.py`、`sync_service.py`、`full_market_history_service.py`、`tushare_adapter.py` |
| 修复保护 | 上游原始代码/市场/日期与响应指纹；完整冻结快照；新写入拒绝旧无身份计划，保留旧批次校验/回滚 | `source_identity.py`、`quote_repair_source_service.py`、`daily_quote_repair_service.py`、`repair_daily_quotes.py` |
| 执行与复盘 | 日期/方向/有限正数/null校验，跨SQLite/PG提醒原子幂等；当前股票现金流与复盘快照分列；错误最大回撤改最差五日收益 | `schemas/trade.py`、`routers/plans.py`、`routers/alerts.py`、`strategy_backtest.py` |
| 持久任务/调度 | 进度/结果/owner/心跳、跨进程读取、过期中断/保留、持久终态CAS、租约与唯一slot、上海交易日/错过策略、统一最近历史 | `models/task.py`、`tasks/background.py`、`tasks/scheduler.py`、`routers/sync.py` |
| 消息/AI | savepoint、真实消费状态、严格JSON/原文锚定/来源证券映射、反证与来源等级、允许动作、审计/幂等/有限重试、人工状态保护、映射与默认关闭流水线 | `message_llm_validation.py`、`message_source_policy.py`、`message_mapping_service.py`、`message_pipeline_service.py`、既有消息/图谱/AI服务 |
| 前端 | 请求身份/缓存/分页/深链、统一可恢复轮询、任务消息二期、日报候选证据、驳回理由、账本口径、路由lazy和图表分包 | `PoolList.tsx`、`SignalDetail.tsx`、`PlanList.tsx`、`MessageCenterPage.tsx`、`taskPolling.ts`、`taskNotifications.ts`及组件/API/types |
| 迁移/交付 | 两个增量revision、SQLite兼容、新旧结构验收、完整schema readiness、事务数据复制、CI、固定SHA发布/备份恢复/旧镜像健康验证 | `backend/alembic/versions/`、`adopt_legacy_schema.py`、`deployment_database.py`、`readiness_service.py`、GitHub workflows、ECS release脚本 |

未引入自动交易、市场状态评分、新付费来源或新的外部队列服务。原 `.env` 和历史来源/计划/审计工件未覆盖。

## 最终实际验证

在本地后端迁移/重启后，再次执行最终回归：

| 检查 | 实际结果 |
|---|---|
| Python / 依赖 | **Python 3.11.15**；`python -m pip check` 无依赖冲突；使用 `requirements.lock` |
| 后端全部默认单测/API + opt-in真实PG | **367 passed，0 skipped，34.37s**；剩1条既有 pandas concat FutureWarning |
| 其中真实PG | **8项**：升级/降级/ORM一致、消息/日报API、SQLite→PG JSON/日期/复合键、备份恢复、升级后旧备份同库恢复、恢复错误事务回滚、并发提醒claim、任务恢复及调度单例 |
| 前端 lint | 通过 |
| 前端 build | 通过；入口693.72kB/gzip229.35kB，独立图表591.43kB/gzip196.88kB；保留500kB构建提示 |
| 隔离Playwright | **23 passed，1.1m**；独立4177端口，所有API显式mock并阻断外联 |
| 发布恢复故障注入 | 覆盖成功、备份失败、迁移失败、业务smoke失败、停止writer失败；停止失败时禁止恢复；真实PG恢复失败整体回滚 |
| 结构/打包检查 | Alembic与ORM一致性、旧约束漂移拒绝stamp、全部ORM readiness、shell语法、workflow/compose YAML解析、`git diff --check`通过 |
| 本地真实后端 | `/api/health`、`/api/ready`、观察池、计划、真实模式消息、持久任务历史六个只读入口均HTTP 200 |
| 本地真实前后端 | agent-browser独立会话登录后进入`/plans`；交易计划空状态、导航可见；1280×900无页面水平溢出；无页面JS错误 |

最终后端命令（连接均为隔离测试库/schema；不是活动业务库）：

```bash
cd backend
DATABASE_URL=sqlite:////tmp/<isolated>/tests.db \
AUTO_INIT_DB=false AUTO_START_SCHEDULER=false SCHEDULER_ENABLED=false \
QUOTE_REPAIR_POSTGRES_ADMIN_URL=postgresql+psycopg://newquant_test@127.0.0.1:55439/postgres \
RUNTIME_POSTGRES_TEST_URL=postgresql+psycopg://newquant_test@127.0.0.1:55439/postgres \
./venv/bin/python -m pytest -q --run-integration
```

该次全部 integration 标记均为上述8项PG检查；外部 Tushare 探测文件不在默认 `test_*.py` 收集范围。临时PG16实例使用独立目录/端口及UTF8，不复用系统业务库。

浏览器覆盖：观察池→雷达→提醒→计划→成交→复盘；首屏外深链/全部收起；切池/切股乱序、缓存命中作废在途响应；分页失败原页重试与跨池丢弃；两日报候选证据、人工复核/驳回取消；同步/扫描/回测弱网恢复；真正失败、通知去重、存储额度异常和刷新待确认。

12条离线消息语料用于校验器/规则：有意包含坏JSON、伪代码、伪引用、反证与弱映射。专项指标不代表真实模型成功率或来源事实真实性；没有为本轮测试调用付费LLM。

## 交叉审查闭环

实现后由不同agent进行规格与质量复核，以下新增问题全部修复并补回归：

- 心跳与终态乱序覆盖结果，以及跨进程中断被旧更新撤销：任务锁+快照+SQL终态CAS。
- 指标源全失败/部分缺失被包装成完成零候选：结构化数据不足与失败，避免误报。
- 无身份旧计划从apply绕过门槛：实际新写入强制身份，历史批次兼容。
- PG只用`pg_restore --clean`不能清除升级新增对象：专用schema重建与恢复同事务；失败回滚。
- 接管审计表缺唯一等约束、readiness漏关联表、发布SHA漂移/中断、恢复前writer停止失败和旧应用未探活。
- 历史日报末跳未来关系/证据：统一有效期、来源日期与上海发布时间/原文校验。
- 同URL高置信转载覆盖官方反证：合并provenance、保留官方反证、同源仅计一次。
- 模型任意next_actions：精确允许枚举/别名；非法动作整体拒绝，保存raw并规则回退。
- 自动reviewed阻止弱映射降级：人工标记与自动状态分离，保护已确认人工结果。

最终定向复验未发现这些冻结范围内的新阻断项。历史图谱仍没有完整的 captured_at 点时知识版本重放能力，本轮不把publication日期裁剪称为该能力。

## 本地迁移与数据安全记录

- 旧本地Python3.9后端正常停止，确认数据库无写连接后进行完整备份；没有直接在业务主库跑测试或演练回滚。
- 备份：[830c7fcb-fb33-4ec7-8b82-915d415628b8.db.manifest.json](/Users/lijiajun/.local/share/newquant/reliability/2026-11-11/830c7fcb-fb33-4ec7-8b82-915d415628b8.db.manifest.json)。备份文件SHA256：`1f1cc5dff087dfd931c835874b4da97418ce9cfa33cd646650c443bc413e8253`。
- 活动库此前版本为`c4647a9160ea`，但显式SQLite修复流程已创建审计表。先完整校验审计两表并对齐到`1f4b0c7d9e2a`，再运行增量升级至 **`3b2f8da1c422`**；未重写已版本化baseline的其他旧约束。
- 与完整备份按旧列投影、逐行排序摘要对照：**30张原有表全部行数及内容指纹一致**，其中 **1,965,310条行情保持不变**；新建3张任务/调度表在启动前均为空。`PRAGMA integrity_check=ok`。
- 完整核对结果：[local-migration-validation.json](/Users/lijiajun/.local/share/newquant/reliability/2026-11-11/local-migration-validation.json)。核对发生在应用/调度恢复运行之前，之后正常任务元数据可能继续产生。
- 原Python3.9虚拟环境完整移至`~/.local/share/newquant/reliability/2026-11-11/venv-python39`；`backend/venv`指向已验证的`venv-311`。原配置未覆盖。
- 新后端保持`127.0.0.1:8000`，显式关闭启动改库，沿用原配置允许的调度；消息流水线及新采集/LLM开关仍默认关闭。真实前端继续使用`127.0.0.1:5173`。

恢复本次升级时，应先停止全部写进程，再用3.11环境执行`python scripts/deployment_database.py restore --manifest <上述manifest>`，恢复旧应用/环境并验证旧业务接口；该命令**未在真实主库执行**。完整备份/回滚说明见[运行手册](../reliability.md)。Alembic downgrade会删除新结构，不替代保留数据的恢复方案。

## 尚未关闭的运行门槛

- [迁移后行情质量报告](2026-11-11-post-reliability-market-data-quality.md)：截至20261110最近120个交易日无整日空白，但 **verified_pass_days=0，scoring_allowed=false**。权威历史证券分母、核心/量额完整度及冻结深/京样本的状态/代码有效期证据仍需补齐；没有自动放宽闸门或全面修复真实行情。
- ECS真实Docker构建/云端发布与生产灾难切换未执行；本地shell故障注入和真实PG测试不等于生产演练。CI配置已落地，未推送触发GitHub运行。
- 真实外部来源、付费LLM效果、移动端完整视觉及生产网络性能未全面验收。
- 公网服务端认证T03仍是独立前置；现有本地登录不保护业务API。
- 任务中断须核查后人工重试；不承诺业务副作用exactly-once。年度日历必须更新，缺失日期保守停止市场任务。
- 交易仍为按股账本，信号回测仍为事件后验收益；不自动推断计划交易归因或生成虚构组合回撤。

本轮源码与文档在上述分支本地提交；未自动推送、合并或部署云端。
