# 消息中心与 X 舆情采集技术方案

> 日期：2026-05-14
> 最新更新：2026-05-16
> 状态：MVP 已实现，待 PR 合并
> 目标：把 AI 产业舆情从“人工浏览”沉淀为可追溯、可去重、可聚合、可进入观察池/买点雷达的系统对象。

## 1. 设计原则

消息中心不直接生成买卖信号。它负责发现题材、保留来源、提示候选标的；交易动作仍由用户判断，买点确认仍交给买点雷达。

MVP 坚持三条边界：

- 先接 X recent search，不做全网爬虫和实时流。
- 先处理公开文本和公开互动指标，不处理图片、视频、Space、长线程还原。
- 先输出题材与候选机会，不做自动交易、复杂 Agent、收益归因。

## 2. 当前能力

已落地能力：

- 原始消息层 `message_source_item`，保存渠道原文、链接、发布时间、标签、热度、可信度、去重键和原始载荷。
- 统一导入接口 `/api/messages/source-items/import`，支持外部采集器、手工导入、文件导入或 webhook 统一写入。
- 题材聚合 `message_topic`，按日期、题材、渠道数和消息量生成热度、可信度、拥挤度与生命周期。
- 个股机会 `message_opportunity`，按题材和股票聚合，生成机会分、风险分、建议动作和来源链接。
- X recent search 采集接口 `/api/messages/x/collect`。
- X 种子池：关键词、账号、海外线索到 A 股候选映射。
- 前端消息中心右上角“采集X”按钮，可触发小批量采集并刷新页面。

## 3. 数据流

```text
X recent search
  -> X 原始帖子
  -> 关键词命中与主题识别
  -> 海外 ticker/产业词到 A 股候选映射
  -> MessageSourceItem
  -> 去重
  -> Topic 聚合
  -> Opportunity 聚合
  -> /api/messages/daily
  -> 消息中心页面
  -> 核心关注 / 股票详情 / 买点雷达
```

其他渠道后续统一接入同一条链路：

```text
雪球 / 淘股吧 / 小红书 / RSS / 手动文件 / webhook
  -> /api/messages/source-items/import
  -> 后续流程相同
```

## 4. 配置与密钥

后端环境变量：

```env
X_API_BEARER_TOKEN=your_x_api_bearer_token
X_API_BASE_URL=https://api.twitter.com
```

说明：

- `X_API_BEARER_TOKEN` 必填，否则 `/api/messages/x/collect` 会返回配置错误。
- `X_API_BASE_URL` 默认使用 `https://api.twitter.com`。本地验证中 `https://api.x.com` 出现 TLS 断开，保留环境变量便于后续调整。
- X 当前是 pay-per-use/credits 模式，MVP 默认小批量采集，避免成本失控。
- 不要提交 `backend/.env`，只提交 `.env.example`。

## 5. 种子配置

种子池位于 `backend/app/seeds/`，随代码版本化。

| 文件 | 作用 |
|---|---|
| `message_keywords.csv` | AI 产业关键词，包含 keyword/type/theme/priority/language |
| `message_x_accounts.csv` | X 重点账号池，包含 handle/category/theme/weight/status |
| `message_x_stock_mappings.csv` | X 海外语境到 A 股候选映射 |

### 5.1 关键词种子

关键词覆盖：

- AI算力、AI服务器、数据中心
- 半导体、ASIC、NVIDIA产业链
- HBM、DRAM、NAND、存储涨价
- 光模块、CPO、800G、1.6T、硅光
- 液冷、AI电力、电源、变压器容量
- PCB、铜连接
- AI应用、机器人、人形机器人

关键词字段：

| 字段 | 说明 |
|---|---|
| keyword | 搜索关键词 |
| type | industry / product / company / catalyst |
| theme | 归属题材 |
| priority | 1-5，X 默认采集优先使用高优先级关键词 |
| language | en / zh |

### 5.2 X 账号池

账号池用于后续扩展“重点账号采集”和可信度调权。当前 MVP 的 recent search 主要按关键词采集，账号池已先版本化。

重点类别：

- 官方账号：Nvidia、AMD、Micron、Broadcom、Intel、OpenAI 等
- 半导体研究：SemiAnalysis、TrendForce 等
- 科技/市场信息源：DeItaone、ServeTheHome、TheTranscript 等

### 5.3 海外线索到 A 股候选映射

X 上大量帖子不会出现 A 股代码，需要用海外 ticker、公司名、产业词映射到 A 股候选池。

示例：

