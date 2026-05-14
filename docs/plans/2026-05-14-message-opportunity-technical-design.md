# 消息中心：题材与个股机会技术方案

> 日期：2026-05-14
> 目标：新增可独立运行的消息模块，承载每日题材与个股机会，并给后续多平台采集器留出写入接口。

## 1. 架构

```text
外部采集器（后续）
  -> /api/messages/topics
  -> /api/messages/opportunities
  -> 本地 SQLite
  -> /api/messages/daily
  -> 前端消息中心
  -> 核心关注 / 股票详情 / 买点雷达
```

MVP 不把外部采集器作为阻塞项。页面从本地数据库读取今日题材与机会；当今日无数据时，服务会生成一组 AI 产业种子机会，保证模块第一天即可运行和验收。

## 2. 后端模型

### 2.1 message_topic

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | UUID |
| trade_date | string | YYYYMMDD |
| theme | string | 题材名称 |
| summary | text | 题材摘要 |
| lifecycle_stage | string | early / spreading / climax / cooling |
| sentiment | string | positive / neutral / negative |
| heat_score | int | 热度分 0-100 |
| credibility_score | int | 可信度分 0-100 |
| crowding_score | int | 拥挤度 0-100 |
| source_platforms | json | 来源平台 |
| tags | json | 标签 |
| created_at / updated_at | datetime | 时间 |

唯一约束：`trade_date + theme`。

### 2.2 message_opportunity

| 字段 | 类型 | 说明 |
|---|---|---|
| id | string | UUID |
| topic_id | string/null | 关联题材 |
| trade_date | string | YYYYMMDD |
| theme | string | 冗余题材 |
| ts_code | string/null | 股票代码 |
| stock_name | string/null | 股票名称 |
| opportunity_score | int | 机会分 0-100 |
| heat_score | int | 热度分 |
| credibility_score | int | 可信度分 |
| risk_score | int | 风险分 |
| action_suggestion | string | watch / add_to_pool / risk_watch |
| reason | text | 机会逻辑 |
| catalysts | json | 催化剂 |
| risks | json | 风险 |
| source_platforms | json | 来源平台 |
| source_links | json | 来源链接 |
| status | string | active / dismissed / archived |
| created_at | datetime | 时间 |

索引：`trade_date`、`ts_code`、`opportunity_score`。

## 3. API

### GET /api/messages/daily

参数：

- `trade_date`：可选，默认上海自然日，格式 YYYYMMDD。
- `ensure_seed`：可选，默认 true。今日无数据时生成 AI 产业种子机会。

返回：

```json
{
  "trade_date": "20260514",
  "generated_at": "2026-05-14T09:00:00",
  "stats": {
    "topic_count": 4,
    "opportunity_count": 6,
    "top_score": 92
  },
  "topics": [],
  "opportunities": []
}
```

### POST /api/messages/topics

创建或更新题材。按 `trade_date + theme` 幂等更新。

### POST /api/messages/opportunities

创建个股机会。若传入 `topic_id` 则关联题材；若传入 `theme` 且不存在题材，则只以冗余主题展示。

## 4. 前端页面

路由：`/messages`

导航名称：消息中心。

页面结构：

- 顶部统计：题材数、机会数、最高分、强势题材。
- 左侧/上方：今日题材卡片。
- 主区域：个股机会表格。
- 筛选：题材、分数阈值。
- 操作：刷新、加入核心关注、查看股票详情。

## 5. 与现有系统衔接

- 股票详情：沿用 `/stocks/:tsCode`。
- 核心关注：复用 `toggleCoreWatch`。
- 买点雷达：不直接触发，用户加入核心关注后由现有流程处理。
- 交易计划：MVP 不自动创建，后续可以把机会逻辑写入计划背景。

## 6. 测试策略

后端：

- 今日摘要无数据时自动生成种子机会。
- 创建题材 API 幂等更新。
- 创建机会 API 可被今日摘要查询到。

前端：

- Playwright 进入消息中心。
- 验证题材与个股机会展示。
- 验证高分筛选。

## 7. 自检结论

该方案符合当前系统边界：不替代买点雷达，不引入外部平台不稳定依赖，先把“每日题材/个股机会”作为系统内可见、可测试、可扩展的业务对象落地。后续采集器只需要写入同一套 API，即可复用页面和工作流。
