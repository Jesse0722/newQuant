# 可靠性运行与验收

更新：2026-11-11。适用于 SQLite MVP 和 PostgreSQL 主库；全部业务仍使用同一个 `DATABASE_URL`。

## 环境与检查

Python 基线为 3.11。`backend/requirements.lock` 固定本轮验证的依赖，避免新建环境无意升级业务库的大版本。

```bash
uv python install 3.11
uv venv --python 3.11 backend/venv
uv pip sync --python backend/venv/bin/python backend/requirements.lock
cd backend
AUTO_INIT_DB=false AUTO_START_SCHEDULER=false SCHEDULER_ENABLED=false ./venv/bin/python -m pytest -q
```

默认测试使用临时库、mock 行情和 LLM，不进行真实采集。PostgreSQL 集成测试还需独立、可创建测试数据库/临时 schema 的测试账号，绝不能填生产连接：

```bash
export QUOTE_REPAIR_POSTGRES_ADMIN_URL=postgresql+psycopg://test_user:test_password@127.0.0.1:5432/postgres
export RUNTIME_POSTGRES_TEST_URL="$QUOTE_REPAIR_POSTGRES_ADMIN_URL"
cd backend
./venv/bin/python -m pytest -q --run-integration tests/test_postgres_reliability.py tests/test_quote_repair_postgres.py tests/test_runtime_postgres.py
```

前端 `npm run lint`、`npm run build`、`npm run test:e2e`；浏览器测试使用独立 4177 端口及显式 API mock，不连接已有开发后端。首次需要 `npx playwright install chromium`。

## 数据库升级、备份与回滚

新增两个 Alembic revision：

- `2a1e7c90b311`：补齐消息证据三表和机会复核七列及索引。
- `3b2f8da1c422`：持久任务、调度租约/运行记录、产业日报输入快照及原始响应。

升级是增量操作，不清理历史业务行。SQLite 旧启动方式仍有幂等兼容迁移；正式运行建议显式迁移并关闭启动自动改库。

1. 停止 Web、独立调度器及其他写任务。
2. `python scripts/deployment_database.py backup --directory /private/persistent/backups`，保留返回的 manifest 路径及备份文件。
3. 对没有 Alembic 版本的完整旧库运行 `python scripts/adopt_legacy_schema.py`。此命令核对 baseline 列、类型、主键、非空、唯一及外键后才 stamp；陌生/缺损结构拒绝自动接管。已版本化库通常不重新 stamp；若已记录 baseline 但曾用显式 SQLite 修复脚本创建审计表，会先完整校验该两表的类型/非空/主键/唯一/外键再将版本对齐至审计 revision，不在此步骤重写其他旧约束。
4. `python -m alembic -c ../alembic.ini upgrade head`。
5. `python scripts/deployment_database.py check`，启动后再检查 `/api/ready` 以及只读业务接口。

恢复命令：`python scripts/deployment_database.py restore --manifest /path/to/backup.manifest.json`。恢复前仍须停止所有写任务。命令检查目标身份、文件哈希及格式；SQLite 使用 backup API 处理 WAL；PostgreSQL 在一个事务中重建专用 `public` schema 并恢复，失败整体回滚，避免升级新增表和外键妨碍旧备份恢复。自动 PG 恢复仅支持只含 `public` 业务 schema 的独立应用库；共享/多业务 schema 库须单独制定恢复方案。恢复后验证行情全表指纹，并使用旧应用版本进行业务检查。

Alembic downgrade 会删除对应的新证据/任务/审计结构，不能当作无损数据恢复；应先备份。需要保留新期间数据时，应先导出再决定恢复范围。

SQLite→PG 数据复制使用单一只读源快照及一个目标事务；后续表失败会撤销此前复制和显式清空。默认拒绝非空目标，`--truncate` 必须先有备份；按表精确核对行数，保留原有旧孤儿提醒清理说明。

## 任务与调度

