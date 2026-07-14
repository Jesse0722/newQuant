import client from './client'
import type { AiAnalysisResult, JsonObject } from '../types'

export interface ScreenTemplate {
  id: string
  name: string
  default_params: JsonObject
}

export interface ScreenCondition {
  template_id: string
  params: JsonObject
}

export interface ScreenResult {
  task_id: string
  status: string
  progress: number
  message: string
  ts_codes: string[]
  stock_names: Record<string, string>
  items?: MainWaveScreenResultItem[]
  total: number
  performance?: {
    total_elapsed_ms?: number
    total_codes?: number
    hard_filtered?: number
    score_filtered?: number
    matched?: number
    preload?: {
      total_elapsed_ms?: number
      quotes?: { enabled?: boolean; row_count?: number; elapsed_ms?: number; skipped_reason?: string | null }
      sector_quotes?: { enabled?: boolean; row_count?: number; elapsed_ms?: number; skipped_reason?: string | null }
      market_proxy?: { enabled?: boolean; row_count?: number; elapsed_ms?: number; skipped_reason?: string | null }
    }
    hard_filter_elapsed_ms?: number
    analyze_elapsed_ms?: number
    score_filter_elapsed_ms?: number
    sort_elapsed_ms?: number
  }
}

export const getScreenTemplates = () =>
  client.get<ScreenTemplate[]>('/strategy/templates')

export const runIndicatorScreen = (data: {
  scope: string
  conditions: ScreenCondition[]
  logic?: string
}) => client.post<{ task_id: string }>('/strategy/screen', data)

export const runAiScreen = (data: { description: string; scope?: string }) =>
  client.post<{ task_id: string }>('/strategy/ai-screen', data)

export const aiAnalyzeStock = (data: { ts_code: string; stock_id: string }) =>
  client.post<{
    stock_id: string
    ts_code: string
    analysis: AiAnalysisResult
    ai_analyzed_at: string
    raw: string
  }>('/strategy/ai-analyze', data)

export const getScreenResult = (taskId: string) =>
  client.get<ScreenResult>(`/strategy/result/${taskId}`)

export const getLimitUpTemplates = () =>
  client.get<ScreenTemplate[]>('/strategy/limit-up-templates')

export const runLimitUpBuyPointScreen = (data: {
  trade_date_from: string
  trade_date_to: string
  conditions: ScreenCondition[]
  logic?: string
}) => client.post<{ task_id: string }>('/strategy/limit-up-buy-point', data)

export interface MainWaveScreenParams {
  scope: string
  sector_codes?: string[]
  sector_logic?: 'any' | 'all'
  min_score?: number
  statuses?: string[]
  require_sector_resonance?: boolean
  exclude_effective_break?: boolean
  exclude_st?: boolean
  min_data_days?: number
  min_price?: number | null
  max_price?: number | null
  min_float_market_cap_yi?: number | null
  min_avg_amount_20d_yi?: number | null
  max_return_60d?: number | null
  max_ma20_distance_pct?: number | null
  min_sector_return_20d?: number | null
  min_relative_strength_20d?: number | null
  entry_stages?: string[]
  min_entry_score?: number | null
  exclude_overheat?: boolean
}

