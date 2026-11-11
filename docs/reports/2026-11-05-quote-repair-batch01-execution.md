# 行情首批修复执行与质量复核

2026-11-05 已在当前本地 SQLite 主库完成首批修复：更新 3 条、新增 4 条、保护性跳过 1 条，未删除行情。批次校验和完整性检查通过；T02 仍未达标，不能开放市场宽度或反转评分。

## 执行范围与记录

主库为 `/Users/lijiajun/ai-coding/newQuant/backend/data/quant.db`。执行前确认没有运行中的后端、调度器及其他主库连接；全程没有启动同步器或新增收费来源。

本批仅涉及 `000099.SZ`、`000411.SZ`、`000547.SZ`、`603014.SH`，日期为 2026-10-08 至 2026-10-09。前三只证券在 10 月 8 日的已有不完整行被更新，四只在 10 月 9 日的缺失行被补入。三个更新行的 OHLC 不变，填补缺失核心字段及量额，两条成交量恢复小数精度；603014.SH 在 10 月 8 日因已有有效股本被保护性跳过，没有清空字段或跨来源拼接。

- 批次 ID：`50134166-d133-43e7-93f7-100b115dfc1c`
- 状态：`applied`，审计 7 条，`matches=true`、`audit_integrity=true`
- 核对文件 SHA256：`c96d2fb2b691b1ae6f9e693bec4e965936272667c3eed3084fc9ab0a4b5fdefe`
- 语义计划哈希：`4bfe15a09e78c8ee05fa0bfb070f1801a4d04f2191cdd8aecfb9f9bf6874bb6e`
- 行情总行数：1,924,041 → 1,924,045

[范围与风险核对](2026-11-05-quote-repair-batch01-review.md)、[逐字段差异计划](2026-11-05-quote-repair-batch01-plan.json)、[来源快照](2026-11-05-quote-repair-batch01-source.json)、[结构化执行证据](2026-11-05-quote-repair-batch01-result.json)已保留。旧样例计划与本批有重叠主键，不应再次执行。

## 备份与副本回滚演练

完整备份含已提交 WAL，保存在仓库外私有目录；目录权限 700，备份和清单文件 600。备份不进入 Git。

| 阶段 | 备份路径末段 | 文件 SHA256 |
|---|---|---|
| 迁移前不可变备份 | `pre-migration/5a2d7524-246e-4723-b99e-16150a56bcf1.db` | `b675463c7ff7477778c46b0480f3d6332ffd9230a50d2746e94eecfe91db80eb` |
| 审计表初始化前 | `schema-init/a098ad11-7251-4624-a3ec-d45ef7abc0a9.db` | `b675463c7ff7477778c46b0480f3d6332ffd9230a50d2746e94eecfe91db80eb` |
| 行情应用前 | `pre-apply/7e8d5821-948f-4d9f-a943-3d8f00bc9bab.db` | `c2c891793ef95ecf4fdda030f1bb4761410f724dc4f97aa317757d4241cd522d` |

以上路径前缀均为 `/Users/lijiajun/.local/share/newquant/quote-repair/2026-11-05/`，每份备份均附 `.manifest.json`。两次 CLI 写操作均先自动备份。SQLite 兼容初始化只新增 `daily_quote_repair_batch` 和 `daily_quote_repair_audit` 两表，行情行数保持不变，未 stamp 或执行 PostgreSQL 迁移。

先从不可变备份复制工作副本，生成单独绑定副本身份的计划，再执行完整应用、校验、新备份、批次回滚与再次校验。副本应用后为 1,924,045 行；回滚后恢复到原始 1,924,041 行及完全相同的行情全表指纹，7 条审计保留并标记回滚。原备份文件哈希未变。主库没有进行回滚演练，保持修复后的 `applied` 状态。

[副本演练原始证据](/Users/lijiajun/.local/share/newquant/quote-repair/2026-11-05/rehearsal/62f963be-f67c-4c8b-8784-cad23ab06e4c/rehearsal-report.json)位于私有目录。

## 全库一致性与业务影响

