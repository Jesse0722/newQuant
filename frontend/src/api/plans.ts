import client from './client'
import type { TradePlan, TradeDetail, Pagination } from '../types'

export const listPlans = (params?: { status?: string; page?: number; size?: number }) =>
  client.get<Pagination<TradePlan>>('/plans', { params })
export const createPlan = (data: {
  title: string
  stocks: Array<{
    ts_code: string
    risk_level?: number
    trigger_strategy?: string
    planned_buy_price?: number
    target_price?: number
    stop_loss_price?: number
    position_plan?: number | string
    note?: string
  }>
  alert_id?: string
  note?: string
}) => client.post<TradePlan>('/plans', data)
export const getPlan = (id: string) => client.get<TradePlan>(`/plans/${id}`)
export const updatePlan = (id: string, data: any) => client.put<TradePlan>(`/plans/${id}`, data)
export const deletePlan = (id: string) => client.delete(`/plans/${id}`)
export const submitReview = (id: string, data: { review_summary: string; lessons_learned?: string }) =>
  client.put<TradePlan>(`/plans/${id}/review`, data)

export const updateDetail = (id: string, data: any) => client.put<TradeDetail>(`/details/${id}`, data)
export const deleteDetail = (id: string) => client.delete(`/details/${id}`)
