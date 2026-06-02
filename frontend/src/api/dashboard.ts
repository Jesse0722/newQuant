import client from './client'
import type { DashboardData } from '../types'
import type { AxiosResponse } from 'axios'

const DASHBOARD_CACHE_TTL_MS = 60 * 60 * 1000

type DashboardParams = { trade_date?: string }
type DashboardOptions = { forceRefresh?: boolean }
type CachedDashboard = {
  cachedAt: number
  data: DashboardData
}

function getCacheKey(params?: DashboardParams) {
  return `newQuant:dashboard:${params?.trade_date ?? 'default'}`
}

function readDashboardCache(cacheKey: string): DashboardData | null {
  try {
    const raw = localStorage.getItem(cacheKey)
    if (!raw) return null
    const cached = JSON.parse(raw) as Partial<CachedDashboard>
    if (!cached.cachedAt || !cached.data) return null
    if (Date.now() - cached.cachedAt > DASHBOARD_CACHE_TTL_MS) {
      localStorage.removeItem(cacheKey)
      return null
    }
    return cached.data
  } catch {
    return null
  }
}

function writeDashboardCache(cacheKey: string, data: DashboardData) {
  try {
    localStorage.setItem(cacheKey, JSON.stringify({ cachedAt: Date.now(), data }))
  } catch {
    // Cache writes are best-effort; dashboard loading should not depend on storage availability.
  }
}

export const getDashboard = async (
  params?: DashboardParams,
  options?: DashboardOptions,
): Promise<AxiosResponse<DashboardData>> => {
  const cacheKey = getCacheKey(params)
  if (!options?.forceRefresh) {
    const cached = readDashboardCache(cacheKey)
    if (cached) {
      return { data: cached } as AxiosResponse<DashboardData>
    }
  }

  const response = await client.get<DashboardData>('/dashboard', { params })
  writeDashboardCache(cacheKey, response.data)
  return response
}
