# 舆情模块 Agent 化任务拆解

> 日期：2026-06-12
> 状态：待执行
> 关联方案：[舆情模块 Agent 化技术方案](./2026-06-12-message-agent-technical-design.md)
> 执行原则：先补证据链，再接 LLM agent；每个阶段形成可运行、可测试、可回滚的小闭环。

## 0. 总体顺序

推荐执行顺序：

```text
阶段 0：现有消息模块清理与基线确认
阶段 1：证据层 MVP
阶段 2：规则版 Evidence Cleaner
阶段 3：消息中心证据展开
阶段 4：候选复核状态与人工反馈
阶段 5：LLM Evidence Cleaner / Entity Mapping Agent
阶段 6：Report Agent 与调度
```

第一轮不要先做完整多 agent pipeline。优先解决“候选机会不可追溯到具体证据”的问题。

## 阶段 0：现有消息模块清理与基线确认

目标：在新增 agent 能力前，先确认现有消息中心行为稳定，避免把历史 demo 数据和读请求副作用带入新流程。

### Task 0.1 清理读请求副作用

范围：

- 检查 `backend/app/services/message_service.py` 中 `get_daily_messages(... ensure_seed=false)` 的行为。
- 移除或隔离读取接口中对 legacy seed rows 的自动 demote。
- 如仍需清理历史 demo 数据，改为一次性脚本或显式维护接口。

验收：

- `GET /api/messages/daily` 不修改数据库。
- 现有 `test_daily_messages_hides_legacy_seed_rows_in_real_mode` 根据新行为调整。
- 后端消息测试通过。

风险：

- 可能暴露历史 demo 数据。需要用脚本或显式条件处理，而不是在 read API 内处理。

### Task 0.2 明确 demo 数据策略

范围：

- 梳理 `ensure_seed_daily_messages` 和 `status=demo` 的用途。
- 文档化 demo 数据只用于空库演示，不进入真实查询。
- 确认前端默认 `ensure_seed=false`。

验收：

- README 或消息模块文档说明 demo seed 使用边界。
- 测试覆盖真实模式不返回 demo 机会。

### Task 0.3 跑基线测试

范围：

- 后端消息模块测试。
- 产业链日报测试。
- 前端消息中心 e2e 如环境可用。

建议命令：

```bash
cd backend
./venv/bin/pytest -q tests/test_messages_api.py tests/test_industry_reports_api.py
```

```bash
cd frontend
npm run lint
```

验收：

- 记录当前通过/失败情况。
- 若失败与本任务无关，记录为已知问题，不在本阶段扩大修复范围。

## 阶段 1：证据层 MVP

目标：新增统一证据表和 agent run 日志，不接 LLM，先让机会候选能关联具体原始消息和证据片段。

### Task 1.1 新增 ORM 模型

范围：

- 更新 `backend/app/models/message.py`。
- 新增：
  - `MessageEvidence`
  - `MessageOpportunityEvidence`
  - `MessageAgentRun`

建议字段以方案文档第 9 节为准。

`MessageEvidence` 必备字段：

```text
id
source_item_id
trade_date
channel
theme
ts_code
evidence_text
stance
quality_score
credibility_score
confidence
extraction_method
extractor_name
extractor_version
raw_json
status
created_at
```

`MessageOpportunityEvidence` 必备字段：

```text
id
opportunity_id
evidence_id
role
weight
created_at
```

`MessageAgentRun` 必备字段：

```text
id
agent_name
agent_version
trade_date
input_ref_type
input_ref_id
input_digest
output_json
model_provider
model_name
prompt_version
status
error_message
started_at
finished_at
duration_ms
```

验收：

- SQLite 测试库可以 `Base.metadata.create_all` 创建新表。
- PostgreSQL 初始化路径不受影响。
- 新表字段使用 JSON 兼容 SQLite 和 PostgreSQL。

### Task 1.2 新增 Pydantic Schemas

范围：

- 更新 `backend/app/schemas/message.py`，或新增 `backend/app/schemas/message_agent.py`。
- 增加：
  - `MessageEvidenceOut`
  - `MessageEvidenceCreate`
  - `MessageOpportunityEvidenceOut`
  - `MessageAgentRunOut`
  - `MessageAgentRunCreate`

