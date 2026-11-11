# 行情修复差异计划

- 计划：979c4b28-787e-43b2-930d-bd36efcb984e
- 目标库：`{'dialect': 'sqlite', 'database': '/Users/lijiajun/ai-coding/newQuant/backend/data/quant.db'}`
- 权威来源：baostock，不复权正式日线
- 汇总：{'updates': 0, 'inserts': 1, 'unchanged': 0, 'skipped': 1, 'requested_cells': 2}
- 旧行情来源未知；新行全部字段来自本次同一个来源。缺少已有附加字段时默认跳过整条修复。

| 股票 | 日期 | 操作 | 变化字段 |
|---|---|---|---|
| 603014.SH | 20261009 | insert | open, high, low, close, pre_close, change, pct_chg, vol, amount, turnover_rate, float_share |

JSON 含所有逐字段新旧值、哈希、原始来源和跳过原因；本摘要最多显示前 1000 条。
应用前核对 JSON；apply 只执行该计划，不会重新联网选取其他行情。
