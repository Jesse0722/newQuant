import client from './client'
import type { TaskStatus } from '../types'

export const syncPool = (poolId: string) => client.post<{ task_id: string }>(`/sync/pool/${poolId}`)
export const syncStock = (tsCode: string) => client.post<{ task_id: string }>(`/sync/stock/${tsCode}`)
export const syncFullMarket = (days?: number) =>
  client.post<{ task_id: string }>('/sync/full-market', null, { params: { days } })
export const getTaskStatus = (taskId: string) => client.get<TaskStatus>(`/sync/status/${taskId}`)