验收：

- schema 可作为 FastAPI response_model。
- JSON 字段默认返回 dict/list，不返回 `None` 导致前端处理复杂化。
- 时间字段输出稳定。

### Task 1.3 新增证据服务

范围：

- 新增 `backend/app/services/message_evidence_service.py`。
- 实现：
  - 从 `MessageSourceItem` 生成规则版 evidence。
  - evidence upsert，避免重复。
  - opportunity 与 evidence 关联。
  - 查询某个 opportunity 的证据。
  - 写入 `MessageAgentRun`。

建议幂等键：

```text
source_item_id + extractor_name + extractor_version + stance + theme + ts_code
```

第一版 evidence_text：

- 优先使用 `title`。
- 没有 title 时使用 `content` 前 160 字。
- 保留原始 `url` 通过 source item 查询，不在 evidence 重复存全量链接。

验收：

- 同一 source item 重复运行不会生成重复 evidence。
- 有 theme 的 source item 至少生成一条 support/neutral evidence。
- 有 ts_code 的 source item 生成股票相关 evidence。

### Task 1.4 聚合机会时关联证据

范围：

- 更新 `aggregate_source_items` 或 `_upsert_aggregated_opportunity`。
- 在生成/更新 `MessageOpportunity` 后，为其关联来自同组 source items 的 evidence。
- 保留现有 `source_platforms` / `source_links` 摘要字段，作为兼容输出。

验收：

- 导入两条同题材同股票消息后：
  - 生成 1 个 topic。
  - 生成 1 个 opportunity。
  - 生成至少 2 条 evidence。
  - opportunity 能查到关联 evidence。
- 重复导入或重复聚合不重复关联。

### Task 1.5 新增证据 API

范围：

- 更新 `backend/app/routers/messages.py`，或新增 `backend/app/routers/message_agents.py`。
- API：

```text
GET /api/messages/evidence
GET /api/messages/opportunities/{opportunity_id}/evidence
GET /api/message-agents/runs
GET /api/message-agents/runs/{run_id}
```

过滤参数：

```text
trade_date
theme
ts_code
stance
status
source_item_id
limit
```

验收：

- 可按日期和股票查询 evidence。
- 可按 opportunity 查询证据列表。
- 空结果返回空数组，不报错。

### Task 1.6 后端测试

范围：

- 更新 `backend/tests/test_messages_api.py`，或新增 `backend/tests/test_message_evidence_api.py`。

必测用例：

- 导入 source items 后生成 evidence。
- opportunity 关联 evidence。
- 重复运行 evidence cleaner 不重复生成。
- `GET /api/messages/evidence` 支持过滤。
- `GET /api/messages/opportunities/{id}/evidence` 返回关联证据。
- agent run 成功和失败状态能记录。

验收：

```bash
cd backend
./venv/bin/pytest -q tests/test_messages_api.py tests/test_message_evidence_api.py
```

如拆分测试文件尚未创建，只运行实际存在的相关测试。

## 阶段 2：规则版 Evidence Cleaner

目标：把证据生成从聚合过程里抽出来，形成独立的规则版 agent，后续可平滑替换为 LLM agent。

### Task 2.1 实现规则版 Evidence Cleaner Agent

范围：

- 在 `message_evidence_service.py` 中实现批处理函数：

```text
run_rule_evidence_cleaner(db, trade_date, source_item_ids=None, dry_run=False)
```

能力：

- 读取 `message_source_item`。
- 跳过 `ignored` 和低质量消息。
- 生成 evidence。
- 写入 agent run。
- 支持 dry-run。

验收：

- 手动调用后能返回 processed/skipped/created counts。
- dry-run 不写入 evidence。
- 重复运行幂等。

### Task 2.2 增加手动触发 API

范围：

```text
POST /api/message-agents/run
```

第一版只支持：

```json
{
  "agent_name": "rule_evidence_cleaner",
  "trade_date": "20260612",
  "dry_run": false
}
```

验收：

