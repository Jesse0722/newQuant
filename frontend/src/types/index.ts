export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export interface JsonObject {
  [key: string]: JsonValue
}

export interface Pool {
  id: string
  name: string
  description?: string
  default_monitor_rule?: JsonObject
  trigger_target_pool_id?: string
  stock_count: number
  created_at: string
  updated_at: string
}

export interface WatchStock {
  id: string
  pool_id: string
  ts_code: string
  stock_name?: string
  added_at: string
  added_price?: number
  latest_price?: number
  pct_chg?: number
  industry?: string
  trade_date?: string
  source: string
  monitor_status: string
  pinned: boolean
  note?: string
  ai_analysis?: string
  ai_analyzed_at?: string
  limit_up_date?: string
  created_at: string
}

export interface StockBasicInfo {
  ts_code: string
  name: string
  industry?: string
  area?: string
  market?: string
  list_date?: string
}

export interface QuoteItem {
  date: string
  open: number
  high: number
  low: number
  close: number
  vol: number
  amount: number
  pct_chg: number
  turnover_rate?: number | null
}

export interface StockChartData {
  basic: StockBasicInfo
  quotes: QuoteItem[]
  sync_meta?: {
    auto_sync_attempted: boolean
    status: 'updated' | 'up_to_date' | 'sync_failed'
    message: string
    latest_trade_date?: string | null
    added_count?: number
  }
  /** 本地历史不足时向前补齐日线的结果（与所选周期 period+60 条有关） */
  chart_depth_meta?: {
    chart_depth_attempted: boolean
    status: 'updated' | 'unchanged' | 'failed' | 'timeout'
    message: string
    rows_before?: number
    rows_after?: number
    added_count?: number
    need_rows?: number
  }
  indicators: {
    ma5: (number | null)[]
    ma10: (number | null)[]
    ma20: (number | null)[]
    macd: {
      dif: (number | null)[]
      dea: (number | null)[]
      histogram: (number | null)[]
    }
    rsi: (number | null)[]
  }
}

export interface StockAlertItem {
  id: string
  trigger_date: string
  status: string
  snapshot?: JsonObject & { close?: number }
  created_at: string
}

export interface StockPlanItem {
  id: string
  title?: string
  status: string
  risk_level: number
  actual_pnl?: number
  created_at: string
}

export interface MonitorTemplate {
  id: string
  name: string
  description: string
  default_params: JsonObject
}

export interface MonitorRule {
  id: string
  pool_id?: string
  stock_id?: string
  template_id?: string
  template_name?: string
  params?: JsonObject
  logic: string
  is_active: boolean
  created_at: string
}

export interface Alert {
  id: string
  stock_id: string
  rule_id?: string | null
  source?: string
  buy_strategy_id?: string | null
  ts_code: string
  stock_name?: string
  industry?: string | null
  template_name?: string
  strategy_name?: string
  latest_price?: number
  pct_chg?: number
  buy_signal?: Partial<BuySignal>
  scan_meta?: JsonObject & { intraday_provisional?: boolean }
  trigger_date: string
  status: string
  plan_id?: string
  snapshot?: JsonObject & { close?: number }
  created_at: string
}

export interface TradeDetail {
  id: string
  ts_code: string
  trade_date: string
  trade_time?: string
  direction: string
  price: number
  quantity: number
  amount: number
  commission: number
  stamp_tax: number
  exec_note?: string
  created_at: string
}

export interface TradePlanStock {
  id: string
  plan_id: string
  ts_code: string
  stock_name?: string
  risk_level: number  // 1=低 2=中 3=高
  trigger_strategy?: string
  planned_buy_price?: number
  target_price?: number
  stop_loss_price?: number
  risk_reward_ratio?: number
  position_plan?: string
  note?: string
  details?: TradeDetail[]
}

export interface PnlSummary {
  total_buy_amount: number
  total_sell_amount: number
  total_commission: number
  total_stamp_tax: number
  net_pnl: number
  holding_quantity: number
}

export interface TradePlan {
  id: string
  title: string
  status: string
  alert_id?: string
  actual_pnl?: number
  review_summary?: string
  lessons_learned?: string
  note?: string
  created_at: string
  updated_at: string
  stocks: TradePlanStock[]
  pnl_summary?: PnlSummary
}

export interface DashboardLimitSectorRow {
  ts_code: string
  name: string
  trade_date: string
  days?: number | null
  up_stat?: string | null
  cons_nums?: number | null
  up_nums?: number | null
  pct_chg?: number | null
  rank?: string | null
}

export interface DashboardLimitLadderRow {
  ts_code: string
  name: string
  trade_date: string
  nums: string
  /** 所属行业（stock_basic.industry） */
  industry?: string | null
}

