# 全市场日线只读校验使用说明

T02 校验命令读取当前配置主库，生成 Markdown 报告和 JSON 质量快照。它不会启动应用、调度器、行情供应商或迁移，也不会写数据库。报告帮助判断行情是否足以支持市场宽度研究；缺少可靠证券分母时，覆盖率始终为 `null`，退出码为 2。

## 运行

在项目的 Python 3.11+ 环境中安装现有后端依赖，从 backend 运行：

```bash
python scripts/audit_market_data_quality.py \
  --end-date 20261104 \
  --calendar-csv data_reference/sse_calendar_2026.csv \
  --output-prefix ../docs/reports/2026-11-04-market-data-quality
```

默认 `--days 120`、`--detail-days 20`。省略截止日时，按上海时间 16:00 划分已完成日；精确交易日由输入日历决定。2026 年离线日历及公告出处见 [参考数据说明](../backend/data_reference/README.md)。它只描述交易所休市安排，不包含证券级停牌。

命令优先使用进程环境的 `DATABASE_URL`，其次读取 `backend/.env`，最后采用应用默认数据目录。相对 SQLite URL 默认按 backend 工作目录解析；应用若从其他目录启动，显式传入 `--app-cwd`，避免检查错库。不在命令行打印用户名、密码或完整连接串。检查结果仅证明当前配置连接的数据库，不能证明其他机器/容器的生产主库。

SQLite 使用 `mode=ro` 和 `PRAGMA query_only=ON`，不存在的路径直接失败。PostgreSQL 使用 `REPEATABLE READ`、`READ ONLY` 事务和 60 秒单语句超时。结束时回滚并关闭连接。源码不导入带 WAL/初始化副作用的 `app.database`。

## 独立输入

日历 CSV 必须覆盖每个自然日，不能只列已有行情日期：

```csv
trade_date,is_open
20261101,0
20261102,1
20261103,1
```

命令验证截止日覆盖、自然日连续性、重复日期和 0/1 状态，回溯选取所需交易日。没有日历时，仅生成工作日诊断网格，并将覆盖质量标记为不可验证。

可通过 `--universe-csv` 提供独立历史证券清单：

```csv
trade_date,ts_code,security_type,is_listed,is_trading
20261102,000001.SZ,a_share,1,1
20261102,600000.SH,a_share,1,0
20261102,000001.SH,index,1,1
```

每日分母为 `security_type=a_share`、`is_listed=1`、`is_trading=1` 的代码集合，全天停牌的代码填 `is_trading=0`；临时停牌但当天有正式交易仍填 1。历史退市、类型与停牌未知时不能伪填为 1。CSV 需包含每个检查日的完整独立证券状态，不能从当天收到的行情反推。

仅提交证券清单不能放行质量门槛；还需 `--universe-counts-csv` 提供独立来源的逐日控制总数，并按下节绑定证据：

```csv
trade_date,expected_count,source_url
20261102,5500,https://example.org/official-daily-universe
```

这里的 5500 仅是格式示例，实际总数必须与该日停牌剔除后的同口径权威统计一致。若清单交易代码数与控制总数不匹配，命令直接失败；不提供控制总数则为不可验证，不能通过评分门槛。证券类型只接受 `a_share/index/fund/bond/other`，代码须为规范六位交易所代码；A 股还须符合当前支持的代码规则。未知类型、空代码、重复或未上市却交易的状态直接拒绝，不通过忽略错误行缩小分母。来源 URL、输入路径和同一读取字节的 SHA-256 保存于 JSON。

### 证据清单与资格

从 `market-data-quality-v1.1.0` 起，匹配的控制总数只说明 `counts_match=true`。取得全市场结构资格还须同时提供：

```bash
python scripts/audit_market_data_quality.py \
  --end-date 20261110 --days 120 \
  --calendar-csv data_reference/sse_calendar_2026.csv \
  --universe-csv /private/evidence/universe.csv \
  --universe-counts-csv /private/evidence/counts.csv \
  --universe-evidence-manifest /private/evidence/manifest.json \
  --universe-evidence-sha256 <独立审阅后保存的manifest文件SHA256> \
  --output-prefix /private/reports/new-version
```

manifest 使用 `market-universe-evidence-v1`。声明 `scope=full_market_point_in_time` 或 `security_subset`、`temporal_basis=retrospective`、覆盖的 `dates`/`markets`，分母口径固定为 `listed_a_share_excluding_full_day_suspensions`。`universe_sha256`、`counts_sha256` 绑定实际解析的两个 CSV；`universe_source_ids`、`control_source_ids` 指向 `sources` 中的原件。

