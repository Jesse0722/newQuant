# 产业链 GraphRAG 日报任务拆解

> 日期：2026-05-28
> 状态：待执行
> 关联方案：[产业链 GraphRAG 日报技术方案](./2026-05-28-industry-graphrag-report-technical-design.md)
> 执行原则：后续会话按阶段接力实施。每个阶段尽量形成可运行、可测试、可回滚的小闭环。

## 0. 总体顺序

推荐执行顺序：

```text
阶段 1：PostgreSQL 主库迁移
阶段 2：图谱基础模型与种子导入
阶段 3：DeepSeek 实体/关系抽取
阶段 4：产业链路径与候选评分
阶段 5：每日产业链报告生成
阶段 6：前端消息中心展示
阶段 7：调度、测试与部署文档
```

不要先做开放式 GraphRAG 问答。第一版只围绕“每日产业链机会报告”交付。

## 阶段 1：PostgreSQL 主库迁移

目标：把现有 SQLite 主库整体迁移到 PostgreSQL，包括 K 线、观察池、消息中心、AI 分析、交易计划、监控和同步日志。

### Task 1.1 增加 PostgreSQL 依赖与配置

范围：

- 更新 `backend/requirements.txt`。
- 增加 `psycopg[binary]` 或 `psycopg2-binary`。
- 更新 `backend/.env.example`。
- 更新 `README.md` 数据库配置说明。

建议：

```env
DATABASE_URL=postgresql+psycopg://newquant:newquant@localhost:5432/newquant
```

验收：

- 后端可以用 PostgreSQL `DATABASE_URL` 启动。
- 仍兼容 SQLite URL，方便本地兜底。

### Task 1.2 增加本地 PostgreSQL docker-compose

范围：

- 更新开发环境 compose，或新增 `docker-compose.dev.yml`。
- 添加 PostgreSQL 服务、数据卷和健康检查。
- 不影响现有生产 compose。

验收：

- `docker compose` 可以启动 PostgreSQL。
- 后端连接本地 PostgreSQL 成功。

### Task 1.3 引入 Alembic 迁移管理

范围：

- 初始化 Alembic 配置。
- 将当前 SQLAlchemy models 作为初始 schema。
- 保留现有 `scripts/init_db.py` 的兼容能力，但长期以 Alembic 为准。

验收：

- 空 PostgreSQL 数据库执行迁移后生成全部现有表。
- 测试库可以通过迁移初始化。

### Task 1.4 编写 SQLite -> PostgreSQL 数据迁移脚本

范围：

- 新增脚本，例如 `backend/scripts/migrate_sqlite_to_postgres.py`。
- 从旧 SQLite 读取数据，写入 PostgreSQL。
- 按外键和业务依赖排序迁移。
- 支持 dry-run、批量提交和 count 校验。

核心表范围：

```text
stock_basic
daily_quote
watch_pool
watch_stock
message_source_item
message_topic
message_opportunity
message_keyword_seed
stock_ai_analysis
trade 相关表
monitor / alert / sync_log / sector / intraday_scan 相关表
```

验收：

- 每张核心表输出迁移前后 count。
- `daily_quote`、`stock_basic`、`watch_stock`、`message_source_item` 数据量一致。
- 迁移脚本重复执行不会破坏目标库，至少支持清空后重跑或 upsert 模式之一。

### Task 1.5 PostgreSQL 核心索引优化

范围：

- 为 K 线、消息、机会、AI 分析表补充 PostgreSQL 适配索引。

建议索引：

```text
daily_quote(ts_code, trade_date desc)
daily_quote(trade_date)
message_source_item(trade_date, theme)
message_source_item(trade_date, ts_code)
message_opportunity(trade_date, opportunity_score desc)
stock_ai_analysis(ts_code, created_at desc)
```

验收：

- 股票详情页 K 线查询正常。
- 消息中心日报查询正常。
- 后端测试通过。

## 阶段 2：图谱基础模型与种子导入