| 触发词 | 主题 | A 股候选 |
|---|---|---|
| MU / Micron / HBM / SK Hynix | 存储芯片 | 300475.SZ 香农芯创 |
| NVDA / Nvidia | NVIDIA产业链 | 300308.SZ 中际旭创 |
| Blackwell / GB200 / NVL72 | NVIDIA产业链 | 601138.SH 工业富联 |
| CPO / Co-packaged optics | 光模块 | 300502.SZ 新易盛 |
| Liquid cooling | 液冷 | 300442.SZ 润泽科技 |
| AI power demand | AI电力 | 300274.SZ 阳光电源 |
| Tesla Optimus / Humanoid robot | 机器人 | 002050.SZ 三花智控 |

映射只代表“候选关注”，不是交易建议。后续应继续用买点雷达、财务验证和人工判断过滤。

## 6. 后端模型

### 6.1 message_source_item

原始消息表，所有渠道先进入这里。

| 字段 | 说明 |
|---|---|
| id | UUID |
| trade_date | YYYYMMDD |
| channel | 渠道，如 X / 雪球 / 淘股吧 / 小红书 / RSS |
| source_name | 作者、账号、栏目或导入源 |
| external_id | 外部平台原始 ID |
| title | 标题，可空 |
| content | 原文或摘要 |
| url | 原文链接 |
| published_at | 原文发布时间 |
| captured_at | 入库时间 |
| theme | 归属题材 |
| ts_code | A 股候选代码，可空 |
| stock_name | A 股候选名称，可空 |
| tags | 标签 |
| sentiment | positive / neutral / negative |
| heat_score | 单条消息热度分 |
| credibility_score | 单条消息可信度分 |
| dedupe_key | 去重 hash |
| raw_payload | 渠道原始载荷 |
| status | new / processed / ignored |

去重口径：

```text
trade_date + channel + (external_id or url or content) + theme + ts_code
```

同一条 X 帖子可映射到不同 A 股候选，因此去重键包含 `theme` 和 `ts_code`。

### 6.2 message_topic

题材聚合表。

| 字段 | 说明 |
|---|---|
| trade_date | YYYYMMDD |
| theme | 题材名称 |
| summary | 题材摘要 |
| lifecycle_stage | early / spreading / climax / cooling |
| sentiment | positive / neutral / negative |
| heat_score | 热度分 |
| credibility_score | 可信度分 |
| crowding_score | 拥挤度 |
| source_platforms | 来源平台 |
| tags | 标签 |

唯一约束：`trade_date + theme`。

### 6.3 message_opportunity

个股机会表。

| 字段 | 说明 |
|---|---|
| topic_id | 关联题材 |
| trade_date | YYYYMMDD |
| theme | 冗余题材 |
| ts_code | 股票代码 |
| stock_name | 股票名称 |
| opportunity_score | 机会分 |
| heat_score | 热度分 |
| credibility_score | 可信度分 |
| risk_score | 风险分 |
| action_suggestion | watch / add_to_pool / risk_watch |
| reason | 机会逻辑 |
| catalysts | 催化剂 |
| risks | 风险 |
| source_platforms | 来源平台 |
| source_links | 来源链接 |
| status | active / dismissed / archived |

## 7. 聚合与评分

### 7.1 Topic 聚合

按 `trade_date + theme` 聚合原始消息：

- 消息越多，热度越高。
- 渠道越多，热度和可信度加分。
- 消息量和渠道共振推高拥挤度。
- 拥挤度过高时生命周期倾向 `climax`。

### 7.2 Opportunity 聚合

按 `trade_date + theme + ts_code` 聚合：

- `heat_score` 来自消息平均热度、消息量和渠道共振。
- `credibility_score` 来自来源可信度和渠道数。
- `risk_score` 来自热度过高、消息量过大导致的拥挤风险。
- `opportunity_score` 综合热度、可信度、风险和渠道加分。

当前建议动作：

| 条件 | action_suggestion |
|---|---|
| 机会分高且风险不过热 | add_to_pool |
| 风险分过高 | risk_watch |
| 其他 | watch |

## 8. API

### GET `/api/messages/daily`

查询每日题材和机会。

参数：

| 参数 | 说明 |
|---|---|
| trade_date | 可选，YYYYMMDD，默认上海自然日 |
| ensure_seed | 可选，默认 true；无数据时生成示例种子机会 |

### POST `/api/messages/source-items/import`

批量导入原始消息，并可立即聚合。

请求示例：

```json
{
  "aggregate": true,
  "items": [
    {
      "trade_date": "20260514",
      "channel": "雪球",
      "source_name": "产业观察",
      "title": "CPO 光模块热度提升",
      "content": "CPO 光模块方向被反复提及，新易盛关注度提升。",
      "url": "https://example.test/a",
      "theme": "CPO",
      "ts_code": "300502.SZ",
      "stock_name": "新易盛",
      "tags": ["光模块", "CPO"],
      "heat_score": 78,
      "credibility_score": 70
    }
  ]
}
```

