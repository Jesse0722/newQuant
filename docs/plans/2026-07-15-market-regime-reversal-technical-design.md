# 市场状态识别与反转证据评分技术设计

> 日期：2026-07-15
>
> 状态：设计评审稿
>
> 适用范围：`newQuant` 全项目
>
> 前置依赖：全市场日线覆盖与数据质量闸门
>
> 关联设计：`2026-05-24-main-wave-trend-technical-design.md`

## 1. 结论摘要

本方案将“全球因子、资金压力、市场宽度、卖压衰减与反转确认”建设为一个独立的**市场环境层**，供主升浪、涨停回调、观察池和每日复盘读取。

它不直接给出买卖指令，也不把“量化资金”当作可以被直接观测的单一主体。系统只根据可追溯数据回答：

- 当前市场证据更接近哪种状态；
- 下跌压力是在增强还是衰减；
- 外部冲击对 A 股的边际影响是否变化；
- 一次上涨更像流动性修复，还是已出现持续性确认；
- 结论覆盖了多少数据、还缺少哪些证据。

核心架构：

```text
可用性与质量闸门
        ↓
市场宽度 / 流动性 / 波动 / 外部因子 / 资金证据
        ↓
维度评分 + 证据覆盖率 + 置信等级
        ↓
市场状态快照（不可变、可回放、带版本）
        ↓
主升浪上下文 / 观察池 / 消息中心 / 交易计划 / 复盘
```

实施顺序必须是：

1. 修复并验证全市场历史数据覆盖；
2. 建立数据质量快照和 A 股市场宽度；
3. 再引入跨市场因子；
4. 最后接入 ETF、两融等资金证据并校准评分。

在覆盖率未达门槛前，系统输出“证据不足”，不得为了生成页面而补零或强行给出总分。

---

## 2. 背景与问题定义

### 2.1 产品假设

短期价格变化不仅受企业基本面影响，还可能受以下机制共同放大：

- 趋势、动量和风险预算模型的同向调整；
- ETF、融资盘、赎回和被动再平衡造成的仓位变化；
- 流动性下降时相同卖出量产生更大价格冲击；
- 跨市场主题、产业链和风险因子的共同暴露；
- 下跌后卖方仓位逐步出清与新增承接的非对称变化。

这些是需要被数据验证的研究假设，不是预设结论。产品不应展示“量化正在砸盘”“主力已经出清”等无法由现有数据直接证明的文案。

### 2.2 当前主升浪模块无法独立回答的问题

现有主升浪模块主要识别个股趋势、结构、回踩与板块共振，适合回答“哪些股票具备趋势候选特征”。它不应同时负责：

- 判断全市场处于趋势强化还是去风险阶段；
- 维护全球 AI、韩国半导体等跨市场因子；
- 推断市场卖压是否正在衰减；
- 判断反弹是否通过了第二次抛售测试；
- 管理 ETF、两融等独立资金证据。

若把这些逻辑继续叠加到主升浪单股分数中，会产生三个问题：

1. 个股质量与市场环境混成同一个分数，无法解释分数变化；
2. 每次市场状态调整都会改变历史主升浪规则，回测失去可比性；
3. 缺失的外部数据容易被错误降级为中性或零分。

因此需要增加独立的市场环境层。

### 2.3 产品边界

本模块是研究和决策支持系统，不是自动交易系统。

允许输出：

- `趋势强化候选`
- `拥挤风险上升`
- `卖压仍高`
- `卖压衰减待验证`
- `修复观察`
- `修复确认度提高`
- `证据不足`

禁止输出：

- `确定反转`
- `必须买入`
- `量化已经卖完`
- `明日必涨`
- 自动生成或执行交易委托

---

## 3. 当前能力与数据审计

### 3.1 可复用能力

| 能力 | 现有位置 | 可复用方式 |
|---|---|---|
| A 股个股日线 | `stock_basic`、`daily_quote` | 市场宽度、波动、成交和相对强弱原始数据 |
| 全市场按日期同步 | `sync_service.sync_full_market` | 改造为可验证、可补写的盘后全市场同步 |
| 板块及板块日线 | `sector_basic`、`stock_sector_map`、`sector_daily_quote` | 板块扩散度和行业状态，需补点时成分约束 |
| 涨跌停情绪 | `limit_market_board_service` | 涨跌停数量、连板和极端情绪证据 |
| 调度与任务日志 | `scheduler.py`、`scheduled_jobs_service.py`、`sync_log` | 盘后计算、失败记录和任务追踪 |
| 产业日报与证据结构 | `industry_report_service`、消息模型 | 市场状态解释和证据展示，不参与核心数值计算 |
| 主升浪相对强弱计算 | `main_wave_service` | 经过稳定化和测试后抽成公共指标，不直接依赖未提交实现 |

### 3.2 2026-07-15 本地 SQLite 审计结果

以下结果只描述当前 `backend/data/quant.db`，不能外推到未来 PostgreSQL 数据库：

| 项目 | 结果 | 影响 |
|---|---:|---|
| `daily_quote` 总行数 | 1,826,651 | 历史总量较大，但不能代表近期完整 |
| 日期范围 | 2023-10-09 至 2026-07-14 | 可支持部分历史研究 |
| 最近约 5,500 标的完整覆盖日 | 2026-04-15 | 之后无法直接视为全市场样本 |
| 2026-07-14 行数 | 254 | 严重低于全市场宽度要求 |
| 2026-07-13 行数 | 837 | 严重低于全市场宽度要求 |
| 近期 `amount` | 基本为空 | 不能可靠计算全市场成交压力 |
| `turnover_rate` 非空占比 | 约 6.3% | 换手率只能作为可选证据 |
| 行业板块历史日线 | 0 | 暂不支持行业级历史扩散回测 |

此外，`stock_basic` 混入了非个股代码；计算市场宽度前必须按证券类型、上市状态和交易日期过滤，不能简单对表内所有代码计数。

### 3.3 现有同步链路的关键缺口

- 默认组合源不包含 Tushare，而现有 Tencent、BaoStock、AkShare 路径不能完整支持历史“全市场按交易日”回补；
- Tencent 日线把 `amount` 写为 `None`；
- 全市场同步遇到已存在记录时直接跳过，不能校正盘中快照或不完整行；
- 同一个交易日缺少“预期标的数、实际标的数、字段完整率”的持久化质量记录；
- 当前没有海外指数、海外个股、ETF 份额、两融余额、股指期货等专用采集模型。

因此，**数据质量修复是本模块 P0，不是上线后的优化项**。

---

## 4. 总体架构与模块边界

### 4.1 分层架构

```text
┌──────────────────────────────────────────────┐
│ 工作流层：观察池 → 提醒 → 计划 → 执行 → 复盘 │
└───────────────────────▲──────────────────────┘
                        │ 读取上下文和证据
┌───────────────────────┴──────────────────────┐
│ 策略层：主升浪 / 涨停回调 / 未来反转候选策略 │
│ 个股策略分数保持独立，不被市场分数重写        │
└───────────────────────▲──────────────────────┘
                        │ market_context
┌───────────────────────┴──────────────────────┐
│ 市场环境层                                    │
│ 状态识别 / 卖压 / 拥挤 / 反转证据 / 外部因子  │
└───────────────────────▲──────────────────────┘
                        │ 仅消费通过质量闸门的数据
┌───────────────────────┴──────────────────────┐
│ 数据层                                        │
│ A股日线 / 市场宽度 / 全球行情 / ETF / 两融    │
└──────────────────────────────────────────────┘
```