目标：在 PostgreSQL 中新增轻量图谱表，先导入产业链种子和股票业务映射。

### Task 2.1 新增图谱 ORM 模型

范围：

- 新增或扩展 `backend/app/models/message.py`。
- 增加：
  - `MessageEntity`
  - `MessageRelation`
  - `MessageRelationEvidence`
  - `IndustryDailyReport`
  - `IndustryReportCandidate`

验收：

- Alembic 迁移生成新增表。
- 新表可以在 PostgreSQL 初始化。

### Task 2.2 新增图谱 Pydantic schemas

范围：

- 更新或新增 `backend/app/schemas/message_graph.py`。
- 包含实体、关系、证据、路径、日报、候选标的输出结构。

验收：

- schema 可以被 FastAPI response_model 使用。
- JSONB 字段对前端输出稳定。

### Task 2.3 新增产业链种子 CSV

范围：

- 新增 `backend/app/seeds/industry_graph_seed.csv`。
- 新增 `backend/app/seeds/stock_business_seed.csv`。

第一批主题：

```text
AI算力
NVIDIA产业链
HBM与存储
光模块
铜连接
PCB
液冷
AI电力
AI服务器
机器人
```

验收：

- 每条种子关系有 `confidence` 和 `note`。
- 股票映射只表示业务/产业链映射，不写“买入”“必涨”等交易判断。

### Task 2.4 实现种子导入服务

范围：

- 新增 `backend/app/services/message_graph_service.py`。
- 实现实体 upsert、关系 upsert、证据写入。
- 实现 CSV 种子导入。

验收：

- 可以重复导入，不产生重复实体和重复关系。
- 种子关系自动生成 seed evidence。
- 导入结果返回创建/更新/跳过数量。

### Task 2.5 新增图谱调试 API

范围：

- 新增 `backend/app/routers/message_graph.py`。
- API：

```text
POST /api/message-graph/import-seeds
GET  /api/message-graph/entities
GET  /api/message-graph/relations
GET  /api/message-graph/paths
```

验收：

- 可按名称查询实体。
- 可查询实体 1-3 跳路径。
- 路径返回节点、关系和证据摘要。

## 阶段 3：DeepSeek 实体/关系抽取

目标：对新增消息进行结构化抽取，把文本线索转成可审计的实体、关系和证据。

### Task 3.1 抽取 Prompt 与 JSON 解析

范围：

- 新增 `backend/app/services/message_extraction_service.py`。
- 使用现有 `llm_client.call_llm_model` 或 `call_llm`。
- 定义抽取 Prompt。
- 解析 DeepSeek JSON 输出并做容错。

硬性规则：

```text
只能基于输入文本抽取。
不能把推测写成事实。
每条关系必须带 evidence_text。
共现但无明确关系时使用 mentions。
证据不足时 confidence 不得高于 50。
禁止输出交易建议。
```

验收：

- 给定一条测试消息，能输出 entities 和 relations。
- JSON 解析失败时记录错误，不影响主流程。

### Task 3.2 抽取结果入库

范围：

- 将抽取出的实体、关系、证据写入图谱表。
- 关联 `message_source_item.id`。
- 对低置信关系设置较低 `confidence` 和 `strength`。

验收：

- 同一条消息重复抽取不会重复创建实体。
- 关系证据可以回溯到原始消息。
- 只有共现的内容不会被写成强关系。

### Task 3.3 新增批量抽取任务

范围：

- 支持按 `trade_date` 抽取 `message_source_item`。
- 支持只处理 `status=new/processed` 但未抽取的消息。
- 记录抽取状态，避免重复调用 DeepSeek。

可选字段：

- 在 `message_source_item.raw_payload` 或新增字段中记录 extraction status。
- 或新增 `message_extraction_log` 表。

验收：

- 可以按日期批量抽取。
- 支持限制每次处理数量，控制成本。
- DeepSeek 失败时单条失败不影响整体任务。