export interface DashboardFlowSectorRow {
  rank?: string | null
  name: string
  trade_date?: string | null
  up_nums?: number | null
  down_nums?: number | null
  pct_chg?: number | null
  cons_nums?: number | null
  max_limit_times?: number | null
  up_stat?: string | null
}

export interface DashboardSummary {
  inflow_sector_count: number
  outflow_sector_count: number
  inflow_limit_count: number
  outflow_limit_count: number
  net_limit_count: number
  flow_ratio?: number | null
  max_up_streak: number
  max_down_streak: number
  outflow_source?: string | null
}

export interface DashboardData {
  trade_date: string
  resolved_by: 'default' | 'query'
  sectors: DashboardLimitSectorRow[]
  ladder: DashboardLimitLadderRow[]
  inflow_sectors?: DashboardFlowSectorRow[]
  inflow_ladder?: DashboardLimitLadderRow[]
  outflow_sectors?: DashboardFlowSectorRow[]
  outflow_ladder?: DashboardLimitLadderRow[]
  summary?: DashboardSummary
}

export interface TaskStatus {
  task_id: string
  status: string
  progress: number
  message?: string
  result?: {
    success_count?: number
    failed_count?: number
    skipped_count?: number
    days_synced?: number
    failed_dates?: Array<{ date: string; message: string }>
    message?: string
  }
}

export interface DataSummary {
  stock_count: number
  total_quotes: number
  quote_date_range: { min: string | null; max: string | null }
  last_sync_at: string | null
}

export interface SyncHistoryItem {
  id: string
  task_type: string
  status: string
  target?: string | null
  started_at: string | null
  completed_at: string | null
  result?: {
    success_count?: number
    failed_count?: number
    skipped_count?: number
    days_synced?: number
    message?: string
    diagnostic?: string
    added?: number
    updated?: number
  }
}

export interface SyncOverview {
  days: number
  total: {
    tasks: number
    success: number
    failed: number
    skipped: number
  }
  by_task_type: Array<{
    task_type: string
    tasks: number
    success: number
    failed: number
    skipped: number
  }>
}

export interface Pagination<T> {
  items: T[]
  total: number
}

// ---------- 消息中心 ----------

export type MessageLifecycleStage = 'early' | 'spreading' | 'climax' | 'cooling' | string
export type MessageSentiment = 'positive' | 'neutral' | 'negative' | string
export type MessageActionSuggestion = 'watch' | 'add_to_pool' | 'risk_watch' | string

export interface MessageTopic {
  id: string
  trade_date: string
  theme: string
  summary?: string | null
  lifecycle_stage: MessageLifecycleStage
  sentiment: MessageSentiment
  heat_score: number
  credibility_score: number
  crowding_score: number
  source_platforms: string[]
  tags: string[]
  created_at: string
  updated_at: string
}

export interface MessageOpportunity {
  id: string
  topic_id?: string | null
  trade_date: string
  theme: string
  ts_code?: string | null
  stock_name?: string | null
  opportunity_score: number
  heat_score: number
  credibility_score: number
  risk_score: number
  action_suggestion: MessageActionSuggestion
  reason?: string | null
  catalysts: string[]
  risks: string[]
  source_platforms: string[]
  source_links: string[]
  status: string
  created_at: string
}

export interface MessageSourceItem {
  id: string
  trade_date: string
  channel: string
  source_name?: string | null
  external_id?: string | null
  title?: string | null
  content: string
  url?: string | null
  published_at?: string | null
  captured_at: string
  theme?: string | null
  ts_code?: string | null
  stock_name?: string | null
  tags: string[]
  sentiment: MessageSentiment
  heat_score: number
  credibility_score: number
  dedupe_key: string
  raw_payload?: Record<string, unknown> | null
  status: string
}

export interface MessageSourceItemInput {
  trade_date?: string
  channel: string
  source_name?: string
  external_id?: string
  title?: string
  content: string
  url?: string
  published_at?: string
  theme?: string
  ts_code?: string
  stock_name?: string
  tags?: string[]
  sentiment?: MessageSentiment
  heat_score?: number
  credibility_score?: number
  raw_payload?: Record<string, unknown>
}

export interface MessageSourceImportResult {
  created_count: number
  skipped_count: number
  items: MessageSourceItem[]
  aggregation?: {
    trade_date: string
    topic_count: number
    opportunity_count: number
    source_item_count: number
  } | null
}

export interface MessageSeedKeyword {
  id?: string | null
  keyword: string
  type: string
  theme: string
  priority: number
  language: string
  status: string
}

export interface MessageSeedKeywordInput {
  keyword: string
  type?: string
  theme: string
  priority?: number
  language?: string
  status?: string
}

