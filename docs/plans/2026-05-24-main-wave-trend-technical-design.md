# 主升浪趋势策略技术方案

> 目标：在现有观察池、买点雷达和策略回测体系上，新增“主升浪样本库 + 主升浪趋势策略”。第一阶段先沉淀板块/题材数据底座，支持后续计算个股与题材共振。

## 一、策略目标

主升浪策略不追求最低点，而是识别：

- 已经被资金证明的强趋势个股
- 与市场核心题材或行业板块共振的个股
- 趋势尚未有效走坏，或跌破 MA20 后能快速修复的个股

策略输出不是简单“买/不买”，而是趋势生命周期状态：

| 状态 | 含义 |
| --- | --- |
| `watching` | 趋势观察，结构开始转强 |
| `breakout_tracking` | 放量突破，等待回踩确认 |
| `main_wave_confirmed` | 主升确认，趋势和板块共振较强 |
| `accelerating_hot` | 加速过热，持有优先，追买风险提高 |
| `divergence_warning` | 分歧预警，观察修复 |
| `exit_signal` | 有效走坏，退出或降级 |

## 二、量化框架

第一版策略 ID：`main_wave_trend_v1`。

总评分由四部分组成：

| 模块 | 权重 | 说明 |
| --- | ---: | --- |
| 个股趋势强度 | 40 | 均线多头、突破新高、涨幅排名、MA20 斜率 |
| 主升结构质量 | 25 | 放量突破、突破后不跌回、沿 MA5/MA10 推进 |
| 回调与修复质量 | 20 | 回调幅度、缩量、跌破 MA20 后能否快速收回 |
| 板块题材共振 | 15 | 板块趋势、涨停热度、个股相对板块强弱 |

### 2.1 个股趋势强度

- 收盘价 > MA20
- MA5 > MA10 > MA20
- MA20 近 10 日上行
- 近 20 日创新高
- 近 60 日涨幅处于样本前列

### 2.2 主升结构质量

- 近 20 日内放量突破 60 日新高
- 突破日成交量 >= 过去 20 日均量 1.5 倍
- 突破后未跌回突破价下方超过 3%
- 近 10 日多数收盘在 MA5/MA10 上方

### 2.3 回调与修复质量

MA20 是趋势生命线，但不是机械止损线。策略应区分“单日跌破”和“有效跌破”。

`ma20_state`：

| 状态 | 规则 |
| --- | --- |
| `above` | 收盘在 MA20 上方 |
| `break_warning` | 单日跌破 MA20，等待确认 |
| `repaired` | 跌破后 3 日内重新收盘站上 MA20 |
| `effective_break` | 连续低于 MA20、跌破超过阈值、或反抽不过 |

有效跌破定义：

- 连续 3 日收盘低于 MA20
- 或收盘低于 MA20 超过 5%
- 或放量大阴跌破 MA20 且次日不能收回
- 或跌破后 3 个交易日内没有重新站上 MA20

### 2.4 板块题材共振

核心判断：

- 板块强，个股更强
- 板块回调，个股少跌
- 板块修复，个股先涨

关键指标：

```text
relative_strength = 个股近20日涨幅 - 板块近20日涨幅
sync_ratio = 近20日个股与板块同涨天数 / 20
beta_up = 板块上涨日个股平均涨幅 / 板块平均涨幅
drawdown_advantage = 板块最大回撤 - 个股最大回撤
```

## 三、数据依赖

### 3.1 现有已支持

| 数据 | 表/来源 | 用途 |
| --- | --- | --- |
| 个股日 K | `daily_quote` | 个股趋势、突破、回调、修复 |
| 换手率 | `daily_quote.turnover_rate` | 量价结构 |
| 流通股本 | `stock_basic.float_share` / `daily_quote.float_share` | 流通市值过滤 |
| 行业 | `stock_basic.industry` | 基础行业归属 |
| 涨停板块/连板天梯 | `limit_market_board_service` 即时数据 | 短线情绪展示 |
| 个股概念标签 | 东方财富 F10 / `stock_sector_map` | 当前主升浪池已落库，用于概念候选 |

### 3.2 第一阶段新增

| 表 | 说明 |
| --- | --- |
| `sector_basic` | 板块/概念/行业基础信息 |
| `stock_sector_map` | 个股与板块关系 |
| `sector_daily_quote` | 板块历史日 K |
| `sector_quote_sync_state` | 板块 K 线补齐状态、覆盖率、失败重试和冷却信息 |

数据源采用东方财富同源口径，板块代码统一保存为 `BKxxxx`：

