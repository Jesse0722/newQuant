# 量化交易系统 - 文档导航

> 供 AI Agent 在新会话中快速理解项目全貌。请按编号顺序阅读。

---

## 项目简介

个人量化交易工作流管理系统。核心流程：**观察池 → 监控提醒 → 交易计划 → 执行记录 → 复盘**。

技术栈：React + TypeScript + Ant Design（前端）、Python + FastAPI + SQLAlchemy（后端）、SQLite/PostgreSQL（数据库）、多数据源（AkShare / BaoStock / Tencent / Tushare，可切换）。长期主库方向是 PostgreSQL。

---

## 文档清单（按阅读顺序）

| 编号 | 文件 | 内容 | 状态 |
|------|------|------|------|
| 01 | `01-方案讨论-定稿.md` | 产品方向脑暴的完整讨论过程记录（问答式），包含所有设计决策的推导过程 | 已定稿 |
| 02 | `02-产品设计-定稿.md` | 产品设计定稿版：定位、V1/V2 范围、模块详细设计（观察池/数据同步/监控/交易计划/交易明细）、技术架构、数据库 ER 图、页面结构 | 已定稿 |
| 03 | `03-技术方案-定稿.md` | 技术方案：项目目录结构、8 张表详细列定义、28 个 API 接口设计、监控引擎（6 模板 + 指标计算）、异步任务机制、统一错误处理 | 已定稿 |
| -- | `UI设计提示词-StitchAI.md` | 6 个页面的 ASCII 线框图（仪表盘、观察池列表、池内详情、监控提醒、交易计划列表、计划详情） | 已定稿 |
| -- | `plans/2026-03-02-v1-implementation-plan.md` | V1 详细实施计划：5 个 Phase、28 个任务，含文件路径、代码片段、验证步骤 | 已定稿 |
| -- | `plans/舆情分析模块需求.md` | 消息中心 PRD：每日题材、个股机会、平台角色、验收标准 | MVP 已实现 |
| -- | `plans/2026-05-14-message-opportunity-technical-design.md` | 消息中心与 X 舆情采集技术方案：原始消息层、X recent search、种子池、A 股映射、API、验证步骤 | MVP 已实现 |
| -- | `plans/2026-05-28-industry-graphrag-report-technical-design.md` | 产业链 GraphRAG 舆情日报技术方案：PostgreSQL、图谱模型、DeepSeek 抽取、候选评分、调度与前端展示 | MVP 已实现 |
| -- | `plans/2026-05-28-industry-graphrag-report-tasks.md` | 产业链 GraphRAG 舆情日报任务拆解：多 agent 分工、验收标准、测试清单 | MVP 已实现 |
| -- | `development-postgresql.md` | PostgreSQL 本地开发运行手册：Docker/Colima、Homebrew fallback、迁移、验证、回滚 | 当前推荐 |
| -- | `reliability.md` | Python 3.11 锁定环境、持久任务/调度、消息证据边界、迁移与发布恢复 | 当前运行标准 |
| -- | `plans/2026-11-11-reliability-hardening-plan.md` | P1/P2 集中治理范围、分工、验收与保留边界 | 本轮实施 |
| -- | `reports/2026-11-11-reliability-verification.md` | 本轮实际验证、交叉审查、备份/重启及残余限制 | 验证记录 |
| -- | `plans/2026-06-12-message-agent-technical-design.md` | 消息证据清洗、映射、复核及日报 Agent | 已有实现，默认关闭自动流水线 |
| -- | `plans/2026-05-24-main-wave-trend-technical-design.md` | 主升浪趋势研究、扫描与回测 | 已有实现 |
| -- | `plans/2026-05-22-task-notification-center-design.md` | 顶部任务消息中心设计：异步任务完成通知、任务收件箱、分期范围；策略回溯/回测放第二期 | 进行中 |
| -- | `plans/2026-07-15-market-regime-reversal-technical-design.md` | 市场状态识别与反转证据评分：数据质量闸门、市场宽度、全球因子、资金压力、状态机及主升浪集成边界 | 设计评审稿 |
| -- | `market-data-quality-audit.md` | T02 全市场日线只读校验命令、日历与点时分母输入、质量快照及退出码 | 工具已实现 |
| -- | `plans/2026-11-11-quality-evidence-gates-plan.md` | 严格证券/数值校验、离线证据包及报告工件保护 | T02 后续改造 |
| -- | `reports/2026-11-11-quality-evidence-gates-verification.md` | T02 新门禁回归、独立审查、真实只读复核及重启记录 | 真实全市场分母仍待补 |
| -- | `historical-universe-evidence.md` | 离线历史证券池构建、逐行原件溯源、独立控制和子集资格边界 | 工具及两日沪主板 A 实证通过 |
| -- | `plans/2026-11-11-real-market-evidence-plan.md` | 新量额疑点、历史证券池和真实证据包的实施范围 | 本轮实施 |
| -- | `reports/2026-11-11-920083-amount-evidence.md` | 920083 当日大宗与量额统计范围核验，原行保留及解释限制 | 官方事实已核验，不豁免金额闸门 |
| -- | `reports/2026-11-11-real-market-evidence-execution.md` | 两日3400证券日、13源证据绑定、主库缺口、完整回归及重启 | 子集验证通过，全市场仍不放行 |
| -- | `full-market-history-sync.md` | T06 数据源能力、历史按日/逐股回补、缺口请求、日期覆盖与失败结果 | 代码已实现，真实回补待验收 |
| -- | `daily-quote-repair.md` | T07/T08 单源快照、只读差异、备份、逐行审计、批次回滚及恢复验证 | 受控修复与沪市 pilot 通过，全市场质量未达标 |
| -- | `reports/2026-11-04-quote-repair-implementation.md` | T07/T08 验证结果、真实只读样例和操作边界 | 实施记录 |
| -- | `reports/2026-11-05-quote-repair-batch01-execution.md` | 主库首批 3 条更新/4 条新增、副本回滚、备份链及 T02 前后对照 | 已执行，后续批量修复待推进 |
| -- | `reports/2026-11-05-quote-repair-batch02-execution.md` | 第二批 5 条受保护更新、全库逐行对照及 T02 复核 | 已执行，累计两批审计通过 |
| -- | `reports/2026-11-05-gap14-backfill-plan.md` | 14 个整日缺口、冻结代理范围、单源分块与验收闸门 | 历史方案，已进入分市场小样本验证 |
| -- | `reports/2026-11-08-gap14-pilot-execution.md` | 冻结沪深各 10/北交所 5 只，真实来源验证、沪市 140 条新增及深京暂停原因 | 沪市样本已执行，评分仍不放行 |
| -- | `reports/2026-11-11-security-lifecycle-evidence.md` | 000004 摘牌、则成新旧代码映射/生效推导及原始披露冲突 | 官方证据已归档，不自动改主数据 |
| -- | `reports/2026-11-11-real-quote-repair-execution.md` | 三组真实修复、完整网格保护、副本精确回滚及主库全表对照 | 12 新增/3 更新，评分仍不放行 |
| -- | `reports/2026-11-04-t02-findings.md` | 当前本地主库、120 日覆盖诊断、最近 20 日异常及验证结果 | 已核查 |
| -- | `plans/2026-03-01-涨停回调买入策略.md` | 涨停回调买入策略实施方案（已实施） | 已归档 |
| -- | `plans/2026-04-14-五日均线不破策略.md` | 五日均线不破（`ma5_hold_pullback`）量化口径与回测说明 | 已归档 |
| -- | `PLANNING_WITH_SUPERPOWERS.md` | Superpowers 问答式规划流程说明 | 参考 |

