# 舆情模块 Agent 化技术方案

> 日期：2026-06-12
> 状态：设计稿
> 目标：把现有消息中心从“规则聚合与产业链日报”升级为“可审计、可复核、可进入观察池工作流的舆情研究 Agent 系统”。

## 1. 背景

当前 `newQuant` 已经形成主工作流：

```text
观察池 -> 买点雷达 -> 买点提醒 -> 交易计划 -> 执行记录 -> 复盘
```

消息中心 MVP 已落地以下能力：

- `message_source_item` 保存原始消息、来源、链接、发布时间、热度、可信度、去重键和原始载荷。
- `message_topic` 按日期和题材聚合热度、可信度、拥挤度和生命周期。
- `message_opportunity` 按题材和股票聚合候选机会。
- X recent search 已接入，并有关键词池、账号池和海外产业词到 A 股候选映射。
- 产业链 GraphRAG Lite 已有实体、关系、证据、日报和候选标的模型。
- 消息中心前端已经展示今日题材、个股机会和产业链日报。

当前主要问题：

- 机会结论缺少可审计的证据对象，只保留平台和链接，不能稳定追溯到具体消息片段、触发词、映射关系和置信度。
- X 文本识别与 A 股映射仍以关键词和 substring 为主，误映射和弱证据候选难以区分。
- 消息中心和产业链日报是两条相对并行的管线，证据没有充分合流。
- 每日结论偏模板摘要，不足以承担“研究助理”的解释、反证、风险审查和待验证提示。
- 前端缺少证据展开、人工复核、采纳/驳回和反馈闭环。

本方案建议以“受监督的舆情研究 Agent”为目标演进，而不是做一个自动交易 Agent。

## 2. 产品定位

### 2.1 一句话

舆情 Agent 负责把多源消息整理成证据充分、风险明确、可复核的题材和个股候选，帮助用户决定“今天看什么、为什么看、下一步如何验证”。

### 2.2 不做什么

- 不自动交易。
- 不生成确定买入或卖出指令。
- 不承诺收益。
- 不把 LLM 输出作为唯一事实来源。
- 不自动覆盖人工复核后的研究结论。
- 不把弱证据映射包装成强结论。

### 2.3 推荐表述

Agent 输出建议使用：

- 候选
- 观察
- 待验证
- 证据不足
- 风险观察
- 加入观察池等待买点雷达确认

避免使用：

- 必涨
- 稳赚
- 确定买入
- 强烈推荐买入
- 无风险

## 3. 目标

- 建立统一证据层，让题材、机会、产业链候选和日报都能追溯到具体消息、证据片段、触发词、映射路径和置信度。
- 引入分工明确的 agent pipeline，替代单一大模型自由发挥。
- 让 LLM 主要承担文本理解、实体抽取、关系抽取、摘要和风险解释；评分、去重、权限和交易安全继续由规则系统控制。
- 在消息中心增加人工复核入口，支持采纳、驳回、降级、加入观察池和反馈低质量候选。
- 记录 agent 运行、输入、输出、失败原因和用户反馈，为后续评测和迭代提供数据。
- 保持现有消息中心、产业链日报、观察池和买点雷达工作流兼容。

## 4. 非目标

- 第一版不做开放式聊天问答。
- 第一版不做全网爬虫和实时流。
- 第一版不引入独立图数据库。
- 第一版不做自动交易、自动下单或仓位建议。
- 第一版不做复杂回测归因。
- 第一版不追求完全自动判断题材生命周期，先用规则加人工可复核解释。

## 5. 设计原则

### 5.1 Evidence First

每个候选结论必须能够回答：

- 来源是哪几条消息？
- 关键证据片段是什么？
- 触发了哪些关键词、实体或关系？
- 映射到 A 股候选的路径是什么？
- 置信度如何计算？
- 还有哪些证据不足或反向风险？

### 5.2 Human in the Loop

