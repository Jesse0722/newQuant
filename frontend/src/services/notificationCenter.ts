import type { StockAiAnalysisRecord } from '../types'

export type AppNotificationStatus = 'running' | 'success' | 'error' | 'unknown'
export type AppNotificationKind = 'stock_ai_analysis' | 'ai_screen' | 'sync_task' | 'buy_alert' | 'screen' | 'buy_scan' | 'strategy_backtest' | 'main_wave_backtest' | 'sector_sync' | 'collection' | 'scheduled_task' | 'data_source'

export interface AppNotification {
  id: string
  kind: AppNotificationKind
  status: AppNotificationStatus
  title: string
  description: string
  createdAt: string
  updatedAt: string
  read: boolean
  taskId?: string
  link?: string
  meta?: {
    tsCode?: string
    stockName?: string
    watchStockId?: string
    mode?: 'fast' | 'deep'
    result?: StockAiAnalysisRecord | null
    taskResult?: unknown
    taskType?: string
    poolId?: string
    strategyId?: string
  }
}

const STORAGE_KEY = 'newQuant.notificationCenter.items'
const CHANGE_EVENT = 'notification-center:changed'
let sessionFallback: AppNotification[] | null = null

const readStored = (): AppNotification[] => {
  if (sessionFallback) return sessionFallback
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

const writeStored = (items: AppNotification[]) => {
  const retained = [...items.filter(item => item.status === 'running'), ...items.filter(item => item.status !== 'running').slice(0, 80)]
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(retained))
    sessionFallback = null
  } catch {
    // Storage quota or browser privacy settings must not turn a submitted task into an apparent failure.
    sessionFallback = retained
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: retained }))
}

export const getNotifications = () => readStored()

export const subscribeNotifications = (handler: (items: AppNotification[]) => void) => {
  const listener = () => handler(readStored())
  window.addEventListener(CHANGE_EVENT, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener)
    window.removeEventListener('storage', listener)
  }
}

export const upsertNotification = (next: AppNotification) => {
  const items = readStored()
  const index = items.findIndex((item) => item.id === next.id)
  const merged = index >= 0
    ? [
        { ...items[index], ...next, meta: { ...items[index].meta, ...next.meta } },
        ...items.slice(0, index),
        ...items.slice(index + 1),
      ]
    : [next, ...items]
  writeStored(merged)
  return merged[0]
}

export const markNotificationRead = (id: string) => {
  writeStored(readStored().map((item) => item.id === id ? { ...item, read: true } : item))
}

export const markAllNotificationsRead = () => {
  writeStored(readStored().map((item) => ({ ...item, read: true })))
}

export const clearReadNotifications = () => {
  writeStored(readStored().filter((item) => !item.read || item.status === 'running'))
}


export const beginTaskNotification = (kind: AppNotificationKind, title: string, taskId: string, link: string, meta?: AppNotification['meta']) => {
  const now = new Date().toISOString()
  return upsertNotification({ id: `${kind}:${taskId}`, kind, status: 'running', title,
    description: '任务已提交，可离开页面，完成后在此查看结果', createdAt: now, updatedAt: now,
    read: false, taskId, link, meta })
}

export const beginOperationNotification = (title: string, link: string, kind: AppNotificationKind = 'collection') => {
  const now = new Date().toISOString()
  return upsertNotification({ id: `${kind}:${typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`, kind, status: 'running', title,
    description: '处理中', createdAt: now, updatedAt: now, read: false, link })
}

export const finishOperationNotification = (item: AppNotification, status: 'success' | 'error', description: string, result?: unknown) => {
  const url = new URL(item.link || '/', window.location.origin)
  url.searchParams.set('notice', item.id)
  return upsertNotification({ ...item, status, description, link: `${url.pathname}${url.search}`, updatedAt: new Date().toISOString(), read: false,
    meta: { ...item.meta, taskResult: result } })
}
