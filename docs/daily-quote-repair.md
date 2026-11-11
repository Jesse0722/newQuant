# T07/T08 行情修复、审计与回滚手册

本流程只修复研究行情，不执行交易。默认先采集离线快照、只读生成差异，再由操作者核对计划。修复工具不启动应用或调度器，不自动改写历史行情，也不会根据空响应删除行情。

SQLite 既有的 `AUTO_INIT_DB=true` 启动流程会通过 `Base.metadata.create_all` 创建缺失表，包括空的修复审计表；本次没有新增启动迁移 runner。空审计表不代表已备份或已执行修复，正式操作仍应遵循以下显式备份与初始化流程。PostgreSQL 使用 Alembic 管理 schema。

## 口径与保护边界

- 内部日线单位：`vol=手`、`amount=千元`，价格不复权。BaoStock 原始股/元换算；AkShare 原始手/元换算；Tushare 原始手/千元保持不变。
- 每条新行情整体来自一个明确选定的来源；不从不同来源补字段。快照保留原始值、单位、阶段、采集时间；审计保存每条记录的新旧值、变化字段、原始来源和校验和。旧行情原始来源未知，不能补造历史血缘。
- 修复需要有效 OHLC、前收、涨跌幅、成交量及成交额，并检查价格顺序与涨跌幅一致性。仅接受盘后正式、不复权数据；日期来自覆盖整个请求区间的交易日历，而不是只遍历库内日期，因此可以回补整日缺失。
- 新来源缺失已有有效换手率或股本时，默认跳过整条记录。只有在明确接受清空这两个字段时，才在生成计划时指定 `--allow-clear-optional`；不得为了提高完成率默认启用。
- 证券清单默认来自当前主数据，仅是诊断范围，不是历史上市、退市及停牌的点时分母。缺失源数据可能是停牌，也可能是源失败，不能自动认定应当删除。
- 普通同步及 K 线兜底写入也统一量额单位；已有行不因此自动改写。原始叶子适配器保持源单位，避免修复快照被重复换算。

## 执行前检查

使用 Python 3.11+，在仓库根目录运行以下命令；`DATABASE_URL` 使用显式进程环境变量优先，否则读取 `backend/.env`。SQLite 相对路径以 `backend` 为基准。先确认输出计划中的 `database_identity`，不要把密码或完整 DSN 写入报告。

正式应用或回滚前停止同步、定时任务和其他写库进程，按小窗口分批操作。应用事务内使用 SQLite `BEGIN IMMEDIATE` 或 PostgreSQL 行情表写锁，并设超时；采集、备份等网络/外部工作不放进写事务。全表行情指纹需要扫描现有行情，数据量大时应预留维护窗口。备份后任意行情变化都会拒绝执行，需重新备份；计划涉及的旧值变化则需要重新生成并核对计划。

先在脱敏副本演练完整流程。PostgreSQL 备份要求本机安装兼容版本的 `pg_dump` / `pg_restore`；凭证不进入命令行参数。

## 1. 采集快照：只读业务库

```bash
cd backend
python scripts/repair_daily_quotes.py fetch \
  --source baostock --from-date 20261008 --to-date 20261009 \
  --codes 603014.SH --output /tmp/quote-source.json
```

可选 `--calendar-csv` 指定覆盖区间的权威交易日历。内置日历位于 `backend/data_reference/`。默认最多 50,000 个证券×交易日单元，可显式调整 `--max-target-rows`，上限 1,000,000；每次最多 250 个交易日。只使用当前配置启用的可靠来源，不隐式启用 Tushare 或购买权限。不支持的交易所、空数据和请求失败独立记录；部分成功返回退出码 2，但仍保留有效原始数据用于人工核查。

## 2. 生成和核对差异：只读 dry-run

```bash
python scripts/repair_daily_quotes.py plan \
  --snapshot /tmp/quote-source.json --output /tmp/quote-plan.json
```

生成 JSON 与同名 Markdown 摘要。JSON 是执行依据，含逐字段新旧值、来源与跳过原因；摘要最多显示前 1,000 条。文件独占创建，不能覆盖已核对计划。核查主库身份、来源单位、证券/日期范围、更新/新增条数、字段丢失和异常价格，再保留命令输出的 `plan_sha256`。源全部失败或无有效数据不能生成可执行计划。

