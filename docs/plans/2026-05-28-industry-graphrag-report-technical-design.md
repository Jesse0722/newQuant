# 产业链 GraphRAG 日报技术方案

> 日期：2026-05-28
> 状态：设计稿
> 目标：把消息中心从“题材与个股机会聚合”升级为“每日产业链机会报告”，用 PostgreSQL、DeepSeek 和轻量图谱能力支撑可追溯的产业链路径分析。

## 1. 背景

当前系统已经形成“观察池 -> 买点雷达 -> 买点提醒 -> 交易计划 -> 复盘”的主工作流，并已落地消息中心 MVP：

- `message_source_item` 保存原始消息、渠道、链接、热度、可信度和去重键。
- `message_topic` 按日期和题材聚合热度、可信度、拥挤度和生命周期。
- `message_opportunity` 按题材和股票生成候选机会。
- X recent search 已接入，并有关键词池、账号池、海外产业词到 A 股候选映射。
- 股票详情 AI 分析已接入 DeepSeek，并强调证据约束和风险边界。

MVP 阶段使用 SQLite 是合理选择，但下一阶段要支撑多源采集、关系图谱、日报归档、候选标的评分和后续向量检索，SQLite 已经不适合作为长期主库。

本方案建议将主数据库整体迁移到 PostgreSQL，并在现有消息中心旁边新增“产业链 GraphRAG Lite”能力，先实现固定产出的每日产业链机会报告，而不是先做开放式问答或大而全图数据库。

## 2. 目标

- 将所有业务表从 SQLite 主库迁移到 PostgreSQL，包括 K 线、股票基础信息、观察池、消息中心、AI 分析、交易计划、监控和同步日志。
- 保留现有消息中心的数据承载与页面入口，新增产业链图谱、关系证据和日报归档。
- 使用 DeepSeek 对新增消息进行实体抽取、关系抽取和日报生成。
- 先做“每日产业链机会报告”，聚焦核心问题：今天哪些产业催化值得关注，它们通过什么路径影响 A 股标的。
- 把候选标的输出到现有观察池/股票详情/AI 分析工作流，交易判断仍交给用户和买点雷达。
- 所有结论必须能够回溯到来源、关系路径和证据强度。

## 3. 非目标

- V1 不做自动交易。
- V1 不做泛化聊天式 GraphRAG 问答。
- V1 不引入 Neo4j、NebulaGraph、TigerGraph 等独立图数据库。
- V1 不强依赖全网爬虫，不以不稳定采集能力作为核心交付。
- V1 不把“利好/利空”作为事实边直接入库；它只能作为基于路径和证据的推理结果。

## 4. 总体架构

```text
多源采集
  -> message_source_item 原始消息与证据
  -> DeepSeek 实体/关系抽取
  -> message_entity / message_relation / message_relation_evidence
  -> PostgreSQL 图查询与证据聚合
  -> industry_daily_report / industry_report_candidate
  -> 消息中心产业链日报
  -> 股票详情 Graph Context
  -> 观察池 / 买点雷达 / 交易计划
```

V1 使用 PostgreSQL 表结构表达图谱：

- 节点表保存公司、股票、产品、技术、题材、产业链环节、事件、来源等实体。
- 关系表保存实体之间的可审计关系。
- 证据表保存关系来自哪条消息、哪段文本、置信度和抽取方式。
- 路径查询先用 SQL、递归 CTE 和应用层 BFS/DFS 实现。

## 5. 数据源策略

X 继续保留，但不再作为唯一或最佳舆情源。推荐按可信度分层：

| 层级 | 来源 | 角色 | 事实可信度 |
|---|---|---|---|
| 一级 | 公司公告、交易所公告、互动易、财报、业绩说明会 | 事实校验、反证、业务确认 | 高 |
| 二级 | 财联社、东方财富、证券时报、上海证券报、同花顺资讯 | 财经事件、产业催化、市场解释 | 中高 |
| 三级 | 雪球、淘股吧、微博、X | 情绪、传播、A 股映射、海外线索 | 中低 |
| 四级 | 小红书、短视频评论、泛社区热度 | 大众扩散与拥挤度 | 低 |

