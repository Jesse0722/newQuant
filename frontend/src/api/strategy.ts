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
  best_sector?: {
    sector_code?: string
    sector_name?: string
    sector_type?: string
    sector_return_20d?: number | null
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
  float_market_cap_yi?: number | null
  avg_amount_20d_yi?: number | null
}

export const runMainWaveScreen = (data: MainWaveScreenParams) =>
  client.post<{ task_id: string }>('/strategy/main-wave-screen', data)

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
