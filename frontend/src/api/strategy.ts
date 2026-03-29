import client from './client'
import type { AiAnalysisResult } from '../types'

export interface ScreenTemplate {
  id: string
  name: string
  default_params: Record<string, any>
}

export interface ScreenCondition {
  template_id: string
  params: Record<string, any>
}

export interface ScreenResult {
  task_id: string
  status: string
  progress: number
  message: string
  ts_codes: string[]
  stock_names: Record<string, string>
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
} from '../types'

export const getBuyStrategies = () =>
  client.get<BuyStrategy[]>('/strategy/buy-strategies')

export const scanBuySignals = (poolId?: string, strategyId: string = 'two_phase') =>
  client.post<BuySignalScanResult>('/strategy/scan-buy-signals', {
    pool_id: poolId || null,
    strategy_id: strategyId,
  })

export const getStockChartWithMarks = (tsCode: string, period: number, limitUpDate?: string) =>
  client.get<StockChartDataWithMarks>(`/stocks/${tsCode}/chart`, {
    params: { period, mark_signals: true, limit_up_date: limitUpDate || undefined },
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