### 4.2 与主升浪模块的接口

主升浪扫描结果增加独立上下文字段，不修改原始个股总分：

```json
{
  "total_score": 78.4,
  "market_context": {
    "trade_date": "20260714",
    "regime": "repair_observation",
    "regime_label": "修复观察",
    "crowding_risk": 62.0,
    "selling_pressure": 48.0,
    "reversal_evidence": 57.0,
    "coverage": 0.86,
    "confidence": "medium",
    "score_version": "market-regime-local-v1.0.0"
  }
}
```

规则：

- `total_score` 保留现有主升浪 API 兼容字段，只由对应主升浪策略版本决定；
- `market_context` 是筛选、排序提示和复盘维度，不在服务端隐式加减个股分数；
- 用户可显式按市场状态过滤，但系统不能将“市场状态不好”等价为自动卖出；
- 历史扫描必须引用当时已生成的市场快照，不能回填最新状态。

当前未提交的主升浪实现已经包含个股相对本地市场的 `market_relative` 特征。它与本方案的 `a_share_external_factor_residual` 含义不同：前者回答“该股票相对 A 股本地市场是否更强”，后者回答“A 股目标指数/板块相对外部因子是否更强”。首版保留前者及 `total_score` 的现有口径，市场上下文只展示后者，二者不得再次数值相加。若未来决定移除或改造 `market_relative`，必须发布新的主升浪 `strategy_id` 并单独回测，不能作为本模块接入时的隐式变更。

### 4.3 V1 时间粒度

V1 只做**盘后日频**市场状态。

不在 V1 实现：

- 盘口订单簿、主动买卖订单流和市场深度；
- 分钟级全球联动和盘中自动切换状态；
- 识别某一类机构的真实持仓或交易指令；
- LLM 直接打分；
- 自动仓位控制。

---

## 5. 数据质量闸门

### 5.1 原则

每个交易日先生成数据质量快照，之后才允许计算市场指标。

任何缺失都必须区分：

- `0`：真实观测值为零；
- `null`：没有数据；
- `not_applicable`：该指标对当前范围不适用；
- `stale`：存在数据但超过新鲜度门槛。

禁止把 `null` 自动填充为 0 后参与评分。

### 5.2 质量指标

| 指标 | 计算口径 | V1 建议门槛 |
|---|---|---:|
| 标的覆盖率 | 有效个股行情数 / 当日预期可交易普通 A 股数 | ≥ 95% |
| 核心字段完整率 | OHLC、`pre_close`、`pct_chg` 非空率 | ≥ 99% |
| 成交额完整率 | `amount` 非空且非负的有效行占比 | ≥ 95% 才启用成交额指标 |
| 历史连续率 | 近 60 个交易日有效样本占比 | ≥ 95% |
| 重复/异常率 | 重复键、非法日期、非有限数值占比 | ≤ 0.1% |
| 数据新鲜度 | 数据可用时间与预期盘后时间的差值 | 当日盘后窗口内 |
| 股票主数据覆盖 | 有证券类型和上市状态的行情行占比 | ≥ 99% |

覆盖率分母不能从当日已收到的 `daily_quote` 反推。它来自独立的点时证券主数据和交易状态：当日已上市且未退市的普通 A 股，排除有可靠记录的全天停牌标的；临时停牌但存在当日正式行情的标的仍计入。若历史退市、证券类型或全天停牌状态任一无法可靠获得，该日证券池质量不通过，不能声称达到 95% 覆盖率。

单项不达标时：

- 只关闭依赖该字段的指标；
- 重新计算本次证据覆盖率；
- 若核心维度覆盖低于 70%，总状态为 `insufficient_evidence`；
- 页面展示缺失项和最后成功日期。

### 5.3 同步修复要求

在建设评分前改造全市场同步：

1. 数据源必须声明 `supports_daily_by_trade_date`、`supports_history`、`provides_amount`；
2. 调度器按能力选择数据源，不允许调用后才静默得到空表；
3. 对已存在但字段不完整的行执行幂等更新，而不是全部跳过；
4. 记录每个交易日的预期数量、实际数量、字段完整率和来源；
5. 支持指定日期范围重跑和校验模式；
6. 盘中快照与盘后正式数据必须通过 `as_of`、`available_at` 或数据阶段区分。
7. 独立同步上市、退市、证券类型、ST 和全天停牌历史，用它生成每日证券池快照；不能用当前 `stock_basic.list_status` 回填历史。

不同供应商的 `volume`、`amount` 单位可能不同。写入前必须按适配器声明归一化到内部标准单位，同时保留原始单位、来源和批次；无法确认单位的数据只能用于价格类指标，不能参与跨源成交额汇总。

Phase 0 默认采用“整行权威来源”策略：同一 `ts_code + trade_date` 的 OHLC、成交量额和换手字段由一条通过质量校验的正式源记录整体选中。若该源缺少 `amount`，宁可保留 `null` 并关闭成交额指标，也不从另一来源静默拼接。未来确需跨源补字段时，必须先启用字段级选择模型，保存 `{field_name: provenance_id}`、各字段可用时间和单位换算；任一字段无法追溯时禁止写入合成行。

---

## 6. 指标体系

所有指标先产生标准化值与证据，再进入维度评分。V1 不使用 LLM 计算数值。

### 6.1 市场宽度 `breadth`

| 指标 | 口径 | 依赖 |
|---|---|---|
| 上涨/下跌/平盘家数 | `pct_chg > 0`、`< 0`、`= 0` | 全市场有效日线 |
| 上涨占比 | 上涨家数 / 有效交易家数 | 同上 |
| 涨跌家数比 | `advancers / max(decliners, 1)` | 同上 |
| 个股中位数收益 | 当日个股 `pct_chg` 中位数 | 同上 |
| 等权市场收益 | 有效个股收益等权平均 | 同上 |
| 20/60 日新高新低 | 当日收盘相对滚动窗口 | 连续历史日线 |
| 涨停/跌停及变化 | 统一口径的极端涨跌数量 | 涨跌停服务 |
| 宽度持续性 | 上涨占比、中位数收益的 3/5 日变化 | 历史宽度快照 |

证券池必须使用点时规则：当日已上市、未退市、证券类型为 A 股普通股票。若暂时无法获得可靠退市/停牌口径，应在质量快照中披露过滤限制。

### 6.2 流动性与波动 `liquidity_volatility`

| 指标 | 口径 | 缺失处理 |
|---|---|---|
| 全市场成交额 | 有效个股 `amount` 求和 | 完整率不足则关闭 |
| 成交额相对水平 | 当日成交额 / 20 日中位数 | 同上 |
| 下跌成交占比 | 下跌个股成交额 / 全市场成交额 | 同上 |
| 横截面离散度 | 个股收益的稳健标准差 | 可计算 |
| 实现波动率 | 等权市场近 20 日收益波动 | 可计算 |
| 下行波动 | 只使用负收益日的波动 | 样本不足则关闭 |
| ATR 扩张比例 | 个股短期 ATR / 中期 ATR 的横截面分布 | 历史连续率达标 |