export interface MainWaveScreenResultItem {
  ts_code: string
  stock_name: string
  total_score?: number
  status?: string
  trend_score?: number
  structure_score?: number
  pullback_repair_score?: number
  sector_resonance_score?: number
  market_relative_score?: number
  best_sector?: {
    sector_code?: string
    sector_name?: string
    sector_type?: string
    sector_return_20d?: number | null
    relative_strength_20d?: number | null
  } | null
  market_proxy?: {
    group?: string
    label?: string
    status?: string
    source?: string
    latest_trade_date?: string
    member_count?: number
    latest_pct_chg?: number | null
    stock_latest_pct_chg?: number | null
    latest_relative_pct_chg?: number | null
    return_20d?: number | null
    stock_return_20d?: number | null
    relative_strength_20d?: number | null
  } | null
  return_20d?: number | null
  return_60d?: number | null
  relative_strength_20d?: number | null
  ma20_state?: {
    state?: string
    distance_pct?: number | null
    break_days?: number
  } | null
  entry_score?: number | null
  entry_stage?: string | null
  entry_label?: string | null
  entry_reasons?: string[]
  entry_risks?: string[]
  sector_data_status?: string | null
  sector_data_warning?: string | null
  overheat_reasons?: string[]
  data_quality?: {
    score?: number
    warnings?: string[]
  } | null
  float_market_cap_yi?: number | null
  avg_amount_20d_yi?: number | null
}

export const runMainWaveScreen = (data: MainWaveScreenParams) =>
  client.post<{ task_id: string }>('/strategy/main-wave-screen', data)

export interface MainWaveBacktestSignal {
  ts_code: string
  stock_name?: string
  trigger_date: string
  entry_price: number
  total_score: number
  status?: string
  entry_stage?: string
  entry_score?: number
  sector_score?: number
  market_relative_score?: number
  return_1d?: number | null
  return_3d?: number | null
  return_5d?: number | null
  return_10d?: number | null
}

export interface MainWaveBacktestGroupSummary {
  group: string
  total_signals: number
  covered_1d?: number
  avg_return_1d?: number
  win_rate_1d?: number
  covered_3d?: number
  avg_return_3d?: number
  win_rate_3d?: number
  covered_5d?: number
  avg_return_5d?: number
  win_rate_5d?: number
  covered_10d?: number
  avg_return_10d?: number
  win_rate_10d?: number
}

export interface MainWaveBacktestRecommendation {
  type: string
  level: 'observe' | 'risk' | string
  message: string
  evidence?: string
}

export interface MainWaveBacktestResult {
  trade_date_from: string
  trade_date_to: string
  scope: string
  stock_count: number
  date_count: number
  holding_days: number[]
  total_signals: number
  covered_1d?: number
  avg_return_1d?: number
  win_rate_1d?: number
  covered_3d?: number
  avg_return_3d?: number
  win_rate_3d?: number
  covered_5d?: number
  avg_return_5d?: number
  win_rate_5d?: number
  covered_10d?: number
  avg_return_10d?: number
  win_rate_10d?: number
  quality_notes?: string[]
  recommendations?: MainWaveBacktestRecommendation[]
  performance?: {
    quote_preload?: {
      enabled?: boolean
      loaded_codes?: number
      row_count?: number
      start_date?: string
      end_date?: string
      skipped_reason?: string | null
    }
    market_proxy_preload?: {
      enabled?: boolean
      groups?: string[]
      row_count?: number
      start_date?: string
      end_date?: string
      skipped_reason?: string | null
    }
  }
  stage_summary: MainWaveBacktestGroupSummary[]
  status_summary: MainWaveBacktestGroupSummary[]
  score_summary: MainWaveBacktestGroupSummary[]
  signals: MainWaveBacktestSignal[]
}

export interface MainWaveBacktestTask {
  task_id: string
  type: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  result?: MainWaveBacktestResult | null
  created_at?: string
}

export const submitMainWaveBacktest = (data: MainWaveScreenParams & {
  trade_date_from: string
  trade_date_to: string
  holding_days?: number[]
  max_signals_per_day?: number
  cooldown_days?: number
}) => client.post<{ task_id: string }>('/strategy/main-wave-backtest', data)

export const getMainWaveBacktestResult = (taskId: string) =>
  client.get<MainWaveBacktestTask>(`/strategy/main-wave-backtest/${taskId}`)

export interface BacktestSignal {
  ts_code: string
  trigger_date: string
  next_day_pct: number
}

export interface BacktestResult {
  signals: BacktestSignal[]
  avg_pct: number
  win_rate: number
  total_signals: number
}