- `background_task` 保存状态、进度、结果、owner 和心跳；结果查询不依赖当前进程内存。
- 心跳超时将任务置为 `interrupted`，不自动重放可能有副作用的业务操作。先核查结果再人工重试。
- 默认心跳过期 120 秒、终态保留 30 天；内存终态有数量上限。配置见 `.env.example`。
- 调度器使用数据库租约和唯一 job/slot；Web 和独立进程即使同时启动，也不能重复认领同一个时隙。
- 采用上海时间与离线交易日历。缺失年份/日期时市场任务停止，不能按工作日猜测；跨年之前更新日历。
- 错过日任务默认 `skip`；可显式设 `SCHEDULER_MISFIRE_POLICY=catch_up`，只补当天宽限窗口内的日任务，盘中扫描不补跑。失败/中断时隙不自动再次执行。
- `scheduled_job_run` 默认保留 90 天；`/api/sync/tasks/recent` 汇合后台任务、同步日志和调度结果。
- 前端查询失败保持任务跟踪并退避重试；真正的 failed/interrupted/cancelled 才结束，保留结果和跳转入口。

## 消息、AI 与研究口径

- 消息消费排除 demo/ignored/dismissed；模型输出须通过严格结构、证券映射和原文锚定检查。摘要与原文分开存储。
- 官方反证降低候选等级并进入风险观察；仅社媒、仅种子映射和 mentions 路径有评级上限。种子关联不代表当日事件。
- LLM 清洗单条失败使用 savepoint 隔离；坏 JSON/引用不支持回退规则并留痕，不回滚此前成功项。
- 清洗/抽取按输入摘要和版本去重；默认同输入连续失败三次后停止自动尝试，显式 force 才再次执行。
- 日报及每次重生成保存输入、原始响应、版本、错误；人工复核原因保留，自动重聚合可更新计算字段，accepted/dismissed 不被自动覆盖。
- 独立 Entity Mapping Agent 输出 `matched_terms`、`mapping_path` 和强弱映射；弱/多义映射待复核。
- 流水线由 `MESSAGE_PIPELINE_ENABLED` 控制，采集及 LLM 另有独立开关，默认全部关闭；限量、逐阶段失败隔离。未启用时不调用外部来源。
- 离线语料评测属于校验器/规则回归，不等于真实模型质量评测。命令：`python -m pytest -q -s tests/test_message_reliability.py::test_offline_quality_metrics`。
- 交易记录仍是股票累计账本；`actual_pnl` 为当前累计现金流，`review_pnl_snapshot` 为复盘提交时保存的旧值，不宣称计划级交易归因。
- 现有信号回测为事件后验收益；`worst_return_5d` 为最差单笔五日收益，`max_drawdown=null`。未定义权益曲线、可执行成交与成本前，不展示策略最大回撤。

## 行情与发布边界

普通行情写入校验证券、日期、价格核心字段及 OHLC；已有坏行不被普通同步自动覆盖。量额缺失留 NULL 并标记，不将源错误当作筛选零结果。已有主数据的上市日期、行业、股本不被空快照清掉；非权威状态不能覆盖已知状态。

新修复快照必须包含上游实际代码/市场/日期身份与响应指纹，CLI 不接收不完整冻结批次。未应用的旧计划不能绕过身份门槛；旧批次仍可 verify/rollback。真实历史证券分母、上市/退市、停牌与代码有效期证据仍需外部权威资料，软件校验不能补造。数据不足时不放行市场状态评分。

GitHub PR 和部署均经过后端、真实 PG、前端 lint/build、浏览器回归门禁。发布绑定通过检查的 SHA、串行执行；先构建，再维护窗口完整备份、迁移、readiness/消息 smoke，失败恢复备份和旧镜像。发布采用独立 release 目录，保留原 checkout 和回滚镜像。workflow 从通过检查的提交直接读取发布脚本，避免远端旧脚本绕过新保护；本地测试不代表已部署 ECS。

服务端认证属于公网使用前独立门槛；当前前端本地登录不能保护 API。本轮不把它标记为已完成。
