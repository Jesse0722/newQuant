# 涨停仪表盘（limit_cpt_list + limit_step）实施计划

> **执行方式：** 使用 subagent-driven-dev 规则逐任务实施。

**目标：** 将 `GET /api/dashboard` 替换为基于 Tushare `limit_cpt_list` 与 `limit_step` 的涨停情绪仪表盘，并完成前端双表展示与手动刷新。

**架构：** `dashboard` 路由调用聚合服务；服务内解析默认交易日、60s TTL 内存缓存、经 `TushareAdapter` 拉取两接口并排序；前端仅消费新 JSON 契约，失败整页错误态。

**技术栈：** FastAPI、tushare、pandas、Vitae/React（现有）、pytest、unittest。

**设计依据：** [2026-03-29-dashboard-limit-board-design.md](2026-03-29-dashboard-limit-board-design.md)

---

### 任务 1：交易日解析（TDD）

**文件：**
- 创建：`backend/app/services/trade_date_resolver.py`
- 修改：`backend/app/services/tushare_adapter.py`（新增 `get_trade_cal_open_dates` 或 `get_last_open_days` 封装 `trade_cal`）
- 测试：`backend/tests/test_trade_date_resolver.py`

**步骤 1：编写失败的测试**

```python
# test_trade_date_resolver.py — 示例场景
# - 盘中（周一 10:00）→ 应为上一交易日（如 20250328）
# - 周一 9:00 非交易时段 → 同上
# - 交易日 16:00 → 应为当日
# - 周六 12:00 → 应为最近开市日
# - 传入 trade_cal DataFrame mock，避免真实 Tushare
def test_resolve_dashboard_trade_date_during_session_uses_previous_open_day():
    ...
```

**步骤 2：运行测试确认失败**

运行：`cd backend && python -m pytest tests/test_trade_date_resolver.py -v`  
预期：FAIL（模块或函数不存在）

**步骤 3：编写最小实现**

- `trade_date_resolver.resolve_dashboard_trade_date(now, trade_cal_df=None, fetch_cal=None)`：按设计文档 4 节逻辑；若 `trade_cal_df` 为 `None` 则通过回调或注入的 adapter 拉取 `SSE` 最近约 30 自然日 `is_open==1` 的日期列表。
- 保持逻辑在单一函数/小模块内，便于测试注入日历。

**步骤 4：运行测试确认通过**

运行：`python -m pytest tests/test_trade_date_resolver.py -v`  
预期：PASS

**步骤 5：提交**

```bash
git add backend/app/services/trade_date_resolver.py backend/app/services/tushare_adapter.py backend/tests/test_trade_date_resolver.py
git commit -m "feat(dashboard): add trade date resolver for limit board default date"
```

---

### 任务 2：Tushare 适配器 — limit 接口

**文件：**
- 修改：`backend/app/services/tushare_adapter.py`
- 测试：可选 `backend/tests/test_tushare_adapter_limit.py`（mock `pro`，断言调用参数）；或合并进任务 3 的集成 mock

**步骤 1：实现**

```python
def get_limit_cpt_list(self, trade_date: str) -> pd.DataFrame:
    return self.pro.limit_cpt_list(trade_date=trade_date)

def get_limit_step(self, trade_date: str) -> pd.DataFrame:
    return self.pro.limit_step(trade_date=trade_date)
```

空结果返回空 `DataFrame`（与 pandas 默认一致）。

**步骤 2：提交**

```bash
git add backend/app/services/tushare_adapter.py
git commit -m "feat(tushare): add limit_cpt_list and limit_step helpers"
```

---

### 任务 3：聚合服务 + 缓存 + 排序

**文件：**
- 创建：`backend/app/services/limit_market_board_service.py`
- 测试：`backend/tests/test_limit_market_board_service.py`

**步骤 1：编写失败的测试**

- Mock `TushareAdapter`：返回固定 DataFrame，断言 `sectors` 按 `rank`/`up_nums` 排序，`ladder` 按 `nums` 降序。
- 第二次调用同 `trade_date` 在 TTL 内应 **不重复** 调用 adapter（可用 mock 的 `call_count`）。

**步骤 2：实现**

- `get_limit_market_board_payload(trade_date: str | None, resolved_by: str)`：
  - `trade_date` 有值则 `resolved_by='query'`，否则解析默认日 `'default'`。
  - 缓存键：`(trade_date,)`；TTL 60s；线程值：`threading.Lock` 保护简单 dict。
- DataFrame → list[dict]：`replace({np.nan: None})` 或逐列处理，与设计 6 节一致。

**步骤 3：pytest 通过**

**步骤 4：提交**

```bash
git add backend/app/services/limit_market_board_service.py backend/tests/test_limit_market_board_service.py
git commit -m "feat(dashboard): limit market board service with sort and TTL cache"
```

---

### 任务 4：Dashboard 路由

**文件：**
- 修改：`backend/app/routers/dashboard.py`
- 测试：`backend/tests/test_dashboard_limit_board_api.py`（`TestClient` + mock service 或 patch `get_limit_market_board_payload`）

**步骤 1：实现**

- 删除 `get_db` 及池/预警/计划查询。
- `GET /api/dashboard?trade_date=` 可选。
- 成功：返回 `{ trade_date, resolved_by, sectors, ladder }`。
- 捕获 Tushare/解析异常 → `HTTPException` 502/503 与设计 7 节 `detail` 结构一致。

**步骤 2：测试**

- 200 +  body 形状
- 422 非法日期（若加入校验）
- 503 mock 解析失败

**步骤 3：提交**

```bash
git add backend/app/routers/dashboard.py backend/tests/test_dashboard_limit_board_api.py
git commit -m "feat(api): replace GET /dashboard with limit board payload"
```

---

### 任务 5：前端类型与页面

**文件：**
- 修改：`frontend/src/types/index.ts`（`DashboardData` 新结构）
- 修改：`frontend/src/pages/Dashboard/index.tsx`（双表、手动刷新按钮、错误整页）
- 可选：修改：`frontend/src/api/client.ts` 或错误展示工具以读取 `detail.hint`

**步骤 1：更新类型**

与设计 6 节一致；删除旧 `pool_summary` / `recent_alerts` / `active_plans`。

**步骤 2：页面**

- 顶部：标题、`trade_date`、`resolved_by` 文案、`刷新` 按钮。
- `Table` 或 antd Table：上 `sectors` 列（rank, name, up_nums, cons_nums, pct_chg, up_stat, days, ts_code）
- 下 `ladder` 列（nums, name, ts_code）
- `getDashboard()` 错误时整页 `Alert` 或 Result，展示 `message` + `hint`。

**步骤 3：本地验证**

`npm run build`（或 `pnpm` 以项目为准）

**步骤 4：提交**

```bash
git add frontend/src/types/index.ts frontend/src/pages/Dashboard/index.tsx frontend/src/api/dashboard.ts
git commit -m "feat(ui): dashboard limit board tables and manual refresh"
```

---

### 任务 6：文档与收尾

**文件：**
- 修改：`docs/03-技术方案-定稿.md`（`/api/dashboard` 响应说明）

**步骤：**

```bash
git add docs/03-技术方案-定稿.md
git commit -m "docs: update dashboard API contract for limit board"
```

重启前后端服务（按 `.cursorrules` 部署约定）。

---

## 执行交接

计划已保存到 `docs/plans/2026-03-29-dashboard-limit-board-plan.md`。两种执行方式：

1. **Subagent 驱动（当前会话）** — 每个任务分派独立 subagent，任务间自动 review，快速迭代  
2. **手动执行** — 按计划逐步实施，每批任务后人工确认  

选择哪种方式？