- 不支持的 agent_name 返回 400。
- dry-run 返回预估结果。
- 成功运行后可在 runs API 查询。

### Task 2.3 低质量消息规则

范围：

- 复用或抽出 `x_message_service.py` 中的文本质量规则。
- 将 spam、过短文本、广告引流、过多 hashtag/cashtag 标为 ignored 或低 confidence。

验收：

- 低质量 spam fixture 不生成 active evidence。
- 边界文本不会误删正常产业消息。

## 阶段 3：消息中心证据展开

目标：前端在现有消息中心内展示候选背后的证据，不新增独立 Agent 控制台。

### Task 3.1 前端类型与 API

范围：

- 更新 `frontend/src/types/index.ts`。
- 更新 `frontend/src/api/messages.ts`。
- 增加：
  - `MessageEvidence`
  - `MessageAgentRun`
  - `getMessageEvidence`
  - `getMessageOpportunityEvidence`
  - `runMessageAgent`
  - `listMessageAgentRuns`

验收：

- TypeScript 类型通过。
- API 参数与后端一致。

### Task 3.2 个股机会表增加证据展开

范围：

- 更新 `frontend/src/pages/Messages/MessageCenterPage.tsx`。
- 在个股机会表操作列增加“证据”按钮或 expandable row。
- 打开后展示：
  - evidence_text
  - 来源平台
  - stance
  - quality_score
  - credibility_score
  - confidence
  - 原文链接

验收：

- 有证据的 opportunity 可以展开证据。
- 没证据时展示空状态。
- 不影响原有查看股票详情、加入核心关注操作。

### Task 3.3 Agent 运行记录轻量展示

范围：

- 在消息中心新增一个紧凑区域或 modal。
- 展示最近 agent runs：
  - agent_name
  - status
  - trade_date
  - duration_ms
  - error_message

验收：

- 用户能看到最近运行结果。
- 失败状态有清晰提示。

### Task 3.4 前端测试

范围：

- 更新 `frontend/tests/e2e/messages.spec.ts`。

验收：

- 消息中心仍能展示今日题材和个股机会。
- 点击证据入口能看到证据文本或空状态。
- 原有高分筛选测试通过。

## 阶段 4：候选复核状态与人工反馈

目标：让 agent 候选进入人工复核流程，避免重复覆盖用户判断。

### Task 4.1 扩展 MessageOpportunity 状态

范围：

- 在 `MessageOpportunity` 增加：
  - `evidence_score`
  - `mapping_confidence`
  - `review_status`
  - `review_reason`
  - `generated_by`
  - `accepted_at`
  - `dismissed_at`

验收：

- 旧数据默认兼容。
- `active` 机会可默认映射为 `reviewed` 或空 review_status。
- 不影响现有 daily API。

### Task 4.2 聚合不覆盖已复核机会

范围：

- 更新 `_upsert_aggregated_opportunity`。
- 仅自动覆盖 `draft` 或未复核的 agent 生成机会。
- 对 `accepted / dismissed / reviewed` 机会保留人工字段。

验收：

- 用户驳回后的候选不会被同一次聚合重新激活。
- 已复核 reason 不被自动聚合覆盖。

### Task 4.3 复核 API

范围：

```text
POST /api/messages/opportunities/{id}/review
POST /api/messages/opportunities/{id}/accept
POST /api/messages/opportunities/{id}/dismiss
```

验收：

- 可标记 reviewed。
- 可驳回候选并写入原因。
- accept 可复用加入核心关注逻辑，但仍需用户显式触发。

### Task 4.4 前端复核操作

范围：

- 在证据展开或操作列增加：
  - 标记已复核
  - 驳回
  - 加入观察

验收：

- 操作后表格状态刷新。
- 驳回原因可填写。
- 不显示任何自动交易暗示。

## 阶段 5：LLM Evidence Cleaner / Entity Mapping Agent

目标：在证据层稳定后，引入 LLM 做结构化证据抽取和更稳健的实体映射。

### Task 5.1 Prompt 与输出 Schema

范围：

- 新增 prompt 版本文件或常量。
- 定义严格 JSON 输出：
  - themes
  - entities
  - evidence
  - risk_flags
  - confidence

