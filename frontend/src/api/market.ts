import client from './client'

export interface MainWaveAnalysis {
  ts_code: string
  name: string
  industry?: string | null
  trade_date?: string
  status: string
  total_score: number
  message?: string
  scores?: {
    trend: number
    structure: number
    pullback_repair: number
    sector_resonance: number
  }
  ma20_state?: {
    state: string
    break_days: number
    distance_pct?: number | null
  }
  metrics?: {
    latest_close?: number | null
    return_20d?: number | null
    return_60d?: number | null
    breakout_date?: string
    breakout_price?: number
    above_short_ma_days_10?: number
    max_drawdown_10d?: number
    best_sector?: {
      sector_code: string
      sector_name: string
      sector_type: string
      sector_return_20d?: number | null
      stock_return_20d?: number | null
      relative_strength_20d?: number | null
      sync_ratio_20d?: number | null
      stock_drawdown_20d?: number | null
      sector_drawdown_20d?: number | null
    } | null
    sector_count?: number
  }
  reasons?: {
    trend?: string[]
    structure?: string[]
    pullback_repair?: string[]
    sector_resonance?: string[]
  }
}

export const analyzeMainWaveStock = (tsCode: string) =>
  client.get<MainWaveAnalysis>(`/market/stocks/${tsCode}/main-wave`)

export const scanMainWave = (params?: {
  pool_id?: string
  min_score?: number
  status?: string[]
}) => client.get<{
  total: number
  items: MainWaveAnalysis[]
  summary: Record<string, number>
}>('/market/main-wave/scan', { params })

export const syncSectors = (data: {
  sector_types?: Array<'concept' | 'industry'>
  sync_constituents?: boolean
  sync_quotes?: boolean
  days?: number
  limit?: number | null
}) => client.post<{
  source: string
  sector_types: string[]
  sector_count: number
  constituent_count: number
  quote_count: number
  failed: string[]
}>('/market/sectors/sync', data)

export interface MainWaveSectorBackfillItem {
  sector_code: string
  sector_name: string
  sector_type: string
  source: string
  status: string
  target_days?: number | null
  quote_count: number
  first_trade_date?: string | null
  last_trade_date?: string | null
  attempts: number
  last_error?: string | null
  next_retry_at?: string | null
  last_success_at?: string | null
  stocks: string[]
}

export interface MainWaveSectorBackfillStatus {
  pool_id?: string | null
  pool_name?: string | null
  stock_count: number
  concept_count: number
  completed_count: number
  partial_count: number
  cooldown_count: number
  missing_count: number
  items: MainWaveSectorBackfillItem[]
}

export interface MainWaveSectorBackfillTask {
  task_id: string
  type: string
  status: string
  progress: number
  message: string
  result?: {
    quote_count?: number
    map_count?: number
    skipped?: number
    failed?: Array<{
      sector_code: string
      sector_name: string
      error: string
      next_retry_at?: string | null
    }>
  } | null
  created_at: string
}

export const getMainWaveSectorBackfillStatus = (params?: {
  pool_id?: string
  days?: number
}) => client.get<MainWaveSectorBackfillStatus>('/market/main-wave/sectors/backfill/status', { params })

export const startMainWaveSectorBackfill = (data: {
  pool_id?: string
  days?: number
  mode?: 'backfill' | 'incremental'
  force?: boolean
}) => client.post<{ task_id: string }>('/market/main-wave/sectors/backfill', data)

export const getMainWaveSectorBackfillTask = (taskId: string) =>
  client.get<MainWaveSectorBackfillTask>(`/market/main-wave/sectors/backfill/tasks/${taskId}`)