- 个股概念识别：东方财富 F10 `CoreConception/PageAjax`
- 概念板块 K 线：东方财富 `push2his.eastmoney.com/api/qt/stock/kline/get`
- 板块 `secid`：`90.BKxxxx`
- 当前池个股-概念映射：优先使用 F10 概念关系落库

说明：曾调研 AkShare EM 和同花顺 THS。AkShare EM 本质也是东方财富接口包装；THS 板块 K 线可用但成分/概念名与东方财富不完全同源，因此不作为主数据口径。

## 四、接口设计

第一阶段新增接口：

| 接口 | 说明 |
| --- | --- |
| `POST /api/market/sectors/sync` | 同步板块基础、成分和日线 |
| `GET /api/market/sectors` | 查询板块列表 |
| `GET /api/market/sectors/{sector_code}/quotes` | 查询板块日线 |
| `GET /api/market/stocks/{ts_code}/sectors` | 查询个股所属板块 |
| `GET /api/market/stocks/{ts_code}/main-wave` | 查询单只股票主升浪评分 |
| `GET /api/market/main-wave/scan` | 批量扫描观察池主升浪评分 |
| `GET /api/market/main-wave/sectors/backfill/status` | 查询主升浪池概念板块 K 线补齐状态 |
| `POST /api/market/main-wave/sectors/backfill` | 启动板块 K 线补齐后台任务 |
| `GET /api/market/main-wave/sectors/backfill/tasks/{task_id}` | 查询补齐任务进度和结果 |

## 五、实施分期

### 第一阶段：板块数据底座

- 新增板块表和板块 K 线同步状态表
- 新增同步服务和 API
- 支持概念/行业板块基础、成分、日线落库

### 第二阶段：主升浪评分服务

- 新增 `main_wave_service.py`
- 计算个股趋势评分、MA20 修复状态、板块共振评分
- 注册 `main_wave_trend_v1`

### 第三阶段：样本库与前端视图

- 建立“主升浪样本库”观察池
- 展示趋势阶段、评分拆解、板块共振、退出状态
- 支持样本复盘字段沉淀

### 第四阶段：回测

- 统计主升确认后的 5/10/20 日收益
- 统计最大回撤、有效跌破 MA20 后表现、修复成功率
- 比较“单看个股趋势”和“叠加板块共振”的效果差异

## 六、当前实现状态

截至 2026-05-24，已完成以下内容。

### 6.1 后端

- 新增板块数据模型：
  - `SectorBasic`
  - `StockSectorMap`
  - `SectorDailyQuote`
  - `SectorQuoteSyncState`
- 新增迁移脚本：`backend/scripts/migrate_sector_data.py`
- 新增东方财富板块数据服务：`backend/app/services/sector_data_service.py`
- 新增主升浪评分服务：`backend/app/services/main_wave_service.py`
- 新增主升浪板块 K 线补齐服务：`backend/app/services/main_wave_sector_backfill_service.py`
- 新增补齐脚本：`backend/scripts/backfill_main_wave_sector_quotes.py`
- 新增市场接口：`backend/app/routers/market.py`

### 6.2 前端

- 新增主升浪研究面板：`frontend/src/pages/Pools/MainWaveResearchPanel.tsx`
- 新增市场 API 客户端：`frontend/src/api/market.ts`
- 观察池页面支持：
  - 名称/描述包含“主升浪”的股票池自动进入主升浪研究视图
  - URL 支持 `/pools/:poolId`，刷新后可定位当前股票池
  - 主升浪池隐藏左侧股票列表，使用研究视图表格作为主操作面

### 6.3 当前主升浪池数据状态

当前主升浪观察池：

- `pool_id`: `59f717fa-f741-4a13-a8ef-255e505e0b11`
- 股票数：10
- 已识别概念数：7
- 当前池个股-概念映射：10 条
- 概念板块 K 线：0/250

已识别的东方财富概念：

| 概念代码 | 概念名称 | 关联股票 |
| --- | --- | --- |
| `BK1137` | 存储芯片 | `301379.SZ`, `600667.SH` |
| `BK0891` | 国产芯片 | `600353.SH`, `603629.SH` |
| `BK0917` | 半导体概念 | `688268.SH` |
| `BK1184` | 人形机器人 | `603667.SH`, `300503.SZ` |
| `BK1128` | CPO概念 | `603220.SH` |
| `BK0921` | 卫星互联网 | `300885.SZ` |
| `BK1134` | 算力概念 | `300209.SZ` |

## 七、板块 K 线补齐策略