### Task 3.4 单元测试

范围：

- 测试 JSON 解析。
- 测试实体归一化。
- 测试关系入库。
- 测试低置信共现处理。

验收：

- 后端相关测试通过。

## 阶段 4：产业链路径与候选评分

目标：从主题/技术/事件出发，找出产业链路径和 A 股候选标的，并生成可解释评分。

### Task 4.1 实现图路径查询

范围：

- 在 `message_graph_service.py` 中实现 1-3 跳路径查询。
- 支持按实体名、实体类型、关系类型过滤。
- 支持路径去重。

验收：

- 查询 `Rubin` 能返回到 `NVLink`、高速互联、铜连接、PCB 等路径。
- 查询产业链节点能返回映射股票。

### Task 4.2 实现候选标的生成

范围：

- 新增 `backend/app/services/industry_report_service.py`。
- 从高热主题、新增关系、种子主题出发生成候选。
- 关联 `stock_basic`、`daily_quote`、`message_opportunity`、`watch_stock`。

候选应包含：

```text
ts_code
stock_name
theme
path_json
evidence_json
path_score
evidence_score
heat_score
crowding_score
risk_score
final_score
grade
reason
risks
```

验收：

- 可以为指定交易日生成候选标的列表。
- 每个候选至少有一条路径。
- 无证据或弱路径候选不能被评为 strong。

### Task 4.3 实现评分规则

范围：

- 实现规则化评分，不依赖 LLM 主观打分。

建议：

```text
final_score =
  path_score * 0.30
+ evidence_score * 0.25
+ heat_score * 0.20
+ resonance_score * 0.15
- crowding_penalty * 0.10
- risk_penalty * 0.10
```

验收：

- 评分结果可解释。
- 只有社媒来源的候选自动降级。
- 有官方反证的候选进入 `risk_watch` 或降级。

### Task 4.4 候选写入与查询

范围：

- 写入 `industry_report_candidate`。
- 支持按日期查询。
- 支持按综合分、等级、主题过滤。

验收：

- 重复生成同一天候选时不会无限新增重复记录。
- 前端可以稳定读取候选列表。

## 阶段 5：每日产业链报告生成

目标：基于候选标的、路径和证据，调用 DeepSeek 生成结构化日报。

### Task 5.1 报告上下文构造

范围：

- 构造 `IndustryReportSnapshot`。
- 包含：

```text
trade_date
top_themes
core_catalysts
graph_paths
candidates
evidence
risk_flags
market_context
watch_pool_context
```

验收：

- Snapshot 可以序列化成 JSON。
- 不包含过长原文，只保留证据片段和链接。

### Task 5.2 DeepSeek 日报 Prompt

范围：

- 新增日报 Prompt。
- 要求只基于输入 JSON。
- 输出严格 JSON。
- 包含今日主线、核心催化、产业链路径、候选标的、风险、下一步动作。

输出结构建议：

```json
{
  "headline": "",
  "summary": "",
  "core_catalysts": [],
  "industry_paths": [],
  "candidate_summary": [],
  "risk_flags": [],
  "next_actions": []
}
```

验收：

- DeepSeek 输出可解析。
- 解析失败时保存 raw_response 和错误。
- 报告不得包含确定性收益承诺。

### Task 5.3 报告生成 API

范围：

- 新增 `backend/app/routers/industry_reports.py`。
- API：

```text
GET  /api/industry-reports/daily
POST /api/industry-reports/generate
GET  /api/industry-reports/candidates
POST /api/industry-reports/candidates/{id}/add-to-pool
```

验收：

- 可以手动生成指定日期报告。
- 可以读取最新报告。
- 可以把候选加入观察池。

### Task 5.4 报告归档与幂等

范围：

- 同一天报告唯一。
- 重新生成时更新旧报告，或生成新版本但默认读取最新版。
- 保存模型 provider、model、prompt_version、raw_response。

验收：

- 多次生成同一天报告不会造成前端重复展示。
- 失败报告有错误信息可查。

