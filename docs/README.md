# 量化交易系统 - 文档导航

> 供 AI Agent 在新会话中快速理解项目全貌。请按编号顺序阅读。

---

## 项目简介

个人量化交易工作流管理系统。核心流程：**观察池 → 监控提醒 → 交易计划 → 执行记录 → 复盘**。

技术栈：React + TypeScript + Ant Design（前端）、Python + FastAPI + SQLite（后端）、Tushare Pro（数据源）。

---

## 文档清单（按阅读顺序）

| 编号 | 文件 | 内容 | 状态 |
|------|------|------|------|
| 01 | `01-方案讨论-定稿.md` | 产品方向脑暴的完整讨论过程记录（问答式），包含所有设计决策的推导过程 | 已定稿 |
| 02 | `02-产品设计-定稿.md` | 产品设计定稿版：定位、V1/V2 范围、模块详细设计（观察池/数据同步/监控/交易计划/交易明细）、技术架构、数据库 ER 图、页面结构 | 已定稿 |
| 03 | `03-技术方案-定稿.md` | 技术方案：项目目录结构、8 张表详细列定义、28 个 API 接口设计、监控引擎（6 模板 + 指标计算）、异步任务机制、统一错误处理 | 已定稿 |
| -- | `UI设计提示词-StitchAI.md` | 6 个页面的 ASCII 线框图（仪表盘、观察池列表、池内详情、监控提醒、交易计划列表、计划详情） | 已定稿 |
| -- | `plans/2026-03-02-v1-implementation-plan.md` | V1 详细实施计划：5 个 Phase、28 个任务，含文件路径、代码片段、验证步骤 | 已定稿 |
| -- | `PLANNING_WITH_SUPERPOWERS.md` | Superpowers 问答式规划流程说明 | 参考 |

---

## 新会话快速上手

1. **理解产品**：读 `02-产品设计-定稿.md`（产品需求全貌）
2. **理解技术**：读 `03-技术方案-定稿.md`（API、数据库、项目结构）
3. **理解实施**：读 `plans/2026-03-02-v1-implementation-plan.md`（任务清单）
4. **了解决策过程**：如需回溯设计决策，读 `01-方案讨论-定稿.md`

---

## 实施顺序

```
Phase 1 → 基础骨架（项目结构 + 数据库 + Tushare 适配 + FastAPI 入口）
Phase 2 → 观察池 + 数据同步（CRUD + CSV 导入 + 增量同步 250 天）
Phase 3 → 监控提醒（指标计算 + 6 模板 + 扫描引擎 + Alert）
Phase 4 → 交易计划（计划 CRUD + 明细 + 复盘 + 盈亏汇总 + 仪表盘）
Phase 5 → 前端（React + Ant Design，6 个页面 + 联调）
```

当前进度：**V1 全部功能已完成**，前后端联调通过，真实数据验证完毕。

---

## 启动服务

**前置**：确保 `backend/.env` 已配置 `TUSHARE_TOKEN`（可从 `backend/.env.example` 复制并填入）。

```bash
# 后端（默认 http://localhost:8000）
cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000

# 前端（默认 http://localhost:5173 或 3000）
cd frontend && npm run dev
```

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
| 观察池 | Tab 式多分组导航、CRUD + 编辑、最新价/涨幅实时展示、加入价格内联编辑、CSV 批量导入、股票代码自动补全 |
| 股票详情 | 基本信息卡片、ECharts K 线图（蜡烛图 + MA5/10/20 + 成交量 + MACD/RSI 切换）、关联监控提醒 + 交易计划 |
| 数据同步 | 仅观察池中股票、Tushare Pro（支持代理）、增量同步、加入时自动拉 250 天 |
| 监控提醒 | 6 个预置模板 + 自定义组合、同步后自动扫描 + 手动、系统内提醒 |
| 交易计划 | 单股/计划、CRUD + 编辑、价格目标 + 盈亏比（自动计算）、风险等级 1-5 星、计划级复盘 |
| 交易明细 | 手动记录 + 编辑、关联交易计划、自动算金额/印花税、盈亏自动汇总 |

## V2 规划（后续）

- AI 工作流驱动选股（一键导入观察池）
- 回测模块
- 微信/钉钉 webhook 推送
- 周期性复盘报告、PDF 导出
- 实盘接口
