import client from './client'
import type { TradePlan, TradeDetail, Pagination } from '../types'

export const listPlans = (params?: { status?: string; plan_type?: string; page?: number; size?: number }) =>
  client.get<Pagination<TradePlan>>('/plans', { params })
export const createPlan = (data: any) => client.post<TradePlan>('/plans', data)
export const getPlan = (id: string) => client.get<TradePlan>(`/plans/${id}`)
export const updatePlan = (id: string, data: any) => client.put<TradePlan>(`/plans/${id}`, data)
export const deletePlan = (id: string) => client.delete(`/plans/${id}`)
export const submitReview = (id: string, data: { review_summary: string; lessons_learned?: string }) =>
  client.put<TradePlan>(`/plans/${id}/review`, data)

export const listDetails = (planId: string) => client.get<TradeDetail[]>(`/plans/${planId}/details`)
export const createDetail = (planId: string, data: any) => client.post<TradeDetail>(`/plans/${planId}/details`, data)
export const updateDetail = (id: string, data: any) => client.put<TradeDetail>(`/details/${id}`, data)
export const deleteDetail = (id: string) => client.delete(`/details/${id}`)
