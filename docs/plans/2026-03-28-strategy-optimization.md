# 涨停回调买入法 — 策略全面优化（2026-03-28）

## 概述

对 7 个"涨停回调买入法"策略进行系统性优化，修复所有已知不足。  
关键原则：**不引入未来函数**，所有条件判断仅使用截止到当日的历史数据。

---

## 一、基础设施变更

### 1.1 换手率持久化

| 文件 | 变更 |
|---|---|
| `backend/app/models/stock.py` | `DailyQuote` 新增 `turnover_rate = Column(Float, nullable=True)` |
| `backend/scripts/migrate_daily_quote_turnover.py` | SQLite 迁移脚本 |
| `backend/app/database.py` | `init_db()` 中调用迁移 |
| `backend/app/services/sync_service.py` | `sync_daily()` 完成后调用 `_backfill_turnover_rate()` 补充换手率；代理不支持时静默跳过 |

### 1.2 统一加权评分体系

**旧方案**：各战法 `met_count / total * 100` 简单计分，二阶段单独有 RSI/VR/MACD 加分。

**新方案**：

- 条件配置格式：`{key: {"label": str, "weight": float, "core": bool}}`
- 评分公式：`score = sum(met_weight) / sum(all_weight) * 100`
- 状态判定：
  - `triggered`：所有 core 条件满足 + score >= 80
  - `approaching`：所有 core 条件满足 或 score >= 65
  - `tracking`：score >= 40
  - `invalidated`：score < 40

---

## 二、公共前置筛选优化

文件：`backend/app/services/limit_up_tactics.py` → `common_pre_filter()`

| 优化点 | 旧逻辑 | 新逻辑 |
|---|---|---|
| max_days 参数化 | 硬编码 20 | 函数参数，各策略自定义（次日缩量=5，均线金叉=30） |
| 高位判定兼容短数据 | 仅 `limit_up_idx >= 60` 时生效 | `lookback = min(idx, 60)`，数据 >= 10 日即生效 |
| 涨停日换手率过滤 | 无 | `turnover_rate` 在 [3%, 25%] 区间；无数据时跳过 |
| 跌破容差 | `< limit_low * 0.98`（2%） | `< limit_low * 0.99`（1%） |

---

## 三、二阶段买点策略优化 (`two_phase`)

文件：`backend/app/services/buy_signal_service.py`

### 条件权重配置

| 条件 | 标签 | 权重 | 核心 | 变更说明 |
|---|---|---|---|---|
| `yang_candle` | 收阳线 | 1.0 | 是 | **新增** |
| `volume_ratio` | 量能温和放量 | 1.0 | 是 | 不变 |
| `pct_change` | 当日涨幅>=1% | 0.5 | 否 | 从 3% 降至 1%，降权为辅助 |
| `macd_golden` | MACD金叉/柱转正 | 1.0 | 是 | 不变 |
| `above_ma5` | 站上MA5 | 1.0 | 是 | 不变 |
| `above_ma10` | 站上MA10 | 0.5 | 否 | 降权为辅助 |
| `rsi_range` | RSI在45~70 | 0.5 | 否 | 从 50~70 扩展至 45~70 |
| `not_break_low` | 未破生命线低价 | 1.5 | 是 | 不变 |
| `pullback_stabilize` | 冲高回落企稳 | 1.5 | 是 | 重构为三阶段判定 |
| `volume_trend` | 成交量趋势向好 | 0.5 | 否 | 不变 |
| `turnover_range` | 换手率适中(2~12%) | 0.5 | 否 | **新增** |

### 冲高回落企稳重构

旧：两个分支实质相同，缺少明确三阶段判断。

新：
1. **冲高**：阶段高点 > 涨停收盘价 × 1.03
2. **回落**：当前价 < 阶段高点 × 0.97
3. **企稳**：近3日最低价逐日抬升 **或** 近5日收盘价标准差 < 均价的2%

### 生命线验证优化

- 量比阈值：从 2.0 降至 1.5；有换手率（>= 3%）时降至 1.2
- 高位判定：兼容短数据（`lookback = min(idx, 60)`）

---

## 四、次日缩量买入优化 (`next_day_shrink`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `volume_shrink` | 1.5 | 是 | **改为回调期间平均量 < 涨停日 60%**（旧：仅比较最新一天） |
| `near_ma` | 1.0 | 是 | 不变 |
| `not_break_low` | 1.5 | 是 | 不变 |
| `stabilize` | 1.0 | 是 | **加强为双确认**：收盘>=昨收 且 最低>=昨最低；次日不自动通过 |
| `no_big_yin` | 0.5 | 否 | 不变 |
| `time_window` | 1.0 | 是 | **新增**：涨停后 1~5 日内（`max_days=5`） |
| `turnover_shrink` | 0.5 | 否 | **新增**：今日换手率 < 涨停日 × 0.6 |

---

## 五、回踩5日线优化 (`ma5_pullback`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `touch_ma5` | 1.5 | 是 | **修复**：`low <= ma5 * 1.01`（旧有 close 范围矛盾） |
| `moderate_vol` | 0.5 | 否 | 降权为辅助 |
| `yang_candle` | 1.0 | 是 | 不变 |
| `above_ma5` | 1.0 | 是 | **修复**：`close >= ma5 * 0.995`（微弱偏差容忍） |
| `pullback_done` | 1.0 | 是 | **修复**：须出现过阴线或回撤>=2%（旧：<=3日直接通过） |
| `ma5_rising` | 0.5 | 否 | **新增**：MA5 今日 >= 昨日 |
| `turnover_moderate` | 0.5 | 否 | **新增**：换手率 < 5% |

