import client from './client'
import type { StockChartData, StockAlertItem, StockPlanItem } from '../types'

export const getStockChart = (tsCode: string, period = 120) =>
  client.get<StockChartData>(`/stocks/${tsCode}/chart`, { params: { period } })

export const getStockAlerts = (tsCode: string) =>
  client.get<StockAlertItem[]>(`/stocks/${tsCode}/alerts`)

export const getStockPlans = (tsCode: string) =>
  client.get<StockPlanItem[]>(`/stocks/${tsCode}/plans`)
