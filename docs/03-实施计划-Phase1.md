# 量化交易系统 - 实施计划（Phase 1）

> 基于 `01-产品设计-定稿.md`，Phase 1 具体实施步骤。

---

## 当前进度

**已完成**：
- 后端：`config.py`、`database.py`、`StockBasic`/`DailyQuote` 模型、Tushare 适配层、`DataService` 同步服务
- 依赖：`requirements.txt`、`.env.example`

**未完成**：
- API 路由、main 入口
- 前端项目骨架
- Phase 2-5

---

## Phase 1 实施步骤

### 1. 后端 API 与入口

| 文件 | 内容 |
|------|------|
| `app/main.py` | FastAPI 应用、CORS、路由挂载、`init_db` |
| `app/routers/stocks.py` | `GET /api/stocks`：分页、关键词、行业筛选 |
| `app/routers/data.py` | `POST /api/data/sync`：type=stock_basic|daily, start_date, end_date, ts_codes? |
| `app/schemas/stock.py` | `StockOut`、`SyncRequest` 等 Pydantic 模型 |

### 2. 前端项目骨架

- Vite + React + TypeScript + Ant Design
- 路由：`/data/stocks`、`/data/sync`，选股/股票池/回测占位
- API 客户端：axios，baseURL `/api`，Vite proxy 到后端

### 3. 验证

- 配置 TUSHARE_TOKEN 后，同步股票列表、拉取日线
- 前端展示股票列表、数据同步表单可成功调用

---

## 后续 Phase 简述

| Phase | 核心交付 |
|-------|----------|
| Phase 2 | 因子模板 + 表达式解析、选股 API、结果入池 |
| Phase 3 | 股票池 CRUD、快照、标签/记录 |
| Phase 4 | backtrader 引擎、策略模板 + 自定义规则、异步任务（SQLite 队列）、回测 API |
| Phase 5 | 选股/池/回测页面、仪表盘简化版、回测结果渲染、PDF 报告、联调 |
