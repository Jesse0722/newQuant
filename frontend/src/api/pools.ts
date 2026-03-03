import client from './client'
import type { Pool, WatchStock } from '../types'

export const listPools = () => client.get<Pool[]>('/pools')
export const createPool = (data: { name: string; description?: string }) => client.post<Pool>('/pools', data)
export const getPool = (id: string) => client.get<Pool>(`/pools/${id}`)
export const updatePool = (id: string, data: Partial<Pool>) => client.put<Pool>(`/pools/${id}`, data)
export const deletePool = (id: string) => client.delete(`/pools/${id}`)

export const listStocks = (poolId: string, params?: { keyword?: string; monitor_status?: string }) =>
  client.get<WatchStock[]>(`/pools/${poolId}/stocks`, { params })
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
