# 涨停仪表盘设计（limit_cpt_list + limit_step）

> 状态：已定稿（脑暴 2026-03-29）  
> 关联脑暴纪要：`.cursor/plans` 内「涨停仪表盘脑暴定稿」

## 1. 目标与范围

- **核心场景**：「当日一战」——首屏同时呈现 **最强涨停板块** 与 **连板天梯**，感知短线情绪。
- **范围**：替换 `GET /api/dashboard` 的响应契约；前端仪表盘页改为上下双表 + 手动刷新；不实现跳转、不实现自动轮询。
- **非目标**：多日板块轮动主分析、个股/涨停池链接、假数据兜底。

## 2. 破坏性变更说明

- URL 不变：`GET /api/dashboard`。
- 响应体 **不再** 包含：`pool_summary`、`recent_alerts`、`active_plans` 及任何旧字段。
- 所有依赖旧结构的调用方（当前已知：[`frontend/src/pages/Dashboard/index.tsx`](../../frontend/src/pages/Dashboard/index.tsx)、[`frontend/src/types/index.ts`](../../frontend/src/types/index.ts)）需同步改版。
- 文档 [`docs/03-技术方案-定稿.md`](../../docs/03-技术方案-定稿.md) 中对该接口的表述需在实施时更新。

## 3. 数据源与积分