export interface MessageKeywordImportResult {
  created_count: number
  updated_count: number
  skipped_count: number
  items: MessageSeedKeyword[]
}

export interface MessageXAccount {
  handle: string
  platform: string
  category: string
  theme: string
  weight: number
  status: string
}

export interface MessageXSeedSummary {
  keyword_count: number
  account_count: number
  top_themes: string[]
  keywords: MessageSeedKeyword[]
  accounts: MessageXAccount[]
}

export interface MessageXCollectRequest {
  trade_date?: string
  query?: string
  min_priority?: number
  keyword_limit?: number
  max_results?: number
  aggregate?: boolean
}

export interface MessageXCollectResult {
  query: string
  raw_count: number
  imported: MessageSourceImportResult
}

export interface MessageConclusionTopic {
  theme: string
  heat_score: number
  credibility_score: number
  crowding_score: number
  lifecycle_stage: MessageLifecycleStage
  source_platforms: string[]
  conclusion: string
}

export interface MessageConclusionOpportunity {
  theme: string
  ts_code?: string | null
  stock_name?: string | null
  opportunity_score: number
  risk_score: number
  action_suggestion: MessageActionSuggestion
  conclusion: string
  source_links: string[]
}

export interface MessageDailyConclusion {
  trade_date: string
  generated_at: string
  headline: string
  conclusion: string
  next_action: string
  top_topics: MessageConclusionTopic[]
  top_opportunities: MessageConclusionOpportunity[]
}

export interface MessageDaily {
  trade_date: string
  generated_at: string
  stats: {
    topic_count: number
    opportunity_count: number
    top_score?: number | null
    leading_theme?: string | null
  }
  topics: MessageTopic[]
  opportunities: MessageOpportunity[]
}

// ---------- 买点雷达 ----------

export type BuySignalStatus =
  | 'triggered'
  | 'provisional_triggered'
  | 'confirmed_triggered'
  | 'approaching'
  | 'tracking'
  | 'invalidated'

export interface BuySignal {
  ts_code: string
  name: string
  industry?: string
  signal_status: BuySignalStatus
  signal_score: number
  life_line_date: string | null
  life_line_price: number | null
  days_since_life_line: number | null
  latest_close: number | null
  latest_pct_chg: number | null
  phase2_high: number | null
  pullback_pct: number | null
  met_conditions: string[]
  unmet_conditions: string[]
  rsi: number | null
  macd_hist: number | null
  volume_ratio: number | null
  signal_persist_days?: number
  stop_loss_price?: number | null
  target_price?: number | null
  stop_loss_pct?: number | null
  target_return_pct?: number | null
  risk_reward_ratio?: number | null
}

export interface BuySignalScanResult {
  signals: BuySignal[]
  scan_time: string
  total: number
  triggered_count: number
  approaching_count: number
  strategy_id?: string
  strategy_name?: string
  scan_data_mode?: 'intraday_merged' | 'historical_only'
  as_of?: string
  intraday_provisional?: boolean
  trade_date_today?: string
  realtime?: {
    requested: boolean
    applied: boolean
    error?: string | null
  }
  provisional_count?: number
  confirmed_count?: number
  min_confirm_hits?: number
}

export interface BuyStrategy {
  id: string
  name: string
  description: string
}

export interface IntradayScanConfigItem {
  pool_id: string
  strategy_id: string
  enabled: boolean
  interval_minutes: number
  min_confirm_hits: number
}

export interface StrategyBacktestSignal {
  ts_code: string
  name: string
  trigger_date: string
  entry_price: number
  return_1d?: number | null
  return_3d?: number | null
  return_5d?: number | null
  signal_score: number
}

export interface StrategyBacktestResult {
  strategy_id: string
  trade_date_from: string
  trade_date_to: string
  total_signals: number
  win_rate_1d: number
  win_rate_3d: number
  win_rate_5d: number
  avg_return_1d: number
  avg_return_3d: number
  avg_return_5d: number
  max_drawdown: number
  profit_factor: number
  signals: StrategyBacktestSignal[]
}

export interface StrategyBacktestTaskStatus {
  task_id: string
  status: 'running' | 'completed' | 'failed' | string
  progress: number
  message: string
  result?: StrategyBacktestResult
}

export interface AiAnalysisResult {
  score: number
  trend: '上涨' | '震荡' | '下跌' | string
  技术面: string
  基本面: string
  量能: string
  风险提示: string
  操作建议: string
  summary: string
}

export interface SignalMark {
  date: string
  type: 'life_line' | 'phase2_high' | 'buy_signal'
  label: string
  value: number | null
}

export interface StockChartDataWithMarks extends StockChartData {
  signal_marks?: SignalMark[]
}
