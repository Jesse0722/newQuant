export interface Pool {
  id: string
  name: string
  description?: string
  default_monitor_rule?: Record<string, any>
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
  snapshot?: Record<string, any>
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
  default_params: Record<string, any>
}

export interface MonitorRule {
  id: string
  pool_id?: string
  stock_id?: string
  template_id?: string
  template_name?: string
  params?: Record<string, any>
  logic: string
  is_active: boolean
  created_at: string
}

export interface Alert {
  id: string
  stock_id: string
  rule_id: string
  ts_code: string
  stock_name?: string
  template_name?: string
  trigger_date: string
  status: string
  plan_id?: string
  snapshot?: Record<string, any>
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

export interface DashboardData {
  pool_summary: {
    total_pools: number
    total_stocks: number
    monitoring_count: number
  }
  recent_alerts: Array<{
    id: string
    ts_code: string
    stock_name?: string
    trigger_date: string
    status: string
    plan_id?: string
  }>
  active_plans: Array<{
    id: string
    title?: string
    ts_code?: string
    stock_name?: string
    stock_count?: number
    status: string
    risk_level: number
    risk_reward_ratio?: number
  }>
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

// ---------- 买点雷达 ----------

export type BuySignalStatus = 'triggered' | 'approaching' | 'tracking' | 'invalidated'

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
}

export interface BuySignalScanResult {
  signals: BuySignal[]
  scan_time: string
  total: number
  triggered_count: number
  approaching_count: number
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