Agent 可以生成候选和草稿，但以下动作默认需要用户确认：

- 加入核心关注。
- 标记高优先级观察。
- 生成正式交易计划。
- 修改人工复核后的结论。
- 删除或归档用户研究记录。

### 5.3 Rules Before LLM

优先用规则、SQL、指标和显式配置解决：

- 去重。
- 限流。
- 数据校验。
- 分数归一化。
- 权限控制。
- 禁止词过滤。
- 状态流转。

LLM 主要用于：

- 主题归类。
- 实体与关系抽取。
- 证据片段提取。
- 反证和风险提示。
- 结构化报告生成。
- 用户可读解释。

### 5.4 Small Reversible Changes

第一阶段只新增证据层和候选草稿，不破坏现有 `message_topic`、`message_opportunity` 和产业链日报输出。

## 6. 总体架构

```text
多源采集
  -> message_source_item 原始消息
  -> Evidence Cleaner Agent 证据清洗
  -> Entity Mapping Agent 实体与 A 股映射
  -> Topic Cluster Agent 题材聚合
  -> Opportunity Scoring Agent 候选评分
  -> Risk Review Agent 风险审查
  -> Report Agent 每日结论/日报
  -> 人工复核
  -> 观察池 / 买点雷达 / 交易计划草稿 / 复盘
```

核心变化：

- `message_source_item` 继续作为原始消息入口。
- 新增统一证据层，保存 agent 从原始消息中抽取出的证据。
- 新增 agent 运行记录，保存每次 agent 的输入摘要、输出、模型、版本、状态和错误。
- 新增候选草稿或复核状态，避免 agent 聚合直接覆盖人工研究结论。
- GraphRAG 候选和消息机会共用证据层。

## 7. Agent 分工

### 7.1 Collector Agent

职责：

- 根据关键词、账号、平台策略触发采集。
- 控制 X API 成本、max results、调用频率和失败重试。
- 保存原始消息到 `message_source_item`。

输入：

- 关键词池。
- 账号池。
- trade_date。
- 平台配置。

输出：

- 原始消息。
- 采集统计。
- 失败原因。

实现建议：

- 第一版仍以规则和现有 X recent search 为主。
- 不需要 LLM。
- 适合放在 scheduler 或后台任务中。

### 7.2 Evidence Cleaner Agent

职责：

- 对原始消息做质量过滤。
- 提取证据片段。
- 判断消息是否是产业线索、纯情绪、广告、spam、低价值转发或噪声。
- 标注支持、风险、反证或中性证据。

输入：

- `message_source_item`。

输出：

```json
{
  "source_item_id": "...",
  "quality_score": 72,
  "evidence_text": "HBM supply remains tight...",
  "stance": "support",
  "themes": ["存储芯片"],
  "entities": ["HBM", "Micron"],
  "risk_flags": [],
  "confidence": 78
}
```

实现建议：

- 第一版使用规则质量过滤加 LLM 结构化抽取。
- 对 spam、短文本、广告、交易群引流直接降权或忽略。

### 7.3 Entity Mapping Agent

职责：

- 把海外 ticker、公司名、产品、技术、行业词映射到 A 股候选。
- 输出映射路径和置信度。
- 区分“直接公司关系”“产业链关系”“弱主题映射”。

输入：

- 证据片段。
- 关键词池。
- 股票基础信息。
- `message_entity` / `message_relation` 图谱。
- 种子映射表。

输出：

```json
{
  "source_item_id": "...",
  "theme": "存储芯片",
  "ts_code": "300475.SZ",
  "stock_name": "香农芯创",
  "mapping_type": "industry_chain",
  "matched_terms": ["HBM", "Micron"],
  "mapping_path": ["HBM", "存储芯片", "香农芯创"],
  "mapping_confidence": 68,
  "needs_review": true
}
```

实现建议：

- 第一版先基于现有 `message_x_stock_mappings.csv`、图谱关系和规则增强。
- LLM 只负责实体识别和解释，不直接决定最终评分。

