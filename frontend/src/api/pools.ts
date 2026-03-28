import client from './client'
import type { Pool, WatchStock } from '../types'

export const listPools = () => client.get<Pool[]>('/pools')
export const reorderPools = (poolIds: string[]) =>
  client.put('/pools/reorder', { pool_ids: poolIds })

export interface AllStockItem {
  ts_code: string
  stock_name?: string
  pool_id: string
  pool_name: string
}
export const getAllStocks = (keyword?: string) =>
  client.get<AllStockItem[]>('/pools/all-stocks', { params: keyword ? { keyword } : {} })
export const createPool = (data: { name: string; description?: string }) => client.post<Pool>('/pools', data)
export const getPool = (id: string) => client.get<Pool>(`/pools/${id}`)
export const updatePool = (id: string, data: Partial<Pool>) => client.put<Pool>(`/pools/${id}`, data)
export const deletePool = (id: string) => client.delete(`/pools/${id}`)

export interface ListStocksParams {
  keyword?: string
  monitor_status?: string
  limit_up_date_from?: string
  limit_up_date_to?: string
  page?: number
  size?: number
  sort_by?: 'created_at' | 'limit_up_date'
  order?: 'asc' | 'desc'
}

export interface ListStocksResult {
  items: WatchStock[]
  total: number
}

export const listStocks = (
  poolId: string,
  params?: ListStocksParams
) => client.get<ListStocksResult>(`/pools/${poolId}/stocks`, { params })
export const addStock = (poolId: string, data: { ts_code: string; added_price?: number; note?: string }) =>
  client.post<WatchStock>(`/pools/${poolId}/stocks`, data)
export const updateStock = (poolId: string, stockId: string, data: { note?: string; monitor_status?: string; added_price?: number; pinned?: boolean }) =>
  client.put<WatchStock>(`/pools/${poolId}/stocks/${stockId}`, data)
export const deleteStock = (poolId: string, stockId: string) =>
  client.delete(`/pools/${poolId}/stocks/${stockId}`)
export const importCSV = (poolId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return client.post(`/pools/${poolId}/stocks/import`, form)
}

export interface BatchAddResult {
  added: number
  skipped: number
  errors: string[]
}

export const batchAddStocks = (
  poolId: string,
  data: { ts_codes: string[]; added_price?: number; note?: string }
) => client.post<BatchAddResult>(`/pools/${poolId}/stocks/batch`, data)

export const quickCreatePool = (data: {
  name: string
  ts_codes: string[]
  description?: string
}) => client.post<Pool>('/pools/quick-create', data)

/** 买点雷达「核心关注」池内股票代码 */
export const getCoreWatchCodes = () =>
  client.get<{ pool_id: string | null; ts_codes: string[] }>('/pools/core-watch/codes')

export const toggleCoreWatch = (data: {
  ts_code: string
  starred: boolean
  limit_up_date?: string | null
}) =>
  client.post<{ starred: boolean; pool_id: string | null; stock_id?: string; ts_code: string }>(
    '/pools/core-watch/toggle',
    data
  )