---

## 六、三阴不破阳优化 (`three_yin`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `has_three_yin` | 1.5 | 是 | **改进**：允许最多1根几乎平盘K线（`|c-o|/o < 0.003`）不中断计数 |
| `yin_shrink_vol` | 1.0 | 是 | **收紧**：容差从 15% 降至 5% |
| `yin_not_break` | 1.5 | 是 | 不变 |
| `today_yang` | 1.0 | 是 | 不变 |
| `today_vol_expand` | 1.0 | 是 | **改进**：> 阴线期间平均量 × 1.5（旧：> 最后一根阴线 × 1.3） |
| `small_yin_body` | 0.5 | 否 | **新增**：所有阴线 |pct_chg| < 3% |

---

## 七、缩倍量信号优化 (`half_volume`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `vol_lock` | 1.5 | 是 | **合并**旧 `has_half_vol_yin` + `vol_half`；选量能最小的阴线；阈值 <= 涨停 50% |
| `today_yang` | 1.0 | 是 | 不变 |
| `break_limit_price` | 1.5 | 是 | **加强**：`close > lu_close * 1.005`（有效突破） |
| `today_vol_expand` | 1.0 | 是 | 不变 |
| `time_proximity` | 0.5 | 否 | **新增**：缩倍量日在涨停后 5 日内 |

---

## 八、均线金叉优化 (`ma_golden_cross`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `pullback_shrink` | 1.0 | 是 | **修复**：用阶段高点划分回调段（旧：二分法，分界点无实际意义） |
| `ma5_cross_ma10` | 1.5 | 是 | 不变 |
| `above_ma5` | 1.0 | 是 | 不变 |
| `above_ma10` | 1.0 | 是 | 不变 |
| `vol_support` | 0.8 | 否 | **提高**：量比阈值从 0.8 升至 1.0 |
| `ma5_turning_up` | 0.8 | 否 | **新增**：近2日至少1日 MA5 上升 |
| `ma10_flattening` | 0.5 | 否 | **新增**：近3日 MA10 斜率 < 1.5% |

`max_days` 从 20 扩展至 30。

---

## 九、搓揉线买入法优化 (`rubbing_line`)

| 条件 | 权重 | 核心 | 变更说明 |
|---|---|---|---|
| `rubbing_pattern` | 1.5 | 是 | **改进**：窗口搜索（涨停后1~5日内）替代固定 Day2/Day3 |
| `day_upper_vol_moderate` | 1.0 | 是 | 不变 |
| `day_upper_low_turnover` | 1.5 | 是 | **新增**：上影日换手率 <= 3%（策略原理核心条件） |
| `day_lower_vol_shrink` | 1.0 | 是 | 不变 |
| `not_break_low` | 1.5 | 是 | 不变 |
| `breakout_close` | 1.5 | 是 | **改进**：用收盘价突破（旧：用最高价，可能冲高回落） |

双组搓揉线检测：改为窗口化搜索第二组，而非固定 Day4/Day5。

---

## 十、避免"未来函数"核心规则

1. 所有条件判断仅使用 `df.iloc[:idx+1]`（截止当日数据）
2. 唯一例外：`common_pre_filter` 的"跌破涨停板最低价"使用涨停后至今全部数据 — 这是"失效判定"不是"买入信号"
3. 搓揉线"突破上影最高价"仅检查 day_lower 之后的**已有**历史K线
4. 均线、MACD、RSI 等指标基于截止当日的全部历史计算

---

## 十一、变更文件清单

| 文件 | 说明 |
|---|---|
| `backend/app/models/stock.py` | DailyQuote 新增 turnover_rate |
| `backend/scripts/migrate_daily_quote_turnover.py` | DB 迁移脚本 |
| `backend/app/database.py` | init_db 调用迁移 |
| `backend/app/services/sync_service.py` | sync_daily 补充换手率同步 |
| `backend/app/services/limit_up_tactics.py` | 加权评分框架 + 六大战法优化 |
| `backend/app/services/buy_signal_service.py` | 二阶段策略优化 + 适配新注册表 |
| 前端代码 | 无需变更（接口格式兼容） |

---

## 十二、测试验证结果

对 844 只观察池股票扫描结果：

| 策略 | triggered | approaching | 说明 |
|---|---|---|---|
| 二阶段买点识别 | 0 | 10 | 条件严格，approaching 合理 |
| 次日缩量买入 | 1 | 10 | 5日窗口限制生效 |
| 回踩5日线 | 35 | 27 | 常见模式，符合预期 |
| 三阴不破阳 | 0 | 1 | 罕见模式 |
| 缩倍量信号 | 2 | 2 | 精准筛选 |
| 均线金叉 | 0 | 16 | 形成中，未完全满足 |
| 搓揉线买入 | 0 | 2 | 换手率条件严格限制 |

---

## 十三、后续迭代方向

1. **回测验证**：对优化后策略进行历史数据回测，统计胜率和盈亏比
2. **信号持续性**：追踪信号连续多日满足的情况，提升置信度
3. **止损/止盈建议**：每条买入信号附带建议的止损价位和目标价位
4. **策略组合**：多策略同时触发的个股给予额外加分
5. **成交额过滤**：增加最小成交额要求，排除流动性不足的标的
