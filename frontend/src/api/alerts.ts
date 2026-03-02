import client from './client'
import type { Alert, Pagination } from '../types'

export const listAlerts = (params?: { status?: string; page?: number; size?: number }) =>
  client.get<Pagination<Alert>>('/alerts', { params })
export const getAlert = (id: string) => client.get<Alert>(`/alerts/${id}`)
export const updateAlert = (id: string, data: { status: string }) => client.put<Alert>(`/alerts/${id}`, data)
export const createPlanFromAlert = (id: string) => client.post(`/alerts/${id}/create-plan`)