### 7.4 Topic Cluster Agent

职责：

- 按日期聚合题材。
- 识别同义主题。
- 生成题材摘要、热度、可信度、拥挤度和生命周期解释。

输入：

- 证据记录。
- `message_source_item`。
- 历史 `message_topic`。

输出：

```json
{
  "trade_date": "20260612",
  "theme": "存储芯片",
  "summary": "...",
  "lifecycle_stage": "spreading",
  "lifecycle_reason": "消息数增加且来源从 X 扩散到财经媒体",
  "heat_score": 82,
  "credibility_score": 70,
  "crowding_score": 46
}
```

实现建议：

- 分数用规则。
- 摘要和生命周期解释可用 LLM。
- 同义主题需要维护 alias 或主题归并表。

### 7.5 Opportunity Scoring Agent

职责：

- 基于题材、证据、映射路径和风险生成个股候选。
- 输出候选分、风险分、证据强度和建议动作。
- 只生成草稿或候选，不直接覆盖人工确认结果。

输入：

- 题材聚合。
- 证据记录。
- 映射记录。
- 图谱路径。
- 股票基础信息。

输出：

```json
{
  "trade_date": "20260612",
  "theme": "存储芯片",
  "ts_code": "300475.SZ",
  "stock_name": "香农芯创",
  "opportunity_score": 76,
  "evidence_score": 68,
  "risk_score": 52,
  "action_suggestion": "watch",
  "reason": "...",
  "evidence_ids": ["..."],
  "risks": ["产业链映射仍需公告或权威媒体验证"]
}
```

### 7.6 Risk Review Agent

职责：

- 检查候选是否夸大结论。
- 检查是否出现禁止投资建议措辞。
- 标记证据不足、单一来源、过度拥挤、弱映射、疑似广告来源。
- 将候选降级为 `risk_watch` 或 `needs_review`。

输入：

- 候选草稿。
- 证据记录。
- 原始消息。

输出：

```json
{
  "candidate_id": "...",
  "review_status": "needs_review",
  "risk_flags": ["single_source", "weak_mapping"],
  "safe_summary": "该候选仅代表产业链映射，需等待更多证据验证。"
}
```

实现建议：

- 第一版可用规则加禁词过滤。
- LLM 输出需要再经过规则 sanitizer。

### 7.7 Report Agent

职责：

- 生成每日舆情结论。
- 生成题材解释、候选摘要、风险提示和下一步动作。
- 只基于结构化证据和候选输入，不自由补充事实。

输入：

- Top topics。
- Reviewed candidates。
- Evidence records。
- Risk flags。

输出：

```json
{
  "headline": "今日主线：存储芯片热度提升",
  "summary": "...",
  "top_topics": [],
  "top_candidates": [],
  "risk_flags": [],
  "next_actions": ["加入观察池等待买点雷达确认"]
}
```

## 8. 状态流转

### 8.1 原始消息状态

```text
new -> processed -> ignored
```

建议新增或通过 tag 表达：

```text
new -> cleaned -> mapped -> aggregated -> ignored
```

### 8.2 候选机会状态

建议从当前 `active / dismissed / archived / demo` 演进为：

```text
draft -> needs_review -> reviewed -> accepted -> dismissed -> archived
```

含义：

| 状态 | 含义 |
|---|---|
| draft | agent 或规则刚生成，未审查 |
| needs_review | 证据不足、弱映射或风险较高，需要人工看 |
| reviewed | 已通过风险审查，可展示 |
| accepted | 用户采纳，例如加入观察池 |
| dismissed | 用户驳回 |
| archived | 历史归档 |

兼容策略：

- 现有 `active` 可映射为 `reviewed`。
- 现有 `dismissed / archived` 保持含义。
- `demo` 不再混入真实数据查询，通过 seed/demo 独立标记或脚本清理。

## 9. 数据模型设计

### 9.1 新增 message_evidence