V1 推荐优先级：

1. 继续保留 X，用于海外产业催化，如 Nvidia、Rubin、HBM、AI capex、光模块、铜连接。
2. 新增雪球导入/采集能力，用于 A 股映射和投资者讨论，但不作为事实源。
3. 新增财经新闻/公告导入能力，用于证据校验和反证。
4. 淘股吧后续用于短线情绪和拥挤度，不作为第一批必要交付。

## 6. PostgreSQL 迁移策略

迁移原则：一次性把主业务库整体切到 PostgreSQL，不做“舆情在 PostgreSQL、K 线在 SQLite”的双主库。

迁移范围包括：

- 股票与行情：`stock_basic`、`daily_quote`、板块/行业、盘中扫描相关表。
- 观察池：`watch_pool`、`watch_stock`。
- 消息中心：`message_source_item`、`message_topic`、`message_opportunity`、`message_keyword_seed`。
- AI 分析：`stock_ai_analysis`。
- 交易计划与复盘：交易计划、交易明细等交易相关表。
- 监控、提醒、同步日志等运行表。

推荐技术：

```text
PostgreSQL 15+
SQLAlchemy
psycopg 3
Alembic
JSONB
必要时启用 pgvector
必要时启用 PostgreSQL 全文检索
```

数据库 URL 示例：

```env
DATABASE_URL=postgresql+psycopg://newquant:newquant@localhost:5432/newquant
```

K 线相关索引建议：

```text
daily_quote(ts_code, trade_date)
daily_quote(trade_date)
daily_quote(ts_code, trade_date desc)
```

## 7. 新增核心模型

### 7.1 message_entity

实体节点表。

| 字段 | 说明 |
|---|---|
| id | UUID |
| entity_type | stock / company / theme / product / technology / industry_chain / event / source / person |
| name | 展示名称 |
| normalized_name | 归一化名称，用于去重 |
| ts_code | 股票代码，可空 |
| aliases | JSONB，别名列表 |
| metadata | JSONB，扩展信息 |
| confidence | 0-100 |
| status | active / merged / ignored |
| created_at / updated_at | 时间 |

建议唯一约束：

```text
entity_type + normalized_name
```

股票实体可以通过 `ts_code` 与 `stock_basic` 关联。

### 7.2 message_relation

实体关系表。

| 字段 | 说明 |
|---|---|
| id | UUID |
| source_entity_id | 起点实体 |
| relation_type | uses / supplies / depends_on / maps_to / mentions / triggers / increases_demand_for / competes_with / substitutes / verifies / refutes |
| target_entity_id | 终点实体 |
| confidence | 0-100 |
| strength | 0-100 |
| polarity | positive / neutral / negative / mixed |
| valid_from / valid_to | 关系有效时间，可空 |
| evidence_count | 证据数量 |
| source_type | seed / rule / llm / manual |
| status | active / disputed / ignored |
| created_at / updated_at | 时间 |

重要约束：

- “利好/利空”不作为事实关系类型。
- `benefits_from` 这类主观关系 V1 尽量不用；如必须保留，必须低置信并强制证据说明。
- 产业链映射优先使用更客观关系，例如 `uses`、`depends_on`、`increases_demand_for`、`maps_to`。

### 7.3 message_relation_evidence

关系证据表。

| 字段 | 说明 |
|---|---|
| id | UUID |
| relation_id | 关系 ID |
| source_item_id | 原始消息 ID，可空 |
| evidence_text | 证据片段 |
| evidence_url | 证据链接 |
| source_channel | 来源渠道 |
| extraction_method | seed / rule / llm / manual |
| confidence | 0-100 |
| created_at | 时间 |

每条用于推理的关系都应该至少有一条证据；种子图谱关系也要写入 seed evidence，说明其来源和维护原因。

### 7.4 industry_daily_report

每日产业链报告主表。

