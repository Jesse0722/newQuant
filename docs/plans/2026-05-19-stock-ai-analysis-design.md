# 股票详情 AI 智能分析设计文档

## 背景

股票详情页当前已经具备 K 线、指标、监控提醒、交易明细、核心关注等工作流能力；观察池详情中也已有 `AI 智能分析` 雏形，但现状主要是将少量技术指标拼成 prompt 后写回 `watch_stock.ai_analysis`。这会带来三类问题：

- 分析数据偏薄，无法支撑“基本面、消息面、技术面”的综合判断。
- 分析结果绑定观察池股票，同一只股票在股票详情页或跨池场景难以复用。
- 输出结构过短，缺少证据、数据质量、观察计划和风险边界。

本设计把 AI 分析定义为“基于系统内客观数据生成的结构化研究快照”，用于辅助用户判断是否继续跟踪，不直接给出收益承诺或确定性买卖指令。

## 目标

- 在股票详情页提供一份可刷新、可缓存、可追溯的 AI 分析卡片。
- 接入 DeepSeek V4，支持快速分析与深度分析的模型分层。
- 分析覆盖技术面、基本面可用性、消息面、交易观察和风险。
- 保留观察池原有 AI 分析按钮，并复用新服务。
- 明确数据不足时的表达，禁止模型编造财务或消息结论。

## 非目标

- 不做自动交易。
- 不承诺收益，不输出强制买卖信号。
- V1 不强制接入完整财报数据；基本面字段可先标记为数据不足。
- V1 不做复杂多轮 Agent 或外部实时搜索。

## 模型接入

DeepSeek V4 官方 API 支持 OpenAI ChatCompletions 兼容接口。V1 增加 provider：

```env
AI_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_FAST_MODEL=deepseek-v4-flash
```

模型使用策略：

- `deep`：`deepseek-v4-pro`，用于手动深度分析。
- `fast`：`deepseek-v4-flash`，用于快速刷新、后续批量或列表摘要。
- temperature 固定低温，建议 `0.1-0.2`。
- 输出必须是 JSON，由后端解析、校验、补默认值后保存。

## 数据输入

后端先构造 `StockAnalysisSnapshot`，再交给模型。V1 数据来源：

- 股票基础信息：`stock_basic`。
- 行情与指标：`daily_quote`、MA5/10/20、MACD、RSI、20 日价格位置、5 日量比。
- 买点雷达/战法摘要：复用现有 limit-up tactics 与信号逻辑。
- 消息面：`message_opportunity`、`message_source_item` 中最近 30 天同 `ts_code` 数据。
- 用户上下文：观察池备注、涨停日期、最近交易明细。
- 基本面：V1 仅声明系统暂未接入完整财务指标，避免模型编造。

## 输出结构

统一保存版本化 JSON：

```json
{
  "version": "1.0",
  "rating": "强关注|观察|谨慎|回避",
  "score": 0,
  "confidence": 0,
  "trend": "上涨|震荡|下跌",
  "time_horizon": "短线|波段|中线",
  "summary": "...",
  "sections": {
    "technical": {
      "score": 0,
      "conclusion": "...",
      "evidence": ["..."],
      "risk": "..."
    },
    "fundamental": {
      "score": null,
      "conclusion": "数据不足",
      "evidence": [],
      "risk": "..."
    },
    "news": {
      "score": 0,
      "conclusion": "...",
      "evidence": ["..."],
      "risk": "..."
    },
    "trading": {
      "score": null,
      "conclusion": "...",
      "evidence": [],
      "risk": "..."
    }
  },
  "watch_plan": {
    "key_levels": {
      "support": [],
      "pressure": [],
      "risk_line": null
    },
    "trigger_conditions": [],
    "invalid_conditions": [],
    "next_review": "..."
  },
  "data_quality": {
    "score": 0,
    "warnings": []
  },
  "disclaimer": "仅基于系统内数据生成，用于研究记录，不构成投资建议"
}
```

## 存储

新增 `stock_ai_analysis` 表，保存每次分析记录：

- `id`
- `ts_code`
- `scope`
- `pool_id`
- `watch_stock_id`
- `mode`
- `model_provider`
- `model_name`
- `prompt_version`
- `snapshot_json`
- `analysis_json`
- `raw_response`
- `data_trade_date`
- `status`
- `error_message`
- `created_at`
- `updated_at`

`watch_stock.ai_analysis` 暂时保留，用于兼容观察池原有 UI。新服务成功后同步写入该字段。

## API

股票详情域新增：

```http
GET /api/stocks/{ts_code}/ai-analysis
```

返回该股票最近一次成功分析。

```http
POST /api/stocks/{ts_code}/ai-analysis
```

请求：

```json
{
  "mode": "deep",
  "scope": "stock_detail",
  "pool_id": null,
  "watch_stock_id": null,
  "force_refresh": false
}
```

响应返回分析记录、结构化分析、分析时间、模型名与数据交易日。

兼容接口：

```http
POST /api/strategy/ai-analyze
```

继续支持观察池传入 `stock_id`，内部改走新服务。

## 前端交互

股票详情页在 K 线图下方增加 `AI 智能分析` 卡片：

- 展示评级、分数、置信度、趋势、分析时间。
- 支持 `快速分析` 与 `深度分析`。
- 展示综合摘要、技术面、基本面、消息面、交易观察。
- 展示观察计划：支撑、压力、风险线、触发条件、失效条件。
- 展示数据质量提示。

观察池详情卡片 V1 可先保持现有简版展示，由后端返回兼容字段；后续可抽取统一组件。

## 风险与边界

- 输出固定免责声明。
- 禁止模型基于缺失数据生成财务结论。
- 模型非 JSON 返回时后端抽取 JSON；仍失败则返回可读错误。
- 远端模型超时或未配置 API key 时不影响股票详情主页面。

## 后续演进

- 接入 Tushare `daily_basic` 与财务指标表，补强基本面。
- 支持分析历史对比，展示“本次相对上次变化”。
- 支持批量刷新核心关注池。
- 支持从 AI 观察计划一键生成监控规则。
