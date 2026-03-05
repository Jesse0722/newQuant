import client from './client'
import type { StockChartData, StockAlertItem, TradeDetail } from '../types'

export const getStockChart = (tsCode: string, period = 120) =>
  client.get<StockChartData>(`/stocks/${tsCode}/chart`, { params: { period } })

export const getStockAlerts = (tsCode: string) =>
  client.get<StockAlertItem[]>(`/stocks/${tsCode}/alerts`)

export const getStockDetails = (tsCode: string) =>
  client.get<TradeDetail[]>(`/stocks/${tsCode}/details`)

export const createStockDetail = (tsCode: string, data: { trade_date: string; trade_time?: string; direction: string; price: number; quantity: number; commission?: number; exec_note?: string }) =>
  client.post<TradeDetail>(`/stocks/${tsCode}/details`, data)