验收：

- prompt 明确禁止投资建议和收益承诺。
- 输出可由 Pydantic schema 校验。

### Task 5.2 LLM Evidence Cleaner

范围：

- 使用 `backend/app/services/llm_client.py`。
- 支持 provider/model 配置。
- 解析失败时回退规则版。
- 保存 raw output 到 `MessageAgentRun.output_json` 或 error。

验收：

- mock LLM 测试通过。
- 非 JSON 输出不会中断流程。
- 禁止词被 sanitizer 替换或拒绝。

### Task 5.3 Entity Mapping Agent

范围：

- 从 evidence 中识别海外 ticker、公司、产品、技术。
- 结合种子映射和图谱关系输出候选映射。
- 输出 `mapping_confidence`、`matched_terms`、`mapping_path`。

验收：

- 弱映射候选进入 `needs_review`。
- 强映射候选可以进入 `reviewed`，但仍不自动加入核心关注。

### Task 5.4 LLM 评测集

范围：

- 新增 `backend/tests/fixtures/message_agent_cases/`。
- 覆盖正常线索、spam、弱映射、多来源共振、反证、中英文混合。

验收：

- JSON 解析成功率可统计。
- 证据引用准确率可人工抽查。

## 阶段 6：Report Agent 与调度

目标：把每日结论升级为基于证据层的 agent report，并接入可控调度。

### Task 6.1 Agent Daily Conclusion

范围：

- 新增或升级：

```text
GET  /api/messages/agent-daily
POST /api/messages/agent-daily/generate
```

输出：

- headline
- summary
- top_topics
- reviewed_candidates
- risk_watch_candidates
- evidence_coverage
- next_actions

验收：

- 报告中的每个候选都能展开证据。
- 无证据时明确说明数据不足。

### Task 6.2 与产业链日报合流

范围：

- `industry_report_candidate.evidence_json` 引用 `message_evidence` 或 `message_relation_evidence`。
- 消息中心日报和产业链日报共享证据展示组件。

验收：

- 产业链候选能展示具体证据，不只是路径摘要。
- 风险和待验证提示一致。

### Task 6.3 调度接入

范围：

- 更新 `backend/app/tasks/scheduler.py` 或相关后台任务。
- 支持每日定时：
  - X 采集
  - rule/LLM evidence cleaner
  - opportunity scoring
  - report generation

验收：

- 默认可关闭。
- 支持手动触发。
- 失败记录到 `message_agent_run`，不影响 Web 服务。

## 推荐第一轮执行范围

建议下一次开发只执行：

```text
Task 1.1
Task 1.2
Task 1.3
Task 1.4
Task 1.5
Task 1.6
```

也就是：

- 新增证据层 ORM。
- 新增 schema。
- 新增规则证据服务。
- 聚合机会关联证据。
- 新增证据查询 API。
- 补后端测试。

暂不做：

- LLM agent。
- 前端复核。
- 自动调度。
- 独立 Agent 控制台。

## 验收总清单

阶段 1 完成时，必须满足：

- 导入 source items 后，能生成 topic、opportunity、evidence。
- opportunity 能查询到具体 evidence。
- evidence 能追溯到 source item。
- 重复运行不产生重复 evidence 或重复关联。
- daily API 兼容旧前端。
- 后端相关测试通过。

阶段 3 完成时，必须满足：

- 消息中心能展开机会证据。
- 用户能看到来源、片段、置信度和风险 stance。
- 无证据候选有空状态。
- 原有消息中心操作不回归。

阶段 5 完成时，必须满足：

- LLM 输出严格 JSON。
- 解析失败可回退。
- 禁止投资建议措辞被拦截。
- 弱证据候选不会被包装为强机会。

## Handoff 要求

每个阶段完成后按以下格式报告：

```text
Summary:
- ...

Files changed:
- ...

Verification:
- ...

Not tested:
- ...

Risks / follow-up:
- ...
```

涉及数据库变更时额外报告：

```text
Migration notes:
- Backup:
- Command:
- Validation:
- Rollback:
```

