export interface Pool {
  id: string
  name: string
  description?: string
  default_monitor_rule?: Record<string, any>
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
  trade_date?: string
  source: string
  monitor_status: string
  pinned: boolean
  note?: string
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
  plan_type: string
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
  plan_id: string
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
  ts_code: string
  stock_name?: string
  plan_type: string
  risk_level: number
  status: string
  trigger_strategy?: string
  alert_id?: string
  event_note?: string
  action_suggestion?: string
  planned_buy_price?: number
  target_price?: number
  stop_loss_price?: number
  risk_reward_ratio?: number
  position_plan?: string
  actual_pnl?: number
  review_summary?: string
  lessons_learned?: string
  note?: string
  created_at: string
  updated_at: string
  details?: TradeDetail[]
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
  }>
  active_plans: Array<{
    id: string
    ts_code: string
    stock_name?: string
    plan_type: string
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
}

export interface Pagination<T> {
  items: T[]
  total: number
}