主库修复后行情全表指纹与副本应用后的预期完全一致，因此不只是检查了七条目标记录；范围外行情未发生额外改变。原有 28 张非行情业务表共 37,073 行，内容指纹全部保持不变。SQLite `integrity_check=ok`。

```text
修复前行情 SHA256  a3879ea15d79a3ae6ef14ecda7b6c092f0c64c1367d3d0aa68e4a84b9a108166
修复后行情 SHA256  5fc8f196a0a2957a700326e0e3bf4443c05a1adb60f8a8aa6e951572230495de
```

独立只读验收逐项核对了计划、审计、当前新值、备份清单和被跳过记录。603014.SH 在 10 月 8 日的整行与迁移前备份精确一致，`float_share=10148.4882` 保持原值。没有执行交易、生成提醒、重算派生策略结果或修改观察池。

## T02 修复前后对照

首先保持截止 2026-11-04、最近 120 个交易日的相同窗口比较；只有以下两个交易日的质量明细发生变化，其余 118 日与主数据诊断结果完全相同。

| 指标 | 10 月 8 日修复前后 | 10 月 9 日修复前后 |
|---|---|---|
| 行情行数 | 1,459 → 1,459 | 1,137 → 1,141 |
| 核心有效代码数 | 51 → 54 | 1,137 → 1,141 |
| 核心不完整代码数 | 1,408 → 1,405 | 0 → 0 |
| 成交额有效记录数 | 0 → 3 | 0 → 4 |

本批七条行情均通过核心字段及量额检查，但仅是试修，不是全市场完整度提升到合格水平。相同窗口仍有 13 个整日空缺、0 个已验证合格交易日，`scoring_allowed=false`。

再以截止 2026-11-05 的最新完整 120 日窗口复核：窗口为 2026-05-13 至 2026-11-05，整日空缺为 14 日，最新已有行情仍停留在 10 月 16 日；`scoring_allowed=false`。13 → 14 是新增检查 11 月 5 日这一缺失交易日所致，不是本次修复造成数据丢失。两次审计退出码均为 2，表示报告成功生成但质量未通过。

- [同窗口修复前报告](2026-11-05-pre-repair-market-data-quality.md)
- [同窗口修复后报告](2026-11-05-post-repair-market-data-quality.md)
- [截至 11 月 5 日的最新报告](2026-11-05-latest-market-data-quality.md)

同名 JSON 保存完整代码及字段明细。历史上市、退市、证券类型和停牌分母仍不足，真实市场覆盖率不可验证；不能用当前主数据候选清单冒充历史分母。

## 验证与恢复命令

本次修复、来源、备份、迁移与 T02 定向测试在 Python 3.12 环境为 89 passed；另外完成真实完整 SQLite 副本应用与回滚演练、主库应用后校验和全库内容对照。`git diff --check` 通过。本次没有修改业务实现代码；没有重跑前端/UI 测试，也未模拟生产并发写流量或执行主库文件级灾难恢复。

只读复核本批：

```bash
cd backend
DATABASE_URL=sqlite:////Users/lijiajun/ai-coding/newQuant/backend/data/quant.db \
  python scripts/repair_daily_quotes.py verify \
  --batch-id 50134166-d133-43e7-93f7-100b115dfc1c
```

如发现本批来源问题需恢复，先停止所有写任务，再使用以下批次回滚；命令将自动新建完整备份。该命令未在真实主库执行：

```bash
DATABASE_URL=sqlite:////Users/lijiajun/ai-coding/newQuant/backend/data/quant.db \
  python scripts/repair_daily_quotes.py rollback \
  --batch-id 50134166-d133-43e7-93f7-100b115dfc1c \
  --backup-dir /Users/lijiajun/.local/share/newquant/quote-repair/2026-11-05/rollback
```

恢复后再次运行 `verify` 和 T02。若涉及记录已有后续改动，不应强行覆盖；按审计链核对、逆序恢复。不要通过删除审计表、按日期删除重插或覆盖正在使用的 DB/WAL 撤销修复。

后续仍需分批修复其他不完整行情、补齐整日缺口及可靠历史证券分母。已有有效股本的保护记录继续保留，待所选来源能提供完整所需字段，或用户另行评审字段清空策略；本次没有放宽保护或自动扩批。