统一证据表，承接消息中心机会、产业链日报和后续复盘。

| 字段 | 说明 |
|---|---|
| id | UUID |
| source_item_id | 原始消息 ID |
| trade_date | YYYYMMDD |
| channel | 来源渠道 |
| theme | 题材，可空 |
| ts_code | 股票代码，可空 |
| evidence_text | 证据片段 |
| stance | support / risk / contradiction / neutral |
| quality_score | 文本质量分 |
| credibility_score | 可信度分 |
| confidence | 抽取置信度 |
| extraction_method | rule / llm / manual |
| extractor_name | agent 名称 |
| extractor_version | agent/prompt 版本 |
| raw_json | 原始结构化输出 |
| status | active / ignored |
| created_at | 时间 |

索引：

```text
message_evidence(trade_date, theme)
message_evidence(trade_date, ts_code)
message_evidence(source_item_id)
message_evidence(status)
```

### 9.2 新增 message_opportunity_evidence

候选机会与证据的多对多关联。

| 字段 | 说明 |
|---|---|
| id | UUID |
| opportunity_id | 机会 ID |
| evidence_id | 证据 ID |
| role | support / risk / contradiction |
| weight | 证据权重 |
| created_at | 时间 |

约束：

```text
unique(opportunity_id, evidence_id, role)
```

### 9.3 新增 message_agent_run

记录每次 agent 运行。

| 字段 | 说明 |
|---|---|
| id | UUID |
| agent_name | collector / evidence_cleaner / entity_mapper / topic_cluster / opportunity_scorer / risk_reviewer / reporter |
| agent_version | 版本 |
| trade_date | YYYYMMDD，可空 |
| input_ref_type | source_item / evidence / topic / opportunity / batch |
| input_ref_id | 输入对象 ID，可空 |
| input_digest | 输入摘要或 hash |
| output_json | 结构化输出 |
| model_provider | rules / deepseek / openai / qwen / ollama |
| model_name | 模型名 |
| prompt_version | Prompt 版本 |
| status | success / failed / skipped |
| error_message | 错误信息 |
| started_at | 开始时间 |
| finished_at | 结束时间 |
| duration_ms | 耗时 |

### 9.4 扩展 message_opportunity

建议新增字段：

| 字段 | 说明 |
|---|---|
| evidence_score | 证据强度分 |
| mapping_confidence | A 股映射置信度 |
| review_status | draft / needs_review / reviewed / accepted / dismissed / archived |
| review_reason | 审查原因 |
| generated_by | rule / agent / manual |
| accepted_at | 用户采纳时间 |
| dismissed_at | 用户驳回时间 |

兼容说明：

- 现有 `status` 可先保留，新增 `review_status` 作为 agent 化状态。
- 后续稳定后再考虑合并字段。

### 9.5 可选新增 message_topic_alias

用于同义主题归并。

| 字段 | 说明 |
|---|---|
| id | UUID |
| alias | 别名，如 HBM与存储 |
| canonical_theme | 标准题材，如 存储芯片 |
| language | zh / en |
| status | active / disabled |

## 10. API 设计

### 10.1 Agent 运行 API

```text
POST /api/message-agents/run
GET  /api/message-agents/runs
GET  /api/message-agents/runs/{id}
```

请求示例：

```json
{
  "agent_name": "evidence_cleaner",
  "trade_date": "20260612",
  "source_item_ids": ["..."],
  "dry_run": false
}
```

### 10.2 证据查询 API

```text
GET /api/messages/evidence
GET /api/messages/opportunities/{id}/evidence
```

支持过滤：

- trade_date
- theme
- ts_code
- stance
- status
- source_item_id

### 10.3 候选复核 API

```text
POST /api/messages/opportunities/{id}/review
POST /api/messages/opportunities/{id}/accept
POST /api/messages/opportunities/{id}/dismiss
```

复核请求示例：

