import client from './client'
import type { DataSummary, SyncHistoryItem, SyncOverview } from '../types'

export const getDataSummary = () => client.get<DataSummary>('/data/summary')

export interface TushareCheckResult {
  token_configured: boolean
  token_length: number
  proxy_configured: boolean
  proxy_url: string
  api_test: string
  rows_returned?: number
}

export const checkTushare = () => client.get<TushareCheckResult>('/data/tushare-check')
export const getSyncHistory = (taskType = 'all', limit = 20) =>
  client.get<SyncHistoryItem[]>('/data/sync-history', { params: { task_type: taskType, limit } })

export const getSyncOverview = (days = 7) =>
  client.get<SyncOverview>('/data/sync-overview', { params: { days } })