成交额不完整时，不允许用成交量直接替代并沿用同一指标名称。

### 6.3 拥挤风险 `crowding_risk`

V1 只衡量**可观测的价格与成交集中现象**，不声称观测到了机构真实仓位。

候选证据：

- 指数或核心板块上涨，但个股中位数、上涨占比走弱；
- 领涨集中于少数股票或少数板块；
- 20 日动量分布极端化；
- 主题/板块收益与成交占比快速集中；
- 波动率扩张且价格对利好敏感、对利空更敏感；
- 可用时加入 ETF 份额、融资集中度作为独立证据。

V1 若缺少官方指数权重或可靠市值，不计算“权重指数减等权指数”这一伪精确指标，可先使用预先配置的宽基指数行情与本地等权市场收益比较。

### 6.4 卖压 `selling_pressure`

卖压分数表示当前可观测的下行压力强弱，不表示卖方身份。

建议初始维度：

| 证据 | 建议权重 | 方向 |
|---|---:|---|
| 下跌家数占比及加速度 | 25% | 越高压力越大 |
| 新低/新高比 | 15% | 越高压力越大 |
| 跌停数量及扩散速度 | 15% | 越高压力越大 |
| 下跌成交占比 | 15% | 越高压力越大 |
| 实现波动和 ATR 扩张 | 15% | 越高压力越大 |
| 等权市场下跌速度/回撤 | 15% | 越高压力越大 |

这是待回测的初始权重，必须绑定 `score_version`。缺失项按可用权重重新归一化，同时降低覆盖率；不能把同一底层变量的多个变体重复计权。

### 6.5 跨市场因子与本地相对强弱

跨市场行情使用通用标的模型，首批候选配置而非硬编码：

- 韩国：KOSPI、SK 海力士、三星电子；
- 台湾：台湾加权、台积电；
- 美国：SOX、NASDAQ 100、英伟达、美光；
- A 股映射：科创 50、创业板、半导体、存储、CPO 等可验证指数或板块。

跨市场因子统一使用“A 股决策时钟”，而不是把不同市场的同名日期直接拼接。设相邻两个 A 股信号截止时间为 `C(t-1)` 和 `C(t)`，某外部成分的有效收益为：

```text
component_return_i,t =
    last_final_price_i(available_at <= C(t))
    / last_final_price_i(available_at <= C(t-1)) - 1

global_factor_return_t = Σ(effective_weight_i,t × component_return_i,t)
```

这样，美国前一夜收盘、韩国/台湾当日收盘会被放入同一个“A 股上次截止到本次截止”的信息区间。每个成分同时保存 `effective_observation_at`、距截止时间的陈旧时长和对应行情修订 ID。若某市场因节假日没有新观测，该成分本期标记 `not_updated`，不把陈旧价格伪装成新的零收益；因子按当期可用成分重新归一化并降低覆盖率。若可用权重低于配置门槛，因子本期不可用。

本地相对强弱：

```text
local_residual_t = a_share_return_t - beta_t × global_factor_return_t
```

约束：

- `beta_t` 只能使用 `t` 日之前可获得的数据滚动估计；
- 初始窗口建议 60 个重叠交易日，稳健版本同时展示 120 日结果；
- 样本不足、结构突变或残差异常时降低置信等级；
- 全球篮子权重和成分必须版本化；
- 汇率是否调整必须按研究目的明确配置，不允许混用；
- beta 训练样本必须使用相同的 A 股决策时钟和成分覆盖规则。

#### 交易日与可用时间

每条外部行情必须记录：

- `session_date`
- `market_timezone`
- `available_at`
- `ingested_at`
- `is_final`
- `published_at/revision_id`
- `effective_observation_at`

计算 A 股交易日 `t` 的信号时，只能使用在信号截止时间前已正式可得的数据。例如美国 `t` 日收盘发生在 A 股 `t` 日收盘之后，不能用于解释或回测 A 股 `t` 日收盘决策。统一由“数据可用性账本”决定，并按上面的截止时间区间计算，不能按 `session_date` 或日期字符串直接连接。

### 6.6 ETF、两融与其他资金证据

这些数据放在后续阶段，以独立证据进入评分：

| 数据 | 推荐口径 | 注意事项 |
|---|---|---|
| ETF 份额 | 日末份额变化 | 份额变化不等于精确净流入 |
| ETF 估算净申购 | 份额变化 × 可用净值/价格 | 明确估算方法和误差 |
| 两融汇总 | 融资余额、融资买入额、融券余额 | 区分“标的名单”和真实余额 |
| 两融行业分布 | 点时成分映射后的聚合 | 防止当前成分回填历史 |
| 北向/期指 | 仅在稳定、合法、可回补来源可用时接入 | 不作为 V1 阻塞项 |