主升浪策略依赖“个股 + 概念板块”的共振关系。当前设计不是每次临时抓数据，而是持续沉淀板块日 K 到本地数据库。

### 7.1 存量补齐

目标是为当前主升浪池涉及的概念板块补齐最近 250 个交易日：

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
PYTHONUNBUFFERED=1 ./venv/bin/python scripts/backfill_main_wave_sector_quotes.py --skip-sector-list
```

脚本行为：

- 自动识别主升浪池相关概念
- 已满足 250 日覆盖的板块自动跳过
- 未到重试时间的冷却项自动跳过
- 失败后写入 `sector_quote_sync_state`
- 成功后更新 `quote_count`、`first_trade_date`、`last_trade_date`

### 7.2 增量同步

存量补齐完成后，每天只需要补最近增量：

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
PYTHONUNBUFFERED=1 ./venv/bin/python scripts/backfill_main_wave_sector_quotes.py --skip-sector-list --mode incremental
```

增量模式会从已有 `last_trade_date` 向前回看 10 天，避免漏掉复权或迟到数据。

### 7.3 前端任务化

主升浪面板提供三个入口：

| 按钮 | 行为 |
| --- | --- |
| 补齐K线 | 启动 `backfill` 任务，补足 250 日存量 |
| 重试失败 | 强制忽略冷却状态，重试失败项 |
| 同步增量 | 启动 `incremental` 任务，只补增量 |

面板会展示：

- 概念数
- 完成数
- 冷却数
- 当前池股票映射数
- 每个概念的 `quote_count / target_days`
- 任务进度和失败原因

## 八、已知限制

### 8.1 东方财富行情域当前不可用

当前机器访问以下接口会出现空响应：

```text
https://push2his.eastmoney.com/api/qt/stock/kline/get
```

表现：

- 浏览器：`ERR_EMPTY_RESPONSE`
- 后端：`Remote end closed connection without response`
- `stock-sdk` 同样失败，说明不是本项目参数拼接问题，而是当前出口到东方财富行情域不稳定或被风控。

因此目前：

- 个股-概念映射已落库
- 概念 K 线尚未落库
- 板块共振分暂时为 0
- 页面会提示“板块K线缺失，暂无法计算共振强度”

### 8.2 Tushare 备用链路暂不可用

曾测试 Tushare 东方财富 DC 接口：

- `dc_index`
- `dc_concept_cons`
- `dc_member`

当前本地 token 返回“token 不对”，暂不能作为生产备用源。

### 8.3 全量概念成分暂未完成

当前系统为主升浪池写入“当前池股票 -> 概念”的 F10 映射。东方财富 `push2` 全量成分接口当前同样不稳定，因此还没有建立“所有概念 -> 全量成分股”数据库。

这不影响当前主升浪样本库，但会影响未来做全市场题材共振选股。

### 8.4 指定观察池的概念备用链路

当用户在策略选股中同时指定“观察池 + 概念板块”时，系统不再只依赖板块全量成分接口。

当前备用顺序：

1. 优先读取本地 `stock_sector_map`。
2. 本地为空时，尝试东方财富板块成分接口补齐。
3. 若仍无观察池交集，则对观察池内股票按概念名关键词预筛，再逐只通过东方财富 F10 反查概念并写入局部映射。

该备用链路适合“涨停观察池 + 绿色电力”这类有限范围扫描；全市场扫描不会逐只 F10 反查，避免任务过慢和触发外部风控。

## 九、验证记录

最近一次完整验证：

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
./venv/bin/pytest -q
```

结果：

```text
66 passed, 2 warnings
```

前端构建：

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm run build
```

结果：构建通过。Vite 提示 bundle 大小超过 500k，为既有提示，不影响本功能。

页面验证：

- 地址：`http://localhost:5174/pools/59f717fa-f741-4a13-a8ef-255e505e0b11`
- “板块K线数据底座”面板已显示：
  - 概念 `7`
  - 完成 `0`
  - 冷却 `7`
  - 股票映射 `10`

## 十、后续建议

1. 等东方财富行情域恢复后，在前端点击“重试失败”，或运行脚本补齐 250 日板块 K 线。
2. 补齐成功后，检查主升浪评分中的 `sector_resonance` 是否开始产生有效分值。
3. 为 `sector_quote_sync_state` 增加定时任务，每日休市后执行 `incremental`。
4. 若后续有可用 Tushare DC token，可实现 `eastmoney_direct -> tushare_dc` 的同源备用链路。
5. 当板块 K 线稳定后，再进入主升浪策略回测阶段，比较“纯趋势”和“趋势 + 题材共振”的收益差异。