返回重点：

```json
{
  "created_count": 1,
  "skipped_count": 0,
  "aggregation": {
    "trade_date": "20260514",
    "topic_count": 1,
    "opportunity_count": 1,
    "source_item_count": 1
  }
}
```

### GET `/api/messages/x/seeds`

返回 X 使用的关键词池、账号池和主题摘要，用于检查配置是否加载成功。

### POST `/api/messages/x/collect`

从 X recent search 拉取最近 7 天的公开帖子，转换为 `message_source_item` 并聚合。

请求示例：

```json
{
  "trade_date": "20260516",
  "query": "HBM -is:retweet lang:en",
  "max_results": 10,
  "aggregate": true
}
```

默认请求示例：

```json
{
  "min_priority": 5,
  "keyword_limit": 12,
  "max_results": 20,
  "aggregate": true
}
```

说明：

- `query` 为空时由高优先级关键词自动拼接查询。
- `max_results` 范围 10-100。
- 当前只采集 recent search，不使用 streaming rules。

## 9. 前端页面

路由：`/messages`

页面能力：

- 顶部统计：题材数、机会数、最高分、强势题材。
- 题材卡片：摘要、生命周期、情绪、热度、可信度、拥挤度、来源平台。
- 个股机会表：标的、题材、机会分、建议、逻辑、催化剂、风险、来源、操作。
- 筛选：题材筛选、高分机会开关。
- 操作：刷新、采集X、查看股票详情、加入核心关注。

“采集X”按钮默认参数：

```json
{
  "min_priority": 5,
  "keyword_limit": 12,
  "max_results": 20,
  "aggregate": true
}
```

## 10. 本地验证

### 10.1 配置 token

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
cp .env.example .env
```

在 `.env` 中配置：

```env
X_API_BEARER_TOKEN=your_x_api_bearer_token
```

### 10.2 启动服务

```bash
cd /Users/lijiajun/ai-coding/newQuant
./restart-dev.sh
```

### 10.3 检查种子池

```bash
curl -sS http://127.0.0.1:8000/api/messages/x/seeds
```

### 10.4 小批量真实采集

```bash
curl -sS -X POST http://127.0.0.1:8000/api/messages/x/collect \
  -H 'Content-Type: application/json' \
  -d '{"query":"HBM -is:retweet lang:en","max_results":10,"aggregate":true}'
```

预期：

- `raw_count` 大于 0。
- `created_count` 或 `skipped_count` 有值。
- `aggregation.topic_count` 大于 0。
- 若命中映射表，`aggregation.opportunity_count` 大于 0。

### 10.5 自动化验证

```bash
cd /Users/lijiajun/ai-coding/newQuant/backend
./venv/bin/pytest tests/test_messages_api.py
```

```bash
cd /Users/lijiajun/ai-coding/newQuant/frontend
npm run build
```

当前验证结果：

```text
backend tests/test_messages_api.py: 8 passed
frontend npm run build: passed
```

## 11. 成本与合规

- X API 使用 pay-per-use credits，采集按钮默认小批量请求。
- 不开启自动充值，避免成本失控。
- 不转售 X 数据。
- 不对外分发原始 X 内容。
- 不做用户画像、敏感信息推断、广告投放、自动互动、刷量或监控个人。
- 系统只用于内部研究、题材分析和来源回溯。

## 12. 当前限制

- X recent search 只覆盖最近 7 天。
- 当前只处理文本，不处理图片、视频、Space、长线程。
- 当前 A 股映射为种子表规则，需继续校准。
- 当前没有对垃圾内容、低质账号、机器人账号做系统过滤。
- 当前示例种子机会仍会在 `ensure_seed=true` 时生成，后续真实采集稳定后应改成手动示例模式。

## 13. 后续计划

优先级从高到低：

1. 增加消息来源质量过滤：低互动、疑似 spam、纯喊单、无主题内容降权或忽略。
2. 扩展 A 股映射表：按题材维护核心候选池和替代候选池。
3. 增加 X 重点账号采集模式：按账号池拉取高可信来源内容。
4. 前端增加采集参数面板：主题、关键词、数量、是否聚合。
5. 接入雪球：重点补 A 股映射和产业链逻辑。
6. 接入淘股吧：重点补短线情绪、龙头/卡位/弱转强。
7. 接入小红书：只做扩散和拥挤度指数。
8. 将高分机会一键加入核心关注后，触发现有买点雷达扫描。