## 阶段 6：前端消息中心展示

目标：在现有消息中心增加“产业链日报”能力。

### Task 6.1 新增前端 API

范围：

- 新增 `frontend/src/api/industryReports.ts`。
- 定义 TypeScript 类型。

验收：

- 前端可以请求日报、候选列表、手动生成报告、加入观察池。

### Task 6.2 消息中心新增日报区域或 Tab

范围：

- 更新 `frontend/src/pages/Messages/MessageCenterPage.tsx`。
- 新增产业链日报视图。

页面模块：

```text
今日主线
核心催化
产业链路径
候选标的
风险提示
生成/刷新按钮
```

验收：

- 无报告时展示空状态和生成按钮。
- 有报告时展示结构化内容。
- 加载、失败、刷新状态完整。

### Task 6.3 候选标的表格

范围：

- 展示股票、主题、等级、综合分、路径强度、证据强度、热度、拥挤度、风险、建议动作。
- 支持跳转股票详情。
- 支持加入观察池。

验收：

- 表格在桌面和窄屏下不发生文本重叠。
- 加入观察池成功后有明确状态反馈。

### Task 6.4 证据与路径展示

范围：

- 候选详情或展开行展示产业链路径。
- 展示证据来源、渠道、链接、置信度。

验收：

- 用户能看懂“为什么这只股票被选出”。
- 每个候选的关键判断都有证据入口。

## 阶段 7：调度、测试与部署文档

目标：让日报可以稳定运行，并确保迁移后核心工作流不回退。

### Task 7.1 新增调度任务

范围：

- 更新 `backend/app/tasks/scheduler.py` 或 `scheduled_jobs_service.py`。
- 新增：

```text
08:30 盘前产业链日报
15:30 盘后产业链日报更新
```

验收：

- 可通过配置开关启用/关闭。
- 调度失败不会影响现有 K 线同步和盘中扫描。

### Task 7.2 后端测试

范围：

- PostgreSQL 配置测试。
- 种子导入测试。
- 图路径查询测试。
- 关系抽取解析测试。
- 候选评分测试。
- 报告 API 测试。

验收：

- `pytest -q` 通过。
- DeepSeek 相关测试默认 mock，不依赖真实 API。

### Task 7.3 前端测试

范围：

- 消息中心产业链日报展示。
- 无报告空状态。
- 候选表格筛选/展示。
- 加入观察池按钮。

验收：

- Playwright 关键路径测试通过。

### Task 7.4 部署文档更新

范围：

- 更新 `README.md`。
- 更新 `docs/aliyun-auto-deploy.md` 或相关部署说明。
- 补充 PostgreSQL 备份和恢复建议。

验收：

- 新环境可按文档启动 PostgreSQL + backend + frontend。
- 旧 SQLite 数据迁移步骤清晰。

## 风险与注意事项

- 现有工作区有未提交改动，执行任务前应先确认当前 diff，避免覆盖用户改动。
- 数据库迁移是高风险阶段，必须先备份 SQLite 文件。
- DeepSeek 抽取要限量、可重试、可跳过，避免成本和失败扩散。
- 雪球等社区数据源要注意合规和稳定性，V1 可先支持手工导入或半自动导入。
- 不要把“社媒热度高”直接等同于“强机会”。
- 不要让 LLM 直接决定最终分数，评分应以规则和证据为主。

## 建议提交边界

推荐后续实现时按以下提交或 PR 边界拆分：

1. PostgreSQL 依赖、配置、迁移脚本。
2. Alembic 与初始 schema。
3. 图谱模型、种子 CSV、导入服务。
4. DeepSeek 抽取服务。
5. 路径查询与候选评分。
6. 日报生成 API。
7. 前端产业链日报页面。
8. 调度、测试、部署文档。

每个边界都应尽量保持后端测试可运行，避免把数据库迁移、图谱、LLM 和前端一次性混在一个大改动里。