---

## 新会话快速上手

1. **理解产品**：读 `02-产品设计-定稿.md`（产品需求全貌）
2. **理解技术**：读 `03-技术方案-定稿.md`（API、数据库、项目结构）
3. **理解实施**：读 `plans/2026-03-02-v1-implementation-plan.md`（任务清单）
4. **了解决策过程**：如需回溯设计决策，读 `01-方案讨论-定稿.md`

消息中心 / 舆情采集相关工作请额外阅读：

1. `plans/舆情分析模块需求.md`
2. `plans/2026-05-14-message-opportunity-technical-design.md`
3. `plans/2026-05-28-industry-graphrag-report-technical-design.md`
4. `plans/2026-05-28-industry-graphrag-report-tasks.md`

数据库迁移、PostgreSQL 开发和回滚请额外阅读：

1. `development-postgresql.md`

---

## 实施顺序

```
Phase 1 → 基础骨架（项目结构 + 数据库 + Tushare 适配 + FastAPI 入口）
Phase 2 → 观察池 + 数据同步（CRUD + CSV 导入 + 增量同步 250 天）
Phase 3 → 监控提醒（指标计算 + 6 模板 + 扫描引擎 + Alert）
Phase 4 → 交易计划（计划 CRUD + 明细 + 复盘 + 盈亏汇总 + 仪表盘）
Phase 5 → 前端（React + Ant Design，6 个页面 + 联调）
```

当前进度：**V1 及后续消息/图谱/主升浪功能已有实现**。运行质量、剩余验收与当前路线以 `TODO.md` 和最新验证记录为准；不能将历史联调通过等同当前全市场数据已达标。

---

## 启动服务