| 字段 | 说明 |
|---|---|
| id | UUID |
| trade_date | YYYYMMDD |
| title | 报告标题 |
| headline | 今日主线 |
| summary | 总结 |
| report_json | JSONB，结构化报告 |
| model_provider | deepseek |
| model_name | 模型名称 |
| prompt_version | Prompt 版本 |
| status | success / failed / draft |
| error_message | 失败原因 |
| created_at / updated_at | 时间 |

唯一约束：

```text
trade_date
```

### 7.5 industry_report_candidate

日报候选标的表。

| 字段 | 说明 |
|---|---|
| id | UUID |
| report_id | 报告 ID |
| trade_date | YYYYMMDD |
| ts_code | 股票代码 |
| stock_name | 股票名称 |
| theme | 关联主题 |
| path_json | JSONB，产业链路径 |
| evidence_json | JSONB，证据列表 |
| path_score | 路径强度 |
| evidence_score | 证据强度 |
| heat_score | 热度 |
| crowding_score | 拥挤度 |
| risk_score | 风险 |
| final_score | 综合评分 |
| grade | strong / medium / weak / risk_watch |
| reason | 候选理由 |
| risks | JSONB |
| created_at | 时间 |

## 8. 种子图谱

现有 `message_x_stock_mappings.csv` 是“触发词 -> A 股候选”的扁平映射。GraphRAG V1 应新增两类种子：

### 8.1 industry_graph_seed.csv

字段：

```text
source,relation,target,theme,confidence,note
```

示例：

```text
Rubin,uses,NVLink,NVIDIA产业链,80,海外AI服务器平台核心互联线索
NVLink,increases_demand_for,高速互联,NVIDIA产业链,75,高速互联需求传导
高速互联,maps_to,铜连接,铜连接,70,产业链环节映射
AI服务器,maps_to,PCB,PCB,70,AI服务器硬件升级映射
```

### 8.2 stock_business_seed.csv

字段：

```text
ts_code,stock_name,business_node,relation,confidence,evidence_note
```

示例：

```text
601138.SH,工业富联,AI服务器,maps_to,80,服务器制造与AI服务器链条映射
300308.SZ,中际旭创,光模块,maps_to,85,光模块龙头映射
```

这些种子不是交易建议，只表示产业链映射。候选标的最终评级仍要结合当日证据、热度、拥挤度、K 线和观察池上下文。

## 9. DeepSeek 使用方式

DeepSeek 用于三类任务：

1. 实体抽取：从原始消息中抽取公司、股票、产品、技术、主题、事件。
2. 关系抽取：抽取采用、供应、扩产、涨价、替代、竞争、需求提升、反证等关系。
3. 日报生成：基于图谱路径、候选标的和证据生成报告。

不建议交给 LLM 的任务：

- 去重主逻辑。
- 评分主逻辑。
- 数据库查询和路径搜索。
- 交易建议。

抽取 Prompt 必须要求 JSON 输出，并包含硬性规则：

```text
只能基于输入文本抽取。
不能把推测写成事实。
每条关系必须带 evidence_text。
如果只是共现，relation_type 使用 mentions。
如果证据不足，confidence 不得高于 50。
不要生成买入、卖出或收益判断。
```

日报 Prompt 必须基于后端准备好的结构化上下文：

```text
主题列表
产业链路径
候选标的
证据来源
反证与风险
K线/观察池/消息热度摘要
```

## 10. GraphRAG 流程

每日任务流程：

```text
1. 采集或导入多源消息
2. 入库 message_source_item 并去重
3. 对新增消息执行实体/关系抽取
4. 归并实体与关系，写入证据
5. 从高热主题和新催化出发做 1-3 跳图谱扩展
6. 关联 A 股股票实体和 stock_basic
7. 读取近行情、观察池状态、已有 message_opportunity
8. 计算候选标的评分
9. 调用 DeepSeek 生成结构化日报
10. 写入 industry_daily_report / industry_report_candidate
11. 前端展示并支持加入观察池
```

用户打开日报时，不重新调用 LLM；默认读取已生成报告。需要刷新时再手动触发。

## 11. 候选评分

V1 评分建议：

```text
final_score =
  path_score * 0.30
+ evidence_score * 0.25
+ heat_score * 0.20
+ resonance_score * 0.15
- crowding_penalty * 0.10
- risk_penalty * 0.10
```