```json
{
  "review_status": "reviewed",
  "review_reason": "证据来自两条独立消息，但仍需公告验证",
  "risk_flags": ["weak_mapping"]
}
```

### 10.4 每日 Agent 结论 API

```text
GET  /api/messages/agent-daily
POST /api/messages/agent-daily/generate
```

输出包含：

- headline
- summary
- top topics
- reviewed candidates
- risk watch candidates
- evidence coverage
- next actions

## 11. 前端设计

### 11.1 消息中心新增区域

在现有消息中心中增加三个可操作视图：

1. 今日候选
2. 证据审阅
3. Agent 运行记录

### 11.2 今日候选表

建议字段：

- 标的
- 题材
- 机会分
- 证据分
- 映射置信度
- 风险分
- 状态
- 主要证据
- 风险提示
- 操作

操作：

- 展开证据
- 加入观察池
- 标记已复核
- 驳回
- 查看股票详情

### 11.3 证据抽屉

点击候选后展开：

- 原始消息片段。
- 来源链接。
- 触发词。
- 实体。
- 映射路径。
- 支持证据。
- 风险/反证证据。
- agent 输出 JSON 摘要。

### 11.4 Agent 运行记录

展示：

- agent 名称。
- 状态。
- 输入数量。
- 输出数量。
- 失败原因。
- 模型和 prompt 版本。
- 耗时。

## 12. 调度设计

推荐第一版每日流程：

```text
09:00 导入关键词和种子检查
09:05 X 小批量采集
09:10 Evidence Cleaner Agent
09:15 Entity Mapping Agent
09:20 Topic Cluster Agent
09:25 Opportunity Scoring Agent
09:30 Risk Review Agent
09:35 Report Agent
```

盘中可手动触发：

- 采集 X。
- 重新清洗今日消息。
- 重新生成候选。
- 重新生成日报。

成本控制：

- 每日默认只处理新增消息。
- LLM agent 支持 batch。
- 对同一 `source_item_id + agent_version` 做幂等跳过。
- 保留 dry-run。

## 13. LLM Prompt 与输出约束

所有 LLM agent 必须：

- 只返回 JSON。
- 不输出 Markdown。
- 不输出买卖建议。
- 不承诺收益。
- 对证据不足明确写 `待验证`。
- 输出 `confidence`。
- 输出 `risk_flags`。
- 输出 `source_item_id` 或证据引用。

### 13.1 Evidence Cleaner Prompt 输出

```json
{
  "is_relevant": true,
  "quality_score": 72,
  "themes": ["存储芯片"],
  "entities": [
    {"type": "product", "name": "HBM"},
    {"type": "company", "name": "Micron"}
  ],
  "evidence": [
    {
      "text": "...",
      "stance": "support",
      "confidence": 78
    }
  ],
  "risk_flags": []
}
```

### 13.2 Risk Review Prompt 输出

```json
{
  "review_status": "needs_review",
  "risk_flags": ["weak_mapping", "single_source"],
  "safe_summary": "该候选仅代表产业链映射，需等待更多证据验证。",
  "unsafe_terms_found": []
}
```

## 14. 评分设计

### 14.1 题材分

建议公式：

```text
heat_score =
  message_count_score * 0.35
  + source_diversity_score * 0.25
  + engagement_score * 0.20
  + freshness_score * 0.20
```

```text
credibility_score =
  source_quality_score * 0.40
  + evidence_quality_score * 0.30
  + cross_source_confirmation * 0.20
  + agent_confidence * 0.10
```

```text
crowding_score =
  message_velocity_score * 0.35
  + retail_platform_score * 0.25
  + repeated_mentions_score * 0.20
  + high_heat_penalty * 0.20
```

### 14.2 机会分

建议公式：

```text
opportunity_score =
  heat_score * 0.25
  + credibility_score * 0.25
  + evidence_score * 0.25
  + mapping_confidence * 0.20
  - risk_score * 0.15
```

说明：

