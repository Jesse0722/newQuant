import client from './client'
import type { DataSummary, SyncHistoryItem } from '../types'

export const getDataSummary = () => client.get<DataSummary>('/data/summary')
export const getSyncHistory = (taskType = 'full_market', limit = 5) =>
  client.get<SyncHistoryItem[]>('/data/sync-history', { params: { task_type: taskType, limit } })
