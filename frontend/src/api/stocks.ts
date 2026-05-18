import client from './client'
import type { StockAiAnalysisRecord, StockChartData, StockAlertItem, TradeDetail } from '../types'
import type { DetailUpdateInput } from './plans'

export interface StockSearchItem {
  ts_code: string
  stock_name: string
}

export const searchStocks = (q: string, limit = 20) =>
  client.get<StockSearchItem[]>('/stocks/search', { params: { q, limit } })

export const getStockChart = (tsCode: string, period = 120) =>
  client.get<StockChartData>(`/stocks/${tsCode}/chart`, {
    params: { period, auto_sync_latest: true },
  })

export const getStockAlerts = (tsCode: string) =>
  client.get<StockAlertItem[]>(`/stocks/${tsCode}/alerts`)

export const getStockDetails = (tsCode: string) =>
  client.get<TradeDetail[]>(`/stocks/${tsCode}/details`)

export const createStockDetail = (tsCode: string, data: DetailUpdateInput) =>
  client.post<TradeDetail>(`/stocks/${tsCode}/details`, data)

export const getStockAiAnalysis = (tsCode: string) =>
  client.get<StockAiAnalysisRecord | { analysis: null }>(`/stocks/${tsCode}/ai-analysis`)

export const runStockAiAnalysis = (tsCode: string, data: {
  mode?: 'fast' | 'deep'
  scope?: string
  pool_id?: string | null
  watch_stock_id?: string | null
  force_refresh?: boolean
}) => client.post<StockAiAnalysisRecord>(`/stocks/${tsCode}/ai-analysis`, data)