- 分数用于排序，不代表收益概率。
- 弱证据映射即使热度高，也不应直接进入高分候选。
- 高拥挤度需要提高 `risk_score`，不一定提高 `opportunity_score`。

## 15. 安全与风控

### 15.1 禁止词检查

所有 agent 输出、日报摘要和机会 reason 都需要经过 sanitizer。

禁止词：

- 必涨
- 稳赚
- 确定买入
- 强烈推荐买入
- 无风险
- 一定上涨

替代表述：

- 待验证
- 候选
- 观察
- 风险观察
- 等待买点雷达确认

### 15.2 权限控制

| 动作 | 默认权限 |
|---|---|
| 读取消息 | 允许 |
| 创建证据 | 允许 |
| 创建候选草稿 | 允许 |
| 标记 reviewed | 可由 Risk Review Agent 规则化执行 |
| 加入核心关注 | 用户确认 |
| 创建交易计划草稿 | 用户触发或明确授权 |
| 自动交易 | 禁止 |
| 删除用户记录 | 禁止 |

## 16. 测试计划

### 16.1 后端单元测试

新增测试：

- 证据清洗能保存 `message_evidence`。
- 低质量 X 文本不会生成 active evidence。
- 同一消息重复运行 agent 不重复生成证据。
- 候选机会能关联多条证据。
- 弱映射候选进入 `needs_review`。
- 禁止词被替换或拒绝。
- agent run 成功、失败和 skipped 状态可记录。

### 16.2 API 测试

新增测试：

- `GET /api/messages/evidence`。
- `GET /api/messages/opportunities/{id}/evidence`。
- `POST /api/messages/opportunities/{id}/review`。
- `POST /api/message-agents/run` dry-run。

### 16.3 前端测试

新增 Playwright：

- 消息中心能展示 agent 候选。
- 候选能展开证据抽屉。
- 用户能驳回候选。
- 用户能从候选加入核心关注。
- Agent 失败时页面有错误状态。

### 16.4 评测集

建立 `backend/tests/fixtures/message_agent_cases/`：

- 正常产业线索。
- 单一来源弱映射。
- 高热度但 spam。
- 多来源共振。
- 反证/风险消息。
- 无股票映射。
- 中英文混合消息。

评测指标：

- JSON 解析成功率。
- 证据引用准确率。
- 禁止词命中率。
- 弱证据降级率。
- 人工采纳率。
- 人工驳回率。

## 17. 分阶段实施

### 阶段 1：证据层与无 LLM 闭环

目标：

- 新增 `message_evidence`、`message_opportunity_evidence`、`message_agent_run`。
- 用现有规则生成证据记录。
- 机会关联证据。
- 前端可展开查看证据。

验收：

- 导入 X mock payload 后，可以从候选追溯到原始消息和证据片段。
- 不改变现有消息中心主流程。

### 阶段 2：Evidence Cleaner Agent

目标：

- 接入 LLM 做结构化证据抽取。
- 保存 agent run。
- 失败回退规则版。

验收：

- LLM 输出严格 JSON。
- 解析失败不会中断消息中心。
- 低质量消息被降权或 ignored。

### 阶段 3：Entity Mapping Agent

目标：

- 增强海外线索到 A 股候选映射。
- 输出映射路径、触发词、置信度和 `needs_review`。

验收：

- 弱映射候选不会直接进入高优先级。
- 映射路径能在前端展示。

### 阶段 4：Opportunity Scoring + Risk Review Agent

目标：

- 引入候选草稿状态。
- 风险审查输出 `review_status` 和 `risk_flags`。
- 人工可以采纳或驳回。

验收：

- agent 生成的候选不会覆盖人工复核结果。
- 用户驳回后的候选不会被同一次聚合重新激活。

### 阶段 5：Report Agent 与日报升级

目标：

- 每日结论改为基于证据层和 reviewed candidates 生成。
- 与产业链日报合流。

验收：

