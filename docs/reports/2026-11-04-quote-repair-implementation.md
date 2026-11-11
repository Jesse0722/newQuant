# T07/T08 实施与验证记录

日期：2026-11-04。状态：工具与隔离库演练完成，真实业务库尚未迁移或应用修复。

## 交付范围

- 新 CLI `backend/scripts/repair_daily_quotes.py`：`fetch → plan → init-audit-schema → apply → verify / rollback`。旧 Tushare 删除重插脚本退役为安全转发入口。
- 单一来源、不复权、盘后正式行情；统一成交量为手、成交额为千元。普通同步和 K 线兜底写入一并统一单位，原始适配器保留源单位。
- 离线快照与只读逐字段计划；计划文件 SHA-256 绑定、不可覆盖工件、原始来源血缘、已有附加字段丢失保护。
- SQLite 在线备份和 PostgreSQL 一致性快照 custom dump，附凭证脱敏的备份清单、文件校验和与全表行情指纹。
- 批次及逐行审计两表、显式 SQLite 迁移与 Alembic `1f4b0c7d9e2a`；不加入自动启动迁移。
- 应用/审计同事务、并发冲突拒绝、提交前回读审计验证、重复应用幂等；回滚恢复更新前整行值，仅删除本批次新增主键，保留审计。

操作、备份、迁移和恢复命令见[运行手册](../daily-quote-repair.md)。本次未引入自动交易、评分规则或新收费来源。

## 真实业务库：仅只读样例

当前配置目标为 `backend/data/quant.db`。未在该库创建审计表、未运行 apply/rollback，也未启动批量回补。

选取 `603014.SH`、2026-10-08 至 2026-10-09，从已配置的 BaoStock 取得 2 条有效正式行情：

- [原始来源快照](2026-11-04-quote-repair-sample-source.json)
- [完整逐字段计划](2026-11-04-quote-repair-sample-plan.json)
- [可读摘要](2026-11-04-quote-repair-sample-plan.md)

结果为新增 1 条、更新 0 条、保护性跳过 1 条：10 月 9 日缺失行可补入；10 月 8 日来源缺少已有 `float_share`，默认跳过整行，未静默丢弃股本字段。这是候选计划，不是已完成修复或全市场质量达标证明。

工件 SHA-256：

```text
source  521fb595c75e399a8fc781996612e93e5dd5b15bb93cff94e2b0c363f54cf8ce
plan    282f91e2e194ac9df536fb00d6e3b27536bd63d4fa9298e4f4a2c55b47fa2c78
```

业务库执行前后 SHA-256 一致（包含 WAL，避免仅检查主文件漏掉写入）：

```text
quant.db      4e53da058f99165ac5072ba73d383e64d3aadba97a378e2f637690fe74db32b6
quant.db-wal  373a57f54488d13ac54c4eaf47405e8aec053e234491243f9f972dd400f2d452
```

## 自动化验证

| 验证 | 结果 |
|---|---|
| 当前 `backend/venv` 全量 `pytest -q` | 228 passed，1 skipped，1 已知 T04 failure |
| 隔离 Python 3.12.14：修复/备份/来源/迁移/单位/适配器/T06 定向套件及真实 PG 测试 | 113 passed |
| 临时 PostgreSQL 16 实测 | Alembic upgrade、pg_dump、应用、校验、批次回滚、pg_restore 到第二临时库、迁移降级均通过 |
| 最终独立只读复审 | 未发现剩余可复现阻断或高风险问题 |
| `git diff --check` | 通过 |

真实 PG 测试只创建随机命名的 `newquant_repair_test_*` 隔离库，结束后清理；没有连接或变更业务 PG 库。测试命令从 `backend` 执行，指定本机隔离测试管理员连接：

```bash
QUOTE_REPAIR_POSTGRES_ADMIN_URL=<隔离PG管理员URL> \
  python -m pytest -q --run-integration tests/test_quote_repair_postgres.py
```

覆盖失败路径：空源/错误代码/重复源行/非法价格或量额不能冒充成功；计划哈希及来源篡改拒绝；缺失/损坏/错误目标备份拒绝；备份后任意行情变化拒绝；涉及行后续改动拒绝恢复；审计失败或静默篡改整批回滚；审计记录缺失/来源/差异清单篡改拒绝；SQLite 历史非有限值及非法文本可原样恢复；计划文件读取时替换不能绕过字节哈希；不存在的 SQLite 目标不会被误建。

已知非本任务问题：`test_query_messages_promotes_capacity_order_value_signals` 使用固定 2026-05 日期，而查询只取当前最近 45 天，T04 仍未修复。当前主虚拟环境是 Python 3.9.6，并有 LibreSSL 警告，T05 仍需推进。Python 3.12 隔离环境初次收集 chart API 测试因最新版 Starlette 缺少 `httpx2` 而中断；最终 3.12 定向集合未含该 API 文件，chart API 已在现有环境的全量测试中通过，未改仓库依赖来掩盖环境问题。

## 尚未验收与后续顺序

1. 真实主库的审计表初始化、全量备份/恢复演练与实际行情修复均未执行；需要维护窗口和人工核对计划。
2. BaoStock 缺股本时会保护性跳过已有有效股本记录。应选择能提供所需整行字段的已授权来源，或明确评审清空附加字段的代价；不得默认开启 `--allow-clear-optional`。
3. 缺上市/退市/停牌点时分母的问题未由本任务解决。修复后必须重跑 T02，再判定是否可以推进市场宽度与反转评分。
4. 全表指纹与备份的真实大库耗时、生产并发写入及生产恢复切换尚未验收。大范围任务应分日期/证券窗口；一个批次失败不会撤销其他已完成批次。
5. 本任务没有修改前端；未重新运行浏览器/UI 测试，也没有覆盖所有供应商和交易所的真实网络行情。免费源不可用时应停止或保留部分结果，不能虚构覆盖率。

回退代码不撤销已经提交的数据；回滚优先使用批次恢复。全库备份恢复和删除审计表的风险、验证及安全顺序详见运行手册。