## 十一、策略选股入口设计

主升浪策略最终归属到“策略选股”，观察池只负责承接、跟踪和复盘。

第一版策略 ID：

```text
main_wave_trend_v1
```

### 11.1 选股范围

| 范围 | 说明 |
| --- | --- |
| 全市场 | 基于本地 `stock_basic` + `daily_quote` 扫描，适合发现新方向 |
| 指定观察池 | 只对某个观察池内股票评分，适合复核存量标的 |
| 指定概念板块 | 基于 `stock_sector_map` 中的概念成分扫描，适合围绕题材做主升浪挖掘 |

当用户指定概念板块时，板块共振计算优先使用用户指定板块；未指定时，系统使用“最相关概念板块”自动排序结果。

### 11.2 参数分层

硬过滤参数：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `min_data_days` | 120 | 至少具备 120 个交易日 K 线 |
| `exclude_st` | true | 剔除 ST / 退市类标的 |
| `min_price` | 5 | 最新价下限 |
| `max_price` | 空 | 最新价上限，可选 |
| `min_float_market_cap_yi` | 30 | 流通市值下限，单位亿元 |
| `min_avg_amount_20d_yi` | 2 | 近 20 日平均成交额下限，单位亿元 |
| `max_return_60d` | 150 | 近 60 日涨幅上限，避免末端加速追高 |
| `max_ma20_distance_pct` | 25 | 最新价相对 MA20 最大乖离 |
| `exclude_effective_break` | true | 排除有效跌破 MA20 的标的 |

评分过滤参数：

| 参数 | 默认值 | 说明 |
| --- | ---: | --- |
| `min_score` | 70 | 总分下限 |
| `statuses` | 主升确认、突破跟踪、观察中、分歧预警 | 状态过滤 |
| `require_sector_resonance` | true | 是否要求板块共振分大于 0 |
| `min_sector_return_20d` | 5 | 指定或最相关概念 20 日涨幅下限 |
| `min_relative_strength_20d` | 0 | 个股 20 日涨幅相对板块强弱下限 |

### 11.3 指定概念板块

指定概念板块支持多选，并提供两种逻辑：

| 逻辑 | 说明 |
| --- | --- |
| `any` | 股票属于任一指定概念即可进入候选 |
| `all` | 股票必须同时属于全部指定概念 |

当前第一版依赖本地 `stock_sector_map` 已落库的概念成分关系。因此：

- 已有映射的概念可以直接扫描；
- 概念成分未同步完整时，扫描范围会偏窄；
- 概念 K 线缺失时仍可输出趋势评分，但会按参数决定是否因缺少共振而过滤。

### 11.4 输出字段

策略选股结果除股票代码和名称外，还应返回：

| 字段 | 说明 |
| --- | --- |
| `total_score` | 主升浪总分 |
| `status` | 主升阶段 |
| `trend_score` | 个股趋势分 |
| `structure_score` | 主升结构分 |
| `pullback_repair_score` | 回调修复分 |
| `sector_resonance_score` | 题材共振分 |
| `best_sector` | 本次用于共振的概念板块 |
| `return_20d` / `return_60d` | 个股阶段涨幅 |
| `relative_strength_20d` | 相对概念板块强弱 |
| `ma20_state` | MA20 状态 |

### 11.5 第一版实现边界

本阶段实现：

- 后端新增 `/api/strategy/main-wave-screen` 异步任务；
- 前端策略选股页新增“主升浪趋势”入口；
- 支持全市场、观察池、指定概念板块；
- 支持关键硬过滤和题材共振过滤；
- 支持一键加入观察池。

暂不实现：

- 历史回测；
- 定时自动加入观察池；
- 全量概念成分补齐任务；
- 参数预设保存。

### 11.6 实现验证

后端测试：

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
./venv/bin/pytest -q
```

结果：

```text
66 passed, 2 warnings
```

前端构建：

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm run build
```

结果：构建通过。Vite bundle 大小提示为既有提示，不影响功能。

接口验证：

```bash
curl -X POST http://127.0.0.1:8000/api/strategy/main-wave-screen \
  -H 'Content-Type: application/json' \
  -d '{"scope":"32f4c307-3129-42c8-be81-ed1fe7903d9f","min_score":0,"require_sector_resonance":false,"exclude_effective_break":false,"min_data_days":60}'
```

结果：任务完成后返回 `items` 明细，包含总分、状态、评分拆解、共振板块、20/60 日涨幅和相对板块强弱。