## 3. 初始化审计表：显式迁移、先备份

SQLite（仅在尚无审计表时）：

```bash
python scripts/repair_daily_quotes.py init-audit-schema --backup-dir /secure/quote-backups
```

只创建 `daily_quote_repair_batch` 和 `daily_quote_repair_audit` 两张表；不会重建或覆盖现有行情表。目标文件必须存在。兼容迁移 helper 不负责备份，实际操作优先使用上述 CLI。

PostgreSQL：先按[主库运行手册](development-postgresql.md)独立备份，再在仓库根目录通过 Alembic 增量升级：

```bash
python -m alembic -c alembic.ini upgrade head
```

本次审计迁移版本 `1f4b0c7d9e2a`，前序为 `c4647a9160ea`。它只补本次两张表，不代表 T01 的消息模块迁移缺口已经解决。已有库不能未经核对直接 stamp baseline。

## 4. 应用已核对计划

```bash
python scripts/repair_daily_quotes.py apply --plan /tmp/quote-plan.json \
  --plan-sha256 <核对时保存的SHA256> --backup-dir /secure/quote-backups
python scripts/repair_daily_quotes.py verify --batch-id <返回的batch_id>
```

CLI 从同一次文件读取校验 SHA-256 并解析，不重新联网选取数据。先自动生成完整数据库备份和 `.manifest.json`，再验证目标身份、文件校验和及备份时的行情行数/全表指纹。SQLite 使用在线备份，包含 WAL 中已提交数据；PostgreSQL 使用导出快照绑定的 custom-format dump。

行情与审计在同一事务提交，应用前后验证涉及记录的哈希与总行数。任何冲突、写入或审计错误均整批回滚，其他已完成批次不受影响。不要将一个超大范围拆成逐行提交。同一计划再次应用返回 `already_applied`；已经回滚的计划不得重用，需生成新计划。

批次记录语义计划哈希与操作者核对的文件字节 SHA-256，两者用途不同；API 内部调用者应自行保存并传入核对哈希。备份包含业务数据，应按私有数据存储，不提交 Git。

## 5. 按批次回滚与恢复校验

```bash
python scripts/repair_daily_quotes.py rollback \
  --batch-id <batch_id> --backup-dir /secure/quote-backups
python scripts/repair_daily_quotes.py verify --batch-id <batch_id>
```

回滚前再次完整备份。系统先验证审计数量、顺序、来源、全量审计摘要及当前行情仍等于本批次新值，然后恢复更新行的原值，只删除本批次新增的主键；绝不按日期批量删除。任一涉及记录被后续任务修改时整批拒绝回滚，需先核对后续批次，通常按逆序恢复。审计记录保留，标记 `rolled_back`；重复回滚返回 `already_rolled_back`。

`verify` 只读验证批次审计与当前值；回滚后按旧值校验，新增行应不存在。它不等于全市场质量验收：完成后仍需重跑 T02 的[只读质量校验](market-data-quality-audit.md)，检查覆盖率与字段完整度。

## 退出码与失败处理

| 场景 | 退出码/处理 |
|---|---|
| 成功、已应用/已回滚、无差异 | 0 |
| 配置、计划哈希、备份、审计或并发冲突 | 1；检查原因，不跳过安全检查 |
| fetch 部分成功/空数据/失败/不支持，或 verify 不匹配 | 2；保留工件核对，不能按全量成功继续 |

正常恢复优先使用批次回滚；全库备份仅用于灾难恢复，必须停写并先备份当前状态。SQLite 恢复到新的文件路径后执行 `PRAGMA integrity_check`、行数/业务检查，再调整连接配置，不直接覆盖正在使用的 DB/WAL。PostgreSQL 将 custom dump 用 `pg_restore --exit-on-error` 恢复到新建临时库，验证后再安排主库切换，不用 `--clean` 覆盖现有业务库。全库恢复会退回备份后的其他业务写入，不能替代无冲突的批次回滚。

如需撤销 schema：先导出并归档批次与审计，确认没有需要恢复的批次，再审慎降级到前序版本；降级会删除审计两表，不能撤销行情修改。代码回退同样不撤销已提交数据。旧 `repair_daily_quote_from_tushare.py` 现仅转发到新 CLI；原按日删除重插参数已停用，不能继续沿用旧命令。