分层：

| 等级 | 含义 |
|---|---|
| strong | 强证据候选，有明确业务映射，且有公告/权威媒体/多源证据支撑 |
| medium | 中证据候选，产业链路径明确，有财经媒体或高质量社区讨论支撑 |
| weak | 弱证据候选，主要来自社媒共现或题材映射 |
| risk_watch | 热度高但拥挤，或反证/风险明显 |

风险因子：

- 只有社媒来源，无公告或权威媒体验证。
- 产业链路径超过 2 跳。
- 近期涨幅过大或拥挤度过高。
- 有官方反证，如“未形成收入”“未签署合同”“未量产”。
- 与公司主营映射弱，收入占比未知。

## 12. API 设计

新增后端路由建议：

```text
GET  /api/industry-reports/daily?trade_date=YYYYMMDD
POST /api/industry-reports/generate
GET  /api/industry-reports/candidates?trade_date=YYYYMMDD
GET  /api/industry-reports/candidates/{id}
POST /api/industry-reports/candidates/{id}/add-to-pool
GET  /api/message-graph/entities
GET  /api/message-graph/relations
GET  /api/message-graph/paths?entity=Rubin&max_depth=3
POST /api/message-graph/extract
POST /api/message-graph/import-seeds
```

V1 前端主要使用：

- `GET /api/industry-reports/daily`
- `POST /api/industry-reports/generate`
- `POST /api/industry-reports/candidates/{id}/add-to-pool`

图谱查询 API 可以先作为调试和后续页面能力。

## 13. 前端设计

建议在消息中心新增“产业链日报”区域或 Tab：

- 今日主线。
- 核心催化。
- 产业链路径。
- 候选标的表格。
- 证据强度与风险标签。
- 原始证据链接。
- 一键加入观察池。

候选标的字段：

```text
股票
关联主题
等级
综合分
路径强度
证据强度
热度
拥挤度
风险
建议动作
```

股票详情页后续新增 Graph Context：

- 当前股票关联的主题。
- 产业链路径。
- 近期证据。
- 是否仅社媒映射。
- 是否有公告/权威媒体验证。

## 14. 调度策略

短期继续复用现有调度器结构，新增日报任务：

```text
盘前：生成昨日收盘后到今早的产业链日报
盘后：更新当日产业链日报和候选标的
手动：消息中心按钮触发刷新
```

建议时间：

- 08:30 盘前日报。
- 15:30 盘后更新。
- 手动刷新用于调试和突发事件。

## 15. 验收标准

数据库：

- PostgreSQL 可以完整初始化所有现有表和新增表。
- SQLite 旧数据可以迁移到 PostgreSQL。
- 每张核心表迁移前后 count 校验通过。
- 股票详情、观察池、消息中心、策略筛选等核心页面仍能正常读写。

图谱：

- 可以导入产业链种子图谱和股票业务映射。
- 可以从 `message_source_item` 抽取实体、关系和证据。
- 关系必须能回溯到来源消息或 seed evidence。
- 给定核心实体可以查询 1-3 跳路径。

日报：

- 可以生成指定交易日的产业链日报。
- 日报包含今日主线、核心催化、产业链路径、候选标的、证据、风险。
- 候选标的有强/中/弱/风险观察分层。
- 每个候选标的能看到路径和证据。
- 候选标的可以加入观察池。

风险控制：

- 只有社媒共现的候选不能被标为 strong。
- 有官方反证的候选必须降级或进入 risk_watch。
- LLM 输出不得包含确定性收益承诺或自动交易指令。

## 16. 后续演进

当数据量、关系复杂度或查询需求明显上升后，再考虑：

- PostgreSQL + pgvector：语义检索和相似事件召回。
- OpenSearch/Elasticsearch：更强全文检索。
- Neo4j/NebulaGraph：复杂路径查询和图分析。
- Agent 工作流：自动发现异常题材、补充检索、生成专题研究。
- 多模态采集：图片 OCR、视频 ASR、长线程还原。

当前优先级仍是：先让日报稳定、有证据、有路径、有标的、有行动入口。