**前置**：
- `backend/.env` 已完成基础配置（可从 `backend/.env.example` 复制）
- 快速记录 OCR 功能需安装 Tesseract：`brew install tesseract`（中文：`brew install tesseract-lang`）
- AI 智能选股需配置 `OPENAI_API_KEY` 或 `DASHSCOPE_API_KEY` 或 `OLLAMA_BASE_URL`（见 `.env.example`）
- X 舆情采集需配置 `X_API_BEARER_TOKEN`，并确保 X Developer Console credits 可用。

```bash
# 后端（默认 http://localhost:8000）
cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端（默认 http://localhost:5173 或 3000）
cd frontend && npm run dev
```

**注意**：代码更新后需**重启后端**，否则新接口（如全市场同步）可能返回 404。

**Tushare 连接排查（可选）**：数据管理页点击「检查 Tushare 连接」可诊断 token、代理、接口是否正常。若 stock_basic 返回空，请确认：
- `backend/.env` 中 `TUSHARE_TOKEN` 已正确填写（从 tushare.pro 获取）
- 使用代理时，`TUSHARE_API_URL` 需与代理地址一致
- 修改 .env 后需重启后端

**重要澄清（2026-05）**：涨停筛选功能已改为 AkShare 主数据源，不再依赖 Tushare token。

---

## 项目配置

| 配置 | 路径 | 说明 |
|------|------|------|
| Cursor 规则 | `.cursorrules` | 全局规则（中文、Superpowers 工作流） |
| Brainstorming | `.cursor/rules/brainstorming.mdc` | 规划/设计时自动触发的问答式流程 |
| Writing Plans | `.cursor/rules/writing-plans.mdc` | 生成实施计划的规则 |
| Subagent Dev | `.cursor/rules/subagent-driven-dev.mdc` | Subagent 驱动开发规则 |

---

## V1 模块概览

| 模块 | 说明 |
|------|------|
| 观察池 | Tab 式多分组导航（支持拖拽排序）、CRUD + 编辑、最新价/涨幅实时展示、加入价格内联编辑、CSV 批量导入、按名称/代码添加股票、备注悬停 Tooltip、工具栏创建交易计划、涨停日期列、买点目标池配置 |
| 股票详情 | 基本信息卡片、ECharts K 线图（蜡烛图 + MA5/10/20 + 成交量 + MACD/RSI 切换）、关联监控提醒 + 交易计划 |
| 数据同步 | 仅观察池中股票、Tushare Pro（支持代理）、增量同步、加入时自动拉 250 天 |
| 监控提醒 | 6 个预置模板 + 自定义组合、同步后自动扫描 + 手动、系统内提醒 |
| 交易计划 | 列表内嵌详情（expandable）、默认展开最近计划、CRUD + 编辑（含成功/失败反馈）、价格目标 + 盈亏比、风险等级、计划级复盘；`/plans/:id` 重定向至 `/plans?expand=id` |
| 交易明细 | 手动记录 + 编辑、按股票累计账本、自动算金额/印花税；当前现金流与复盘快照分列，不宣称计划级归因 |
| 策略选股 | 指标组合（10 条件）+ AI 智能选股、批量添加 / 快捷建池 |
| 消息中心 | 今日题材、个股机会、X recent search 小批量采集、海外线索到 A 股候选映射、加入核心关注 |
| 数据管理 | 全市场 60 日 K 线增量同步、数据概览、涨停筛选、异步任务结果（成功/失败/跳过） |

## 数据管理（V2 已实现）

- **全市场 60 日 K 线**：增量同步，已有数据不重复拉取
- **异步任务**：后台执行，轮询展示进度与结果（成功/跳过/失败天数）
- **数据概览**：股票数量、行情条数、日期范围
- **同步前**：自动同步 stock_basic 全量

---

## 策略选股（V2 已实现）

- **指标组合选股**：最多 10 个条件（MA 金叉、MACD 金叉、RSI 超卖等），支持全市场或池内筛选
- **AI 智能选股**：一句话描述（≤200 字），支持 OpenAI / 通义千问 / Ollama
- **添加到观察池**：批量添加、快捷创建新池

---

## 涨停回调买入策略（已实现）

- **涨停筛选**：数据管理页执行，将近期涨停股加入「涨停股票观察池」，打涨停日期标签
- **涨停判断**：主板 ≥9.9%、创业板/科创板 ≥19.9%、北交所 ≥29.9%，排除 ST
- **监控买点**：涨停池默认 ma_support(n=10)，回踩 10 日均线 ±2% 触发
- **自动加入**：池可配置「买点触发后加入」目标池，触发时自动将股票加入

---

## 当前后续路线

1. 完成可靠性变更的运行验收，继续修复真实行情与权威点时证券分母；保持评分质量闸门。
2. 数据达标后进入市场状态 Phase 1，再逐步评估全球因子及资金证据。
3. 历史分析对比、通知跨设备与新增授权来源按独立产品决策安排。

回测及 AI 候选入池已经存在；本项目保持研究支持定位，不把自动交易列为默认路线。