数据供应商接口可能有权限、积分、限流和字段变更。实现前应通过适配器能力探测，并以供应商官方数据目录为准，例如 [Tushare Pro 数据目录](https://tushare.pro/document/2?doc_id=17)。不得把“融资融券标的名单”误当成融资余额。

### 6.7 反转证据 `reversal_evidence`

反转证据不是“抄底分”，由六个互补维度组成：

| 维度 | 建议权重 | 核心问题 |
|---|---:|---|
| 卖压衰减 | 25% | 下跌速度、跌停扩散和新低数量是否减弱 |
| 反应结构/价格钝化 | 20% | 本地内部反应是否缓和；接入外部因子后，负面冲击下价格影响是否下降 |
| 本地相对强弱 | 20% | 对外部因子的残差是否持续转正 |
| 市场宽度修复 | 15% | 修复是否从少数权重扩散 |
| 价格结构 | 15% | 是否形成更高低点并通过回踩验证 |
| 资金证据 | 5% 起步 | ETF/两融是否提供独立承接证据 |

资金证据尚未接入时，不把 5 分直接判为 0，而是降低覆盖率并对可用部分重新归一化。

#### 反应结构与价格钝化的确定性口径

“相似负面冲击”必须由规则选样，不能在事后主观挑选事件：

- Phase 1 本地口径：另行构造不含等权收益、回撤和实现波动的 `pressure_ex_return`，只使用下跌宽度、新低/跌停扩散及可用的下跌成交占比。当它位于过去 120 个有效交易日的前 20%，定义为本地下行结构日；比较最近 3 个结构日与此前 10 个结构日的等权收益绝对值、新低扩散和次日延续性；
- Phase 2 外部口径：当全球因子收益低于过去 120 个有效样本的 10% 分位，定义为外部负面冲击日；计算 A 股目标收益、条件 beta 和残差，比较最近 3 个冲击日与此前 10 个冲击日；
- 最近窗口的价格影响系数下降且残差改善，才记为钝化证据；反之记为恶化；
- 任一口径不足 13 个历史冲击样本时，该项为 `insufficient_sample`，不参与计分并降低覆盖率；
- 分位数窗口、最小样本、比较窗口和归一化公式全部绑定评分版本。

`pressure_ex_return` 仍包含由个股价格方向派生的宽度和极端数量，因此 Phase 1 结果只命名为 `internal_response_decay`，属于内部结构症状，不能解释为独立订单流造成的价格冲击系数，也不能写成“对海外利空脱敏”。真正的 `external_price_insensitivity` 必须等待 Phase 2 外部因子数据；若下跌成交占比也不可用，Phase 1 该项置信等级最多为 `low`。

---

## 7. 状态机设计

### 7.1 状态枚举

| 状态代码 | 中文标签 | 含义 |
|---|---|---|
| `trend_strengthening` | 趋势强化 | 价格、宽度和持续性共同改善 |
| `crowding_acceleration` | 拥挤加速 | 趋势仍强，但集中度和脆弱性上升 |
| `deleveraging` | 去风险 | 卖压、波动和下行扩散同步增强 |
| `selling_exhaustion` | 卖压衰减 | 压力仍在，但边际恶化停止 |
| `repair_observation` | 修复观察 | 首次修复出现，尚未通过回踩验证 |
| `repair_confirmed` | 修复确认度提高 | 回踩、宽度和相对强弱形成连续证据 |
| `range_neutral` | 震荡中性 | 无明确趋势或压力主导 |
| `insufficient_evidence` | 证据不足 | 核心数据覆盖不达门槛 |

### 7.2 状态转换原则

状态由连续证据决定，避免单日大阳线直接跳到 `repair_confirmed`。

```text
deleveraging
    ↓ 卖压连续衰减
selling_exhaustion
    ↓ 首次修复且宽度改善
repair_observation
    ↓ 二次回踩不破 + 相对强弱保持 + 宽度未恶化
repair_confirmed
    ↓ 趋势持续
trend_strengthening
    ↓ 集中度/波动率过度扩张
crowding_acceleration
```

允许跨级降级：重大冲击下 `repair_observation` 可直接回到 `deleveraging`。

### 7.3 分阶段状态能力

每个阶段冻结独立 `score_version` 和允许输出的状态，不能仅靠缺失权重重归一化获得一个看似完整的反转结论：

| 版本阶段 | 核心维度 | 允许输出 |
|---|---|---|
| `market-regime-local-v1` | 点时证券池、宽度、波动、卖压、本地价格结构 | 除 `repair_confirmed` 外的基础状态；`repair_observation` 标注“仅本地证据” |
| `market-regime-global-v2` | v1 + 外部因子与本地残差 | 可增强 `repair_observation`，仍禁止 `repair_confirmed` |
| `market-regime-flow-v3` | v2 + ETF/两融 | 可增加承接证据，仍禁止 `repair_confirmed` |
| `market-regime-retest-v4` | v3 + 因果二次抛售测试 | 满足全部核心门槛后才允许 `repair_confirmed` |

`repair_confirmed` 的核心门槛为：有效宽度、价格结构、外部相对强弱和二次抛售测试全部可用且通过。任何核心维度缺失都禁止该状态，无论总覆盖率或重新归一化后的分数多高。其他状态也可按版本配置自己的必需维度。

#### `market-regime-local-v1` 决策矩阵

以下默认值用于形成可测试的首版，不代表已经完成统计校准；回测调整时必须发布新版本。每日按表中优先级自上而下判断：

| 优先级 | 目标状态 | 进入条件 | 退出/滞回条件 |
|---:|---|---|---|
| 1 | `insufficient_evidence` | 点时证券池质量失败，或任一核心维度覆盖 < 70% | 缺失日期完成补算且连续 1 日质量通过；不能直接沿用中断前状态 |
| 2 | `deleveraging` | `selling_pressure >= 85` 单日成立；或 `selling_pressure >= 70` 且 `breadth_score <= 35` 连续 2 日 | 压力低于 60 连续 2 日后才允许离开 |
| 3 | `selling_exhaustion` | 前一有效状态为 `deleveraging`，压力较近 5 日峰值下降 ≥ 15 分且连续 2 日走低，新低/跌停扩散未创新高 | 压力重新 ≥ 70 回 `deleveraging`；满足修复条件进入 `repair_observation`；5 日无继续改善回 `range_neutral` |
| 4 | `repair_observation` | 前一有效状态为 `selling_exhaustion`，本地反转证据 ≥ 55、`breadth_score >= 50` 连续 2 日，且等权市场未创新 20 日低点 | 压力 ≥ 70 或创新低回 `deleveraging`；本地反转证据 < 45 连续 2 日回 `range_neutral` |
| 5 | `crowding_acceleration` | `breadth_score >= 60`、`selling_pressure <= 35`、等权市场收盘高于 20 日均线连续 3 日，且 `crowding_risk >= 70` 连续 2 日 | 拥挤风险 < 60 连续 2 日后按当日其他条件转移；满足去风险条件可直接进入 `deleveraging` |
| 6 | `trend_strengthening` | `breadth_score >= 60`、`selling_pressure <= 35` 且等权市场收盘高于 20 日均线，连续 3 日 | 宽度 < 50 或压力 > 45 连续 2 日后退出；满足拥挤或去风险条件按更高优先级转换 |
| 7 | `range_neutral` | 质量通过但不满足以上任一状态 | 满足更高优先级条件即退出 |

补充规则：

- 初次运行或历史状态不可用时，只能判为 `deleveraging`、`crowding_acceleration`、`trend_strengthening`、`range_neutral` 或 `insufficient_evidence`；不能凭单日快照初始化为 `selling_exhaustion` 或 `repair_observation`；
- 任一状态都可按优先级直接进入 `deleveraging` 或 `insufficient_evidence`；
- 数据中断后先补算所有缺失交易日，再从最后一个连续有效状态续接；若无法补算，则按初次运行规则重新初始化，并在快照标记 `state_continuity_reset=true`；
- 表中的连续日只统计质量通过的相邻 A 股交易日；
- `breadth_score`、`selling_pressure` 和 `crowding_risk` 的阈值、滞回区间与优先级全部固化在 `market-regime-local-v1` 配置和测试夹具中。

### 7.4 “二次抛售测试”的可计算定义

建立 `reversal_test_event` 事件，而不是依靠自然语言判断：

1. **锚点候选发生**：在 `deleveraging` 后记录当日最低候选 `L0`，此时不宣称它是已确认低点；
2. **锚点因果确认**：只有后续价格从候选低点上涨达到版本化的波动率调整门槛，系统才在当日收盘后把 `L0` 标记为锚点；分别保存 `anchor_occurred_date` 和 `anchor_detected_at`；
3. **首次反弹高点候选**：反弹过程持续更新候选 `H1`，只有随后发生达到门槛的回撤时才在当日确认，分别保存 `rebound_high_occurred_date` 和 `rebound_high_detected_at`；
4. **回踩窗口**：从 `H1` 确认日开始进入测试状态，回测中的首次可行动时点不得早于确认后的下一可成交时点；
5. **通过条件**：未有效跌破 `L0`，回踩卖压低于锚点阶段，宽度未重新恶化，外部冲击残差不弱；
6. **失败条件**：有效跌破 `L0`，或卖压/跌停扩散重新超过锚点阶段；
7. **超时条件**：设定窗口内未发生有效回踩，状态保持观察，不伪造确认。

事件状态转换采用追加记录，不能只更新最终状态。所有阈值采用 ATR、历史波动分位数等尺度调整方法，并在评分版本中固定。页面可展示低点发生日，但必须同时展示“系统于何时确认”，避免把事后确认日期误当成当时信号。

---

## 8. 评分、覆盖率与置信等级

### 8.1 输出结构

每个维度统一输出：

```json
{
  "score": 57.2,
  "coverage": 0.82,
  "confidence": "medium",
  "direction": "improving",
  "evidence": [
    {
      "metric": "decline_breadth_5d_change",
      "value": -0.18,
      "normalized": 0.71,
      "trade_date": "20260714",
      "source": "market_breadth_snapshot",
      "quality": "pass"
    }
  ],
  "missing_inputs": ["etf_share_change", "margin_balance_change"]
}
```

### 8.2 覆盖率

```text
coverage = Σ(available_weight_i × quality_factor_i) / Σ(configured_weight_i)
```

建议质量系数：

- `pass = 1.0`
- `degraded = 0.5`
- `stale = 0.0`
- `missing = 0.0`

### 8.3 置信等级

| 等级 | 建议条件 |
|---|---|
| `high` | 覆盖率 ≥ 90%，核心数据无降级，状态连续至少 2 日 |
| `medium` | 覆盖率 75%–90%，无核心字段缺失 |
| `low` | 覆盖率 70%–75%，或存在重要降级证据 |
| `insufficient` | 覆盖率 < 70% 或全市场覆盖未通过 |

置信等级不是胜率，不应展示成“预测成功概率”。

### 8.4 版本管理

至少版本化：

- 指标定义；
- 标准化窗口；
- 权重；
- 状态转换阈值；
- 因子篮子成分和权重；
- 证券池过滤规则；
- 数据可用时间规则。

已生成快照不可被新版本覆盖。重算时创建新版本记录，并保留旧快照用于审计。

---

## 9. 数据模型

长期主库按项目方向使用 PostgreSQL。SQLite 仅保留本地开发兼容，不为新模块设计分裂主库。

### 9.1 `market_instrument`

统一维护指数、ETF、海外股票和其他市场标的，不复用只面向 A 股股票的 `stock_basic`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `canonical_code` | VARCHAR | 内部稳定代码 |
| `name` | VARCHAR | 名称 |
| `market` | VARCHAR | SSE/SZSE/KRX/TWSE/NASDAQ 等 |
| `asset_type` | VARCHAR | index/equity/etf/future/fx |
| `currency` | VARCHAR | 币种 |
| `timezone` | VARCHAR | IANA 时区 |
| `active_from/to` | DATE | 生效范围 |
| `metadata_json` | JSONB | 额外元数据 |

`canonical_code` 全局唯一；索引：`(market, asset_type, active_from)`。这张表表达经济标的身份，不包含任何供应商绑定。

### 9.2 `market_instrument_source_map`

同一标的可映射多个数据源：

- `id`
- `instrument_id`
- `source`
- `source_code`
- `valid_from/valid_to`
- `priority`
- `capabilities_json`
- `active`

唯一约束：`(source, source_code, valid_from)`；索引：`(instrument_id, active, priority)`。此外，同一 `source + source_code` 的有效日期范围禁止重叠：PostgreSQL 使用日期范围排斥约束，SQLite 兼容路径在同一事务中由服务层校验。数据源代码变化只产生新的映射版本，不创建重复经济标的。

### 9.3 `market_daily_quote`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 不可变行情修订 ID |
| `instrument_id` | UUID | 标的 |
| `source_map_id` | UUID | 使用的供应商映射 |
| `session_date` | DATE | 所属市场交易日 |
| `open/high/low/close` | NUMERIC | 行情 |
| `pre_close` | NUMERIC | 前收 |
| `volume/amount` | NUMERIC | 成交量额，可空 |
| `currency` | VARCHAR | 原始币种 |
| `is_final` | BOOLEAN | 是否正式收盘数据 |
| `published_at` | TIMESTAMPTZ | 供应商发布时间，可空但需降级 |
| `available_at` | TIMESTAMPTZ | 在决策系统中可用的时间 |
| `ingested_at` | TIMESTAMPTZ | 入库时间 |
| `source_revision` | VARCHAR | 供应商修订号或内部递增版本 |
| `valid_from` | TIMESTAMPTZ | 本修订生效时间 |
| `superseded_at` | TIMESTAMPTZ | 被下一修订替代的时间，可空 |
| `raw_hash` | VARCHAR | 原始内容校验 |

主键为 `id`；唯一约束：`(source_map_id, session_date, source_revision)`。同一供应商的 provisional/final 多次修订均追加新行，不覆盖旧行；因子和状态快照引用具体行情修订 ID。

### 9.4 `market_data_quality_snapshot`

记录每个交易日、数据域的质量：

- `trade_date`
- `domain`：A 股日线/外部因子/ETF/两融/板块
- `expected_count`
- `actual_count`
- `coverage_ratio`
- `field_completeness_json`
- `freshness_status`
- `quality_status`
- `issues_json`
- `source`
- `calculation_version`
- `input_as_of`
- `config_hash/code_hash`
- `input_snapshot_ids`
- `calculated_at`

唯一约束：`(trade_date, domain, calculation_version, input_as_of)`。

### 9.5 `daily_quote_provenance`

现有 `daily_quote` 没有来源、批次、数据阶段和更新时间。为避免在第一期侵入式修改行情主键，先增加一张一对一/一对多溯源表：

- `ts_code`
- `trade_date`
- `source`
- `source_batch_id`
- `data_stage`：intraday/preliminary/final
- `source_revision`
- `available_at`
- `ingested_at`
- `volume_unit`
- `amount_unit`
- `raw_hash`
- `quality_status`

唯一约束：`(ts_code, trade_date, source, data_stage, source_revision)`。正式行情发生修订时追加溯源记录；`daily_quote` 保存当前选定的标准化值，溯源表负责解释该值来自何处。后续若确认单一权威主数据源，可再评估把常用溯源字段合并进 `daily_quote`。

### 9.6 `daily_quote_repair_audit`

任何修复现有 `daily_quote` 的任务在写入前保存逐字段审计：

- `repair_batch_id`
- `ts_code/trade_date`
- `old_values_json/new_values_json`
- `changed_fields`
- `old_hash/new_hash`
- `old_field_provenance_json/new_field_provenance_json`
- `reason`
- `changed_at`
- `rolled_back_at`

该表是数据修复回滚依据，不与普通行情采集日志混用。

### 9.7 `daily_quote_field_selection`

记录 `daily_quote` 当前每个标准字段选自哪条原始源记录：

- `ts_code/trade_date`
- `selection_version`
- `input_as_of`
- `field_provenance_json`：例如 `{ "close": provenance_id, "amount": provenance_id }`
- `selection_policy`：`single_authoritative_row` 或经审批的 `field_level_merge`
- `unit_conversion_json`
- `selected_at`

Phase 0 只允许 `single_authoritative_row`，所有非空字段必须指向同一 provenance。以后启用 `field_level_merge` 时，服务需校验各字段属于同一交易阶段、可用时间不晚于截止时间且单位可转换。唯一约束：`(ts_code, trade_date, selection_version, input_as_of)`。

### 9.8 `market_universe_member_snapshot`

为保证市场宽度和回测可重现，每个交易日保存实际使用的证券池：

- `trade_date`
- `universe_version`
- `ts_code`
- `security_type`
- `board`
- `is_listed`
- `is_trading`
- `is_st`
- `included`
- `exclusion_reason`
- `source`
- `calculation_version`
- `input_as_of`

若历史 ST、停牌或退市状态不能可靠回补，相应字段标记为未知，并在质量快照中降低证券池质量；不能用当前状态无提示地覆盖历史。

唯一约束：`(trade_date, universe_version, ts_code, calculation_version, input_as_of)`。

### 9.9 `market_breadth_snapshot`

保存 A 股市场级与可选板块级宽度：

- `trade_date`
- `scope_type`：market/index/sector
- `scope_code`
- 上涨、下跌、平盘、涨停、跌停、新高、新低数量
- 中位数、等权收益、离散度、成交额及字段完整率
- `universe_version`
- `source_snapshot_json`
- `calculation_version`
- `input_as_of`
- `config_hash/code_hash`
- `input_snapshot_ids`
- `calculated_at`

唯一约束：`(trade_date, scope_type, scope_code, universe_version, calculation_version, input_as_of)`。改变新高口径、异常值处理或输入修订时产生新快照，不覆盖旧结果。

### 9.10 `market_flow_snapshot`

用于 ETF、两融和未来资金证据：

- `trade_date`
- `flow_type`
- `scope_code`
- `value`
- `unit`
- `estimation_method`
- `available_at`
- `source`
- `quality_status`
- `metadata_json`
- `calculation_version`
- `input_as_of`
- `input_snapshot_ids`

同一张表统一存证据，但每个 `flow_type` 必须有明确单位和计算口径。唯一约束：`(trade_date, flow_type, scope_code, source, calculation_version, input_as_of)`。

### 9.11 `market_factor_exposure_snapshot`

- `trade_date`
- `target_code`
- `factor_code`
- `window`
- `beta`
- `alpha`
- `residual_return`
- `sample_count`
- `fit_quality`
- `factor_version`
- `available_at`
- `effective_observation_at`
- `component_quote_revision_ids`
- `calculation_version/input_as_of`

唯一约束：`(trade_date, target_code, factor_code, window, factor_version, calculation_version, input_as_of)`。

### 9.12 `market_regime_snapshot`

- `id`
- `trade_date`
- `as_of`
- `regime`
- `regime_label`
- `breadth_score`
- `crowding_risk`
- `selling_pressure`
- `reversal_evidence`
- `local_relative_strength`
- `coverage`
- `confidence`
- `score_version`
- `evidence_json`
- `missing_inputs_json`
- `quality_snapshot_ids`
- `input_snapshot_ids`
- `config_hash/code_hash`
- `created_at`

唯一约束：`(trade_date, as_of, score_version)`。

### 9.13 `reversal_test_event`

保存二次抛售测试的状态：

- `id`
- `scope_type/scope_code`
- `anchor_occurred_date/value`
- `anchor_detected_at`
- `rebound_high_occurred_date/value`
- `rebound_high_detected_at`
- `retest_start_date`
- `retest_available_at`
- `resolved_date`
- `resolved_at`
- `status`：watching/passed/failed/expired
- `anchor_evidence_json`
- `retest_evidence_json`
- `rule_version`

### 9.14 `reversal_test_event_transition`

事件状态采用追加式历史：

- `id/event_id`
- `from_status/to_status`
- `occurred_at`
- `detected_at`
- `available_at`
- `evidence_snapshot_ids`
- `rule_version`

回测按 transition 的 `available_at` 回放当时已知状态，不读取事件表最终状态倒推历史。

---

## 10. 后端服务设计

### 10.1 服务拆分

| 服务 | 职责 |
|---|---|
| `market_data_quality_service.py` | 证券池、覆盖率、字段完整率、质量闸门 |
| `market_breadth_service.py` | 市场和板块宽度快照 |
| `global_factor_data_service.py` | 外部标的配置、采集、时区与可用时间 |
| `market_factor_service.py` | 因子篮子、滚动 beta、残差相对强弱 |
| `market_flow_service.py` | ETF、两融等资金证据 |
| `market_regime_service.py` | 维度评分、状态机、证据聚合 |
| `reversal_test_service.py` | 锚点、首次反弹、回踩测试事件 |
| `market_regime_report_service.py` | 规则化摘要及可选 LLM 解释 |

业务规则放在服务中，路由只做校验和序列化。

### 10.2 LLM 边界

LLM 仅可将结构化结果解释成自然语言，输入必须包含：

- 已计算的状态与分数；
- 证据列表；
- 覆盖率和缺失项；
- 禁止结论列表。

LLM 不得：

- 修改数值分数；
- 补全不存在的资金流；
- 把相关性描述成因果；
- 输出确定性买卖建议。

解析失败时回退到确定性模板，不影响快照生成。

---

## 11. API 设计

### 11.1 查询接口

```text
GET /api/market-regime/latest
GET /api/market-regime/history?start_date=&end_date=&score_version=
GET /api/market-regime/{trade_date}?score_version=
GET /api/market-regime/{trade_date}/evidence
GET /api/market-breadth/history?scope_type=&scope_code=
GET /api/market-factors/latest
GET /api/market-data-quality/latest
GET /api/reversal-tests?scope_type=&scope_code=&status=
```

### 11.2 管理接口

```text
POST /api/market-regime/recompute
POST /api/market-data-quality/validate
POST /api/market-data/backfill
```

管理接口复用异步任务与 `SyncLog`，返回 `task_id`。重算必须显式指定日期范围和版本，默认不覆盖现有记录。

### 11.3 错误语义

| 场景 | 响应 |
|---|---|
| 数据未生成 | 404 + `SNAPSHOT_NOT_FOUND` |
| 覆盖不足 | 200 + `regime=insufficient_evidence` + 缺失项 |
| 上游仍同步 | 409 + `DATA_NOT_READY` |
| 版本不存在 | 404 + `SCORE_VERSION_NOT_FOUND` |
| 重算任务冲突 | 409 + 现有 `task_id` |

---

## 12. 调度与依赖

### 12.1 盘后任务链

调度不能只依赖固定时间，必须同时校验上游数据质量：

```text
解析目标 A 股交易日
    ↓
全市场盘后正式数据同步/校验
    ↓ quality pass
市场宽度快照
    ↓
外部市场已可用数据同步
    ↓
因子暴露与资金证据
    ↓
状态快照 + 反转测试事件
    ↓
规则摘要 / 可选 LLM 解释
    ↓
消息中心和主升浪上下文可见
```

当前 17:00 任务只同步观察池股票，不是全市场盘后同步，不能作为本质量链路的上游完成条件。Phase 0 必须新增独立任务类型 `scheduled_full_market_final_sync`，负责目标交易日的全市场正式行情、点时证券状态和质量校验；现有 17:00 任务继续作为观察池补齐，二者互不替代。

新的市场状态任务可以配置在盘后全市场任务之后尝试执行，但实际触发以 `scheduled_full_market_final_sync` 的目标交易日和质量快照通过为准，而不是只看墙钟时间。若上游未通过，记录 `waiting_for_data` 或失败原因，不生成伪状态。

### 12.2 幂等与并发

- 每个任务使用 `(task_type, trade_date, version)` 作为业务幂等键；
- 同一日期同一版本只允许一个运行任务；
- 快照在事务内写入；
- 外部数据修订后以新 `as_of` 或新版本重算；
- 调度失败可手动补跑，不能因服务错过某一分钟而永久缺失。

现有调度器“只在目标分钟执行且不补跑”的模式不适合关键状态快照，需要补充依赖感知和补跑机制。

---

## 13. 前端设计

V1 新增一个紧凑的“市场状态”工作页，不拆成三个孤立页面。

### 13.1 页面结构

1. 顶部状态条：交易日、状态、覆盖率、置信等级、数据最后更新时间；
2. 维度表：宽度、拥挤、卖压、反转证据、本地相对强弱；
3. 证据时间序列：最近 20/60 日状态与核心指标；
4. 全球因子表：收益、beta、残差、数据可用时间；
5. 资金证据表：ETF、两融及缺失状态；
6. 二次抛售测试：观察中/通过/失败事件及证据；
7. 可展开的计算口径和数据质量详情。

使用表格、标签和紧凑面板；不使用营销式大卡片或装饰性雷达图掩盖精确数值。

### 13.2 主升浪页面集成

仅增加：

- 当前市场状态提示条；
- 每条扫描结果的市场上下文标签；
- “只看通过市场环境过滤”的显式用户筛选；
- 展开后查看证据和评分版本。

不在前端复制市场状态计算规则，不将市场分数与个股分数相加后展示为新的单一总分。

### 13.3 空态与降级

| 状态 | 页面行为 |
|---|---|
| 未生成 | 展示“尚未生成”，允许管理员触发校验 |
| 数据同步中 | 展示任务进度，不展示旧数据为今日结论 |
| 证据不足 | 展示覆盖率、缺失字段和最后可信日期 |
| 部分维度不可用 | 保留其他维度，缺失项显示 `—` |
| 上游失败 | 展示可重试入口和错误摘要 |

---

## 14. 回测与校准

### 14.1 回测目的

第一阶段先验证指标是否稳定描述和区分市场状态，再评估其对未来风险收益的关系。不能直接按最大收益调权重。

核心问题：

- `selling_pressure` 上升时，未来 1/5/10 日下行风险是否显著变化；
- `repair_observation` 进入 `repair_confirmed` 后，失败率是否下降；
- 本地残差转正是否比绝对上涨更早识别脱敏；
- 宽度改善能否区分权重拉升和普遍修复；
- 哪些指标只解释当日，哪些具有稳定的前瞻价值。

### 14.2 防止未来函数

- 使用点时证券池、成分和数据版本；
- 只使用当时 `available_at` 已可得数据；
- 所有外部成分按相邻 A 股决策截止时间构造收益；美国市场当日晚于 A 股的数据自然进入下一 A 股决策区间；
- 节假日无新观测的成分标记 `not_updated` 并降低覆盖率，不按同名日期拼接；
- 信号使用当日收盘数据时，交易评价从下一可成交时点开始；
- 局部低点和反弹高点从各自 `detected_at` 后才可进入信号，不能用 `occurred_date` 倒推；
- 不能用当前 ETF/板块成分回填历史；
- 缺失数据不得使用未来值向前填充。

### 14.3 评价指标

| 类别 | 指标 |
|---|---|
| 状态稳定性 | 状态平均持续期、单日翻转率、缺失率 |
| 风险区分度 | 未来最大回撤、下行波动、跌停扩散 |
| 修复有效性 | 通过/失败率、确认滞后、假修复比例 |
| 相对强弱 | 残差持续性、外部冲击条件分组表现 |
| 数据质量 | 覆盖率、延迟、重算差异、来源一致性 |
| 策略增量 | 主升浪候选在不同状态下的分组表现 |

策略增量回测必须保留“无市场过滤”的基线，不能只展示改进后的样本。

### 14.4 Walk-forward 校准

建议：

1. 训练窗口固定指标标准化参数；
2. 下一时间段只做验证；
3. 按季度或半年滚动；
4. 权重更新产生新 `score_version`；
5. 旧版本继续可回放。

---

## 15. 测试计划

### 15.1 单元测试

- 证券池过滤：上市、退市、停牌、指数混入；
- 行情来源、批次、数据阶段与成交量额单位归一化；
- Phase 0 整行权威来源选择，禁止无字段血缘的跨源合成；
- 字段级血缘、来源映射有效期不重叠；
- 覆盖率和字段完整率；
- `null` 不得当作 0；
- 宽度、新高新低和离散度计算；
- 缺失指标的权重重归一化与覆盖率下降；
- 状态转换、跨级降级和防抖；
- Phase 1 初始状态、优先级、进入/退出阈值、滞回及数据中断恢复；
- 各阶段允许状态和核心维度门槛；
- 二次抛售测试候选发生、因果确认、通过、失败和超时；
- 回测不能在 `anchor_detected_at` 前使用 `anchor_occurred_date`；
- 跨市场 A 股决策时钟、节假日、陈旧成分和 `available_at` 对齐；
- 滚动 beta 不使用未来数据；
- 价格钝化事件选样、最小样本和冲击窗口；
- 评分版本不可覆盖。

### 15.2 集成测试

- 全市场同步 → 质量快照 → 宽度 → 状态快照完整链路；
- 观察池 17:00 同步成功但全市场正式同步未通过时，状态任务仍保持等待；
- 不完整 `amount` 时成交指标关闭但其他维度可用；
- 上游同步失败时不生成今日状态；
- 同一任务重复提交的幂等行为；
- 历史重算创建新版本；
- 主升浪 API 只引用对应日期市场快照。

### 15.3 回归测试

- 不改变现有主升浪 `total_score` 和 API 字段；
- 个股 `market_relative` 与市场层 `a_share_external_factor_residual` 不重复计分；
- 不改变观察池、提醒、交易计划既有流程；
- 消息中心在市场报告缺失时仍可使用；
- SQLite 本地开发和 PostgreSQL 主路径均能启动。

### 15.4 前端测试

- 加载、空态、证据不足、失败、部分降级；
- 日期和版本切换；
- 分数与覆盖率不混淆；
- 长证据文本展开不溢出；
- 主升浪列表上下文展示不影响原有筛选。

---

## 16. 数据库迁移方案

### 16.1 Backup

- SQLite 开发环境：复制 `backend/data/quant.db` 并记录校验值；
- PostgreSQL：执行 schema 变更前使用 `pg_dump`；
- 新模块 schema 首期不修改 `daily_quote` 主键；但 Phase 0 会审计后更新已有的不完整行情，因此必须将 schema 迁移与数据修复视为两个步骤，数据修复前单独备份 `daily_quote` 并保存逐字段旧值。

### 16.2 Migration

1. 新增通用市场标的、来源映射、行情修订、A 股行情溯源与字段选择、质量、宽度、资金、因子、状态、事件和修复审计表；
2. 建立唯一约束和常用查询索引；
3. 导入配置化标的清单；
4. 对 `daily_quote` 修复先运行 dry-run，输出拟更新主键、逐字段新旧值、来源和校验和；
5. 备份后按 `repair_batch_id` 执行修复，并写入 `daily_quote_repair_audit`；
6. 计算质量快照；
7. 质量通过后回填市场宽度；
8. 外部行情和评分按阶段回填。

### 16.3 Validation

- 迁移前后核心业务表行数一致；`daily_quote` 更新行的旧值、新值和校验和逐条可核对；
- 新表日期唯一性和版本唯一性通过；
- `daily_quote` 抽样行可追溯到来源、批次、数据阶段和标准化单位；
- 随机抽查 5 个交易日的宽度与原始个股行情一致；
- 验证外部行情的 `session_date`、`available_at` 和时区；
- 评分可由证据 JSON 重现；
- 历史重算不修改旧版本。

### 16.4 Rollback

- 停用新调度和 API 功能开关；
- 回滚新增迁移；
- 对指定 `repair_batch_id` 使用审计表恢复 `daily_quote` 旧值，并核对恢复后校验和；必要时从迁移前备份恢复；
- 删除新表前先导出快照、修复审计和配置；
- 现有主升浪、观察池和消息中心不依赖新表才能启动，因此可独立回退。

---

## 17. 实施阶段与验收标准

### Phase 0：修复全市场数据基础（P0）

工作：

- 数据源能力声明；
- 全市场历史补齐；
- 已存在不完整行情的幂等更新；
- 行情来源、批次、盘中/盘后阶段及成交量额单位溯源；
- 整行权威来源选择与字段级选择记录，首版禁止静默跨源拼接；
- 质量快照与校验命令；
- 上市、退市、证券类型、ST 和全天停牌历史；
- 点时证券池快照和股票/指数严格过滤。

验收：

- 连续至少 120 个 A 股交易日的核心行情覆盖率 ≥ 95%；
- 最近 20 日每日覆盖率可追溯；
- `amount` 不完整时系统明确降级；
- 同一日期重跑不产生重复数据；
- 覆盖率分母可由独立证券状态重现，正常停牌与数据缺失可区分；
- 数据修复支持 dry-run、逐字段审计和按批次恢复；
- 任一 `daily_quote` 非空字段都能追溯到具体源记录；
- 校验报告列出缺失和异常代码。

### Phase 1：A 股市场宽度与基础状态（MVP）

工作：

- 数据模型与迁移；
- 宽度、波动和卖压指标；
- 状态快照、API、任务日志；
- 市场状态页面；
- 主升浪只读上下文。

验收：

- 每个分数可展开到原始证据；
- 覆盖不足时输出 `insufficient_evidence`；
- 评分版本可回放；
- 只发布 `market-regime-local-v1` 允许的状态，禁止输出 `repair_confirmed`；
- 初始状态、跨级转换、滞回和数据中断恢复均通过决策矩阵测试夹具；
- 主升浪 `total_score` 和 `market_relative` 原始口径不变，市场上下文不重复计分；
- 页面具备加载、空态、降级和错误状态。

### Phase 2：全球因子与本地相对强弱

工作：

- 通用市场标的和外部行情；
- 交易日、时区与数据可用性账本；
- 因子篮子、beta、残差；
- A 股决策时钟、成分陈旧度和节假日对齐；
- 外部冲击脱敏证据。

验收：

- 不使用 A 股收盘后才可得的同日海外数据；
- 任一残差可复现；
- 每个因子成分收益对应相邻 A 股截止时间和具体行情修订；
- 因子成分和权重有版本；
- 外部源失败不会伪造成中性值。

### Phase 3：ETF 与两融资金证据

工作：

- ETF 份额、净值/价格和估算净申购；
- 两融汇总与可选板块分布；
- 来源权限、限流和补数策略；
- 资金维度接入评分。

验收：

- 单位和估算口径明确；
- 标的名单不被误作余额；
- 缺少付费权限时系统可降级运行；
- 资金证据与价格证据分别展示。

### Phase 4：回测校准与日报集成

工作：

- Walk-forward 校准；
- 二次抛售测试；
- 与主升浪结果的分组评估；
- 消息中心市场状态日报；
- 可选 LLM 解释。

验收：

- 有无市场过滤的基线对比完整；
- 只有 `market-regime-retest-v4` 且核心维度全部通过时才输出 `repair_confirmed`；
- 事件发生日、系统确认日和首次可行动时点可独立回放；
- 不存在未来函数和当前成分回填；
- LLM 失败不影响数值结果；
- 报告明确不确定性和缺失证据。

---

## 18. 主要风险与控制

| 风险 | 后果 | 控制 |
|---|---|---|
| 全市场数据不完整 | 把缺失误判成宽度恶化 | P0 质量闸门，覆盖不足不评分 |
| 数据源无历史能力 | 无法回补和回测 | 适配器能力声明，优先可回补来源 |
| 多源口径不一致 | 指标跳变 | 来源固定、版本化、差异校验 |
| 跨市场日期/收益区间错配 | 未来函数或无经济意义的 beta | A 股决策时钟、`available_at`、成分陈旧度和节假日测试 |
| 当前板块成分回填历史 | 幸存者偏差 | 点时成分或限制用途 |
| `daily_quote` 修复错误 | 污染现有策略与回测 | dry-run、逐字段审计、批次校验和及可执行回滚 |
| 事后低点当作当时信号 | 夸大反转识别能力 | 发生日与确认日分离、追加式事件转换 |
| 相关性被解释为因果 | 错误研究结论 | 文案约束和证据措辞 |
| 评分过度拟合 | 样本内有效、实盘失真 | Walk-forward、稳定性优先、保留基线 |
| 分数替代人工判断 | 产品越界 | 只给候选、证据、风险观察 |
| 主升浪规则被隐式改变 | 历史不可比 | 上下文独立，不修改策略分数 |

---

## 19. 待评审决策

以下问题在进入实现前由主管确认：

1. Phase 0 的全市场历史主数据源及权限预算；
2. 首批 A 股宽基指数和海外因子标的清单；
3. 评分版本的首个冻结窗口和回测区间；
4. 是否在 MVP 同时建设行业点时成分；
5. 市场状态页的导航位置；
6. 是否允许管理员手动重算，以及可重算的最大日期范围；
7. ETF、两融数据的供应商成本和使用条款。

---

## 20. 推荐的下一任务

不要立刻实现反转评分。下一项任务应是：

> **设计并实现全市场日线数据质量快照与校验命令，修复盘后数据补齐和不完整行更新。**

该任务完成后，用真实覆盖报告决定 Phase 1 可以启用哪些指标。这样可以先解决当前最会污染所有结论的根因，并为主升浪回测、市场宽度和未来因子研究共同提供可靠底座。
