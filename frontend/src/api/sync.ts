import client from './client'
import type { TaskStatus } from '../types'

export const syncPool = (poolId: string) => client.post<{ task_id: string }>(`/sync/pool/${poolId}`)
export const syncStock = (tsCode: string) => client.post<{ task_id: string }>(`/sync/stock/${tsCode}`)
export const syncFullMarket = (days?: number) =>
  client.post<{ task_id: string }>('/sync/full-market', null, { params: { days } })
export const getTaskStatus = (taskId: string) => client.get<TaskStatus>(`/sync/status/${taskId}`)

export interface RecentTask {
  id: string
  task_id: string
  type: string
  status: string
  message: string
  created_at: string
  updated_at: string
  result?: unknown
  source: 'background' | 'sync_log' | 'scheduler'
  link?: string
}
export const getRecentTasks = (size = 50) => client.get<{ items: RecentTask[] }>('/sync/tasks/recent', { params: { size } })