- 日报中的候选都能展开证据。
- 报告明确区分强证据、中证据、弱证据和风险观察。

## 18. 迁移与回滚

### 18.1 迁移

新增表为增量迁移，对现有数据低风险。

建议步骤：

1. 备份数据库。
2. 执行新增表迁移。
3. 对近 7 日 `message_source_item` 回填规则证据。
4. 对现有 active `message_opportunity` 建立基础证据关联。
5. 前端先只读展示证据。

### 18.2 回滚

如 agent 化流程异常：

- 停用 scheduler 中的 agent job。
- 前端隐藏 agent 证据和复核入口。
- 保留原有 `message_topic` / `message_opportunity` 查询。
- 新增表不影响旧流程，可延后清理。

## 19. 现有代码需要调整的重点

### 19.1 移除读请求副作用

`get_daily_messages(... ensure_seed=false)` 不应在读取时 demote legacy seed rows。建议改为：

- 写一次迁移脚本清理 demo 数据。
- 或添加明确的管理端 cleanup endpoint。
- 日常 read API 只读。

### 19.2 避免聚合覆盖人工结论

`_upsert_aggregated_opportunity` 应避免直接覆盖已复核/人工编辑机会。建议：

- 引入 `review_status`。
- 仅覆盖 `draft` 或 agent 生成且未复核的机会。
- 人工复核后的 reason、risks 和 action 不自动覆盖。

### 19.3 统一证据接口

`source_platforms` 和 `source_links` 只作为摘要字段，详细证据从 evidence API 获取。

### 19.4 消息中心与产业链日报合流

`industry_report_candidate.evidence_json` 应能引用 `message_evidence` 或 `message_relation_evidence`，而不是只保存路径摘要。

## 20. 待确认决策点

### D1：第一版 agent 的模型供应商

建议默认：

- DeepSeek，用于成本较低的中文金融研究场景。
- 保留现有 `llm_client.py` 抽象，兼容 OpenAI / Qwen / Ollama。

需要确认：

- 第一版是否以 DeepSeek 为默认？
- 是否需要支持本地 Ollama 离线模式作为开发 fallback？

### D2：候选状态字段如何演进

建议：

- 保留现有 `status`。
- 新增 `review_status`。
- 等 agent 流程稳定后再合并。

需要确认：

- 是否接受短期内 `status + review_status` 双字段？

### D3：是否第一期就做人工复核 UI

建议：

- 第一阶段至少做证据展开。
- 采纳/驳回可以放到阶段 4。

需要确认：

- 你希望第一期只做“可追溯展示”，还是同步加入“采纳/驳回”操作？

### D4：采集平台优先级

建议：

- 第一版继续 X。
- 第二步补财经新闻/公告导入，用于提高事实可信度。
- 雪球和淘股吧后置。

需要确认：

- 下一步数据源优先级是 X 增强，还是先接财经新闻/公告？

### D5：agent 调度方式

建议：

- 先手动触发和后台任务兼容。
- 稳定后接 scheduler 定时运行。

需要确认：

- 第一版是否需要每日自动调度，还是先在消息中心手动触发？

### D6：是否新增独立 agent 页面

建议：

- 不新增独立页面。
- 先放在消息中心内，作为“证据审阅”和“Agent 运行记录”两个区域。

需要确认：

- 是否接受先集成在消息中心，而不是单独做 Agent 控制台？

## 21. 推荐 MVP 范围

如果按最小可交付闭环推进，建议第一版只做：

```text
新增证据表
-> 规则版 Evidence Cleaner
-> 候选关联证据
-> 消息中心证据展开
-> agent run 日志
-> 禁止词与弱证据降级规则
```

暂不做：

- 全量 LLM agent pipeline。
- 多平台采集。
- 自动调度。
- 交易计划草稿。
- 独立 Agent 控制台。

这样可以先解决最关键的“证据不可追溯”问题，再逐步把 LLM agent 接进来。

