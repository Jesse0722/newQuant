import client from './client'
import type { Alert, Pagination } from '../types'

export const listAlerts = (params?: {
  status?: string
  page?: number
  size?: number
  source?: string
  ts_code?: string
}) => client.get<Pagination<Alert>>('/alerts', { params })

export const getAlertsPendingCount = (params?: { source?: string }) =>
  client.get<{ count: number }>('/alerts/pending-count', { params })

export const batchDismissPendingAlerts = (params?: { source?: string }) =>
  client.post<{ count: number }>('/alerts/batch-dismiss-pending', undefined, { params })

export const batchDeleteDismissedAlerts = (params?: { source?: string }) =>
  client.post<{ count: number }>('/alerts/batch-delete-dismissed', undefined, { params })

export const getAlert = (id: string) => client.get<Alert>(`/alerts/${id}`)
export const updateAlert = (id: string, data: { status: string }) => client.put<Alert>(`/alerts/${id}`, data)
export const createPlanFromAlert = (id: string) => client.post(`/alerts/${id}/create-plan`)
