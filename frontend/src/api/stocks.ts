import client from './client'
import type { StockChartData, StockAlertItem, TradeDetail } from '../types'
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