| 接口 | Tushare 文档 | 说明 | 积分（官方） |
|------|--------------|------|----------------|
| `limit_cpt_list` | [doc_id=357](https://tushare.pro/document/2?doc_id=357) | 每日涨停相关最强概念板块 | 8000+，约 500 次/分钟 |
| `limit_step` | [doc_id=356](https://tushare.pro/document/2?doc_id=356) | 每日连板晋级个股 | 同上 |

失败（含积分不足、权限、限频、网络）时 **不向客户端返回伪造表格**；由 4 节统一错误模型处理。

## 4. 默认交易日 `trade_date`（最近已完成交易日）

**产品语义**：尽量对齐 **「已收盘口径」** 的涨停/连板统计，避免盘中半成品；收盘后则展示 **当日** 完整统计。

**解析规则（单一实现入口，禁止各处散落 `date.today()`）：**

建议在 [`backend/app/services/trading_session.py`](../../backend/app/services/trading_session.py) 或同目录新建 `trade_date_resolver.py` 中提供：

```text
resolve_dashboard_trade_date(now: datetime | None = None) -> str
```

**逻辑（上海时区）：**

1. `now_sh =` 转成 `Asia/Shanghai`（与现有 `shanghai_trade_date_str`、`is_a_share_trading_session` 一致）。
2. 设 `cal_today = now_sh.strftime("%Y%m%d")`。
3. 若 `is_a_share_trading_session(now_sh)` 为 **True**（盘中）：  
   `trade_date` = **严格早于 `cal_today` 的最后一个 A 股交易日**（需交易日历，见下）。
4. 否则（盘前/午间非交易时段、盘后、周末等）：  
   - 若 **`cal_today` 为交易日** 且 `now_sh.time() >= 15:00`：`trade_date = cal_today`（视为当日已收盘，数据应已完备）。  
   - 否则：`trade_date` = **严格早于 `cal_today` 的最后一个 A 股交易日**。

**交易日历来源：** 调用 Tushare `trade_cal`（`exchange='SSE'`，`start_date`/`end_date` 覆盖 `cal_today` 前若干自然日），取 `is_open==1` 的 `cal_date` 排序后按其定义选取。仅需轻量封装于 [`TushareAdapter`](../../backend/app/services/tushare_adapter.py)（或 resolver 内临时调用 `pro.trade_cal`），结果可 **不作为** 60s 业务缓存的一部分（日历可更长 TTL 或单次请求内缓存当日解析结果，实施计划再定）。

**可选 query（建议纳入本版）：** `GET /api/dashboard?trade_date=20250328`  
- 若传入则 **跳过** 上述默认解析，直接使用该 `YYYYMMDD`（用于补数、调试）；校验格式与合理性（可选：仅校验 8 位数字）。

## 5. 后端架构

- **聚合服务**：新建例如 `backend/app/services/limit_market_board_service.py`（名称以实施为准），负责：
  - 调用 `resolve_dashboard_trade_date`（无 query 时）；
  - 通过 `TushareAdapter` 拉取 `limit_cpt_list(trade_date=…)`、`limit_step(trade_date=…)`；
  - 排序与空表处理（见 6、7 节）；
  - **内存短 TTL 缓存**：键 = `trade_date`（及本期无其他维度）；值 = 序列化前的聚合结果；默认 **TTL 60 秒**（模块级常量 `DASHBOARD_LIMIT_BOARD_CACHE_TTL_SEC = 60`，可环境变量覆盖与否由实施计划决定，YAGNI 可先常量）。
- **Router**：[`backend/app/routers/dashboard.py`](../../backend/app/routers/dashboard.py) 改为调用该服务；**不再** `Depends(get_db)` 读取池/计划/预警（除非后续另有需求）。
- **适配器**：[`tushare_adapter.py`](../../backend/app/services/tushare_adapter.py) 增加 `get_limit_cpt_list(trade_date: str) -> pd.DataFrame`、`get_limit_step(trade_date: str) -> pd.DataFrame`，内部调用 `pro.limit_cpt_list`、`pro.limit_step`。

## 6. API 响应 JSON 规格

### 6.1 顶层

| 字段 | 类型 | 说明 |
|------|------|------|
| `trade_date` | string | 本响应数据对应的 `YYYYMMDD` |
| `resolved_by` | `string` | `"default"` \| `"query"`，标明是否来自 query 覆盖 |
| `sectors` | array | 最强板块行列表，见 6.2 |
| `ladder` | array | 连板天梯行列表，见 6.3 |

成功时 **`sectors`/`ladder` 可为空数组**（当日无数据或接口返回空表），仍 HTTP 200。

### 6.2 `sectors[]`（对齐 `limit_cpt_list`）

每行对象字段与上游一致，直接透传类型（JSON 数字保持 number）：

| JSON 字段 | 类型 | Tushare 字段 | 说明 |
|-----------|------|--------------|------|
| `ts_code` | string | ts_code | 板块代码 |
| `name` | string | name | 板块名称 |
| `trade_date` | string | trade_date | 交易日期 |
| `days` | number \| null | days | 上榜天数 |
| `up_stat` | string \| null | up_stat | 连板高度（描述串） |
| `cons_nums` | number \| null | cons_nums | 连板家数 |
| `up_nums` | number \| null | up_nums | 涨停家数 |
| `pct_chg` | number \| null | pct_chg | 涨跌幅% |
| `rank` | string \| null | rank | 热点排名 |

**默认排序**：优先按 Tushare 的 **热点排名** —— `rank` 可解析为整数的按升序；无法解析的排在后；同级再按 `up_nums` 降序、`pct_chg` 降序。

**空值**：`NaN`/缺失转 `null`。

### 6.3 `ladder[]`（对齐 `limit_step`）

| JSON 字段 | 类型 | Tushare 字段 | 说明 |
|-----------|------|--------------|------|
| `ts_code` | string | ts_code | 股票代码 |
| `name` | string | name | 名称 |
| `trade_date` | string | trade_date | 交易日期 |
| `nums` | string | nums | 连板次数（上游为字符串，如 `"11"`） |

**默认排序**：将 `nums` 解析为整数，**降序**；同级按 `ts_code` 升序稳定排序。

## 7. 错误模型与 HTTP 状态

不向客户端返回虚构表格；前端 **整页错误态**。

| 场景 | HTTP | 响应体建议 |
|------|------|------------|
| Tushare 返回业务错误文案（含积分、权限） | 502 或 503 | `{ "detail": { "code": "TUSHARE_ERROR", "message": "…", "hint": "请检查 TUSHARE_TOKEN 与积分权限…" } }` |
| 限流 / 网络超时 | 503 | `code`: `TUSHARE_UNAVAILABLE` |
| 交易日历解析失败（无法得到默认日） | 503 | `code`: `TRADE_DATE_RESOLUTION_FAILED` |
| 非法 `trade_date` query | 422 | FastAPI 校验错误 |

文案需中英文可读、可操作（配置 env、Tushare 积分说明链接可置于 `hint`）。

## 8. 前端行为

- **布局**：[`Dashboard/index.tsx`](../../frontend/src/pages/Dashboard/index.tsx) —— **上** 板块表、**下** 天梯表。
- **刷新**：仅 **手动**（建议顶部「刷新」按钮调用 `getDashboard()`）；**无** `setInterval` 轮询。
- **加载 / 错误**：请求中 loading；失败展示 `detail.message` + `hint`（与现有 API client 错误结构对齐，必要时扩展 `client` 拦截器）。
- **类型**：[`DashboardData`](../../frontend/src/types/index.ts) 与 [`getDashboard`](../../frontend/src/api/dashboard.ts) 改为新契约；移除旧字段类型。

## 9. 测试建议（交付标准摘要）

- 单元测试：`resolve_dashboard_trade_date` 在 Mock 的交易日历 + 固定 `now` 下的边界（盘中、盘后 15:00+、周一盘前、query 覆盖）。
- 服务层测试：Mock `TushareAdapter`，验证排序、空 DataFrame、缓存命中（可选）。
- 契约测试：`GET /api/dashboard` 在 mock 成功/失败下的状态码与 JSON 形状。

## 10. 参考路径

- 当前仪表盘路由：[`backend/app/routers/dashboard.py`](../../backend/app/routers/dashboard.py)
- Tushare 适配器：[`backend/app/services/tushare_adapter.py`](../../backend/app/services/tushare_adapter.py)
- 交易时段工具：[`backend/app/services/trading_session.py`](../../backend/app/services/trading_session.py)

---

下一步：见 [`2026-03-29-dashboard-limit-board-plan.md`](2026-03-29-dashboard-limit-board-plan.md) 实施计划。