每个原件提供 `id`、无用户凭据的 HTTPS `url`、包内相对 `path`、`sha256`、带时区的 `observed_at` 和原文定位 `locator`。清单与控制来源不得复用 ID、URL 或同一原件内容；控制 CSV 的 URL 须属于控制来源。绝对路径、路径穿越、符号链接逃逸及缺失/变更原件均拒绝，不访问 URL、不自动抓取文件。

全市场资格要求 SH/SZ/BJ 范围、全部审计日期及同口径来源绑定。局部证据即使数量匹配也不能取得全市场资格。缺 manifest 的旧 CSV 继续生成诊断报告，但 `control_totals_verified=false`；已通过的旧报告不修改。日期或证券集合变化后不得复用旧资格摘要。

哈希只绑定字节，不能认证原文真实、范围声明正确或统计独立。人工仍须审阅原件与统计口径，不能把自己计算的 CSV 行数包装成独立控制总数。`retrospective` 表示事后历史事实审计，允许资料观察时间晚于交易日，不能据此声称资料在历史当时已可得。工具不解析公告或生成生命周期事件；两只证券的摘牌/代码映射材料仍是局部证据，不替代全市场历史清单与停复牌全集。

缺少该文件时，主数据中代码前缀近似符合普通 A 股、当前非退市且未明确晚于检查日上市的代码只形成诊断候选集合。未知上市日不会阻止观测字段校验，但不能使真实覆盖率变成已验证。缺失代码列表明确标记 `current_master_proxy`，可能含尚未上市、历史停牌或证券类型误分的代码。

## 输出与判读

| 输出 | 内容 |
|---|---|
| `.md` | 120 日统计表、最近 20 日摘要和限制 |
| `.json` | 数据库身份、日历/证券输入哈希、库存、每日完整率、最近 20 日完整代码明细 |
| `days[].missing_codes` | 行情缺失代码，按 `missing_list_basis` 解释 |
| `days[].invalid_rows` | 核心字段、OHLC 次序、非有限值、负量额和重复键问题 |
| `days[].missing_field_codes` | 每个字段缺失或数值非法的代码 |
| `unexpected_session_rows` | 日历窗口内、不属于所选交易日的行情记录 |

核心有效要求 OHLC 和前收为正有限数、涨跌幅为有限数，且 OHLC 上下界和前收/涨跌幅一致。数值字符串先归一化再比较，布尔值不作为数字。0 成交量/额可为完整有效值，但必须配对；按内部手/千元单位计算的均价须在日内价格区间。矛盾记录明确报告，任何量额一致性矛盾均关闭金额指标资格。字段完整率仍只是数值有效率，不替代市场覆盖率；`consistency` 另列可检查/不可检查及矛盾数量。供应商单位、复权和阶段的历史血缘不在现有表内，一致性检查也不能认证跨源可比性。

已提供独立日历与具有完整证据资格的证券池、有效核心代码覆盖率 ≥95%、各核心字段有效率 ≥99%、重复/异常代码占比 ≤0.1%，且没有证券清单外的意外 A 股代码时，该日才通过核心门槛。异常率分母使用实际观察到的 A 股集合，不被范围外指数/基金稀释。`amount_metrics_allowed` 还要求成交额 ≥95% 有效、至少 95% 观测行可检查量额与价格一致性，且无任何量额一致性矛盾；缺成交量不能凭成交额非空取得金额资格。合法零量零额配对可检查，无需计算均价。窗口金额资格要求全部逐日金额资格和窗口核心资格同时成立。有一天核心不通过，或有非法行情日期/休市日记录时，窗口级 `scoring_allowed=false`；金额不足也不会被包装成金额指标可用。核心字段资格不替代后续评分版本的全部质量条件。

JSON 与 Markdown 在完整渲染后独占创建，既有任一文件或符号链接均不会覆盖；失败时只清理本次拥有的新建文件。每次运行使用新前缀，并检查命令成功及两文件齐全。两个路径不构成跨文件原子提交，异常终止可能留下不完整的新报告，不能仅凭单个文件存在判断完成。

退出码：0 为本窗口门槛通过；2 为成功生成报告但质量失败/不可验证；1 为连接、结构或输入格式失败。退出码 2 是质量结论，并非脚本异常。

## 验证和数据库操作说明

```bash
python -m pytest -q tests/test_market_data_quality.py
```

测试覆盖只读拒写、缺库不创建、空交易日、停牌排除、未知分母、异常数值、重复键、缺列、日历连续性、配置优先级与连接凭据不泄漏。

本任务没有 schema 迁移或行情修复，不需要备份/恢复数据库。报告生成只写输出路径；删除生成的文件即可撤销报告。未来 T06–T08 实际写库时，需另做备份、dry-run、逐字段审计和批次回滚。