export const runBacktest = (data: {
  trade_date_from: string
  trade_date_to: string
  conditions: ScreenCondition[]
  logic?: string
}) => client.post<BacktestResult>('/strategy/backtest', data)

export interface LimitUpCollectResult {
  pool_id: string
  pool_name: string
  dates_processed: string[]
  added: number
  updated: number
  skipped: number
  errors: string[]
}

export const collectLimitUp = (params?: { trade_date?: string; window_days?: number }) =>
  client.post<LimitUpCollectResult>('/strategy/limit-up/collect', null, { params })

// ---------- 买点雷达 ----------

import type {
  BuySignalScanResult,
  StockChartDataWithMarks,
  BuyStrategy,
  StrategyBacktestTaskStatus,
  IntradayScanConfigItem,
} from '../types'

export const getBuyStrategies = () =>
  client.get<BuyStrategy[]>('/strategy/buy-strategies')

export const scanBuySignals = (
  poolId?: string,
  strategyId: string = 'two_phase',
  minConfirmHits: number = 2,
  limitUpDateFrom?: string,
  limitUpDateTo?: string,
) =>
  client.post<BuySignalScanResult>('/strategy/scan-buy-signals', {
    pool_id: poolId || null,
    strategy_id: strategyId,
    min_confirm_hits: minConfirmHits,
    limit_up_date_from: limitUpDateFrom || null,
    limit_up_date_to: limitUpDateTo || null,
  })

export interface BuySignalScanTaskStatus {
  task_id: string
  type: string
  status: 'running' | 'completed' | 'failed'
  progress: number
  message: string
  result?: BuySignalScanResult | null
  created_at?: string
}

export const submitBuySignalScanTask = (
  poolId?: string,
  strategyId: string = 'two_phase',
  minConfirmHits: number = 2,
  limitUpDateFrom?: string,
  limitUpDateTo?: string,
) =>
  client.post<{ task_id: string }>('/strategy/scan-buy-signals-task', {
    pool_id: poolId || null,
    strategy_id: strategyId,
    min_confirm_hits: minConfirmHits,
    limit_up_date_from: limitUpDateFrom || null,
    limit_up_date_to: limitUpDateTo || null,
  })

export const getBuySignalScanTask = (taskId: string) =>
  client.get<BuySignalScanTaskStatus>(`/strategy/scan-buy-signals-task/${taskId}`)

export const listIntradayScanConfig = (poolId?: string) =>
  client.get<IntradayScanConfigItem[]>('/strategy/intraday-config', {
    params: poolId ? { pool_id: poolId } : undefined,
  })

export const upsertIntradayScanConfig = (data: {
  pool_id: string
  strategy_id: string
  enabled?: boolean
  interval_minutes?: number
  min_confirm_hits?: number
}) => client.put<IntradayScanConfigItem>('/strategy/intraday-config', data)

export const getStockChartWithMarks = (tsCode: string, period: number, limitUpDate?: string) =>
  client.get<StockChartDataWithMarks>(`/stocks/${tsCode}/chart`, {
    params: { period, mark_signals: true, limit_up_date: limitUpDate || undefined },
  })

export const getStockChartPreview = (tsCode: string, period: number) =>
  client.get<StockChartDataWithMarks>(`/stocks/${tsCode}/chart`, {
    params: { period, mark_signals: false, auto_sync_latest: false },
  })

export const submitStrategyBacktest = (data: {
  strategy_id: string
  trade_date_from: string
  trade_date_to: string
  pool_id?: string | null
}) => client.post<{ task_id: string }>('/strategy/strategy-backtest', data)

export const getStrategyBacktestResult = (taskId: string) =>
  client.get<StrategyBacktestTaskStatus>(`/strategy/strategy-backtest/${taskId}`)


export const getTradingSession = () =>
  client.get<{ in_session: boolean }>('/market/trading-session')
