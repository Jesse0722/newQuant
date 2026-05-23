import type { StockAiAnalysisRecord } from '../types'

export type AppNotificationStatus = 'running' | 'success' | 'error'
export type AppNotificationKind = 'stock_ai_analysis' | 'ai_screen' | 'sync_task' | 'buy_alert'

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
  }
}

const STORAGE_KEY = 'newQuant.notificationCenter.items'
const CHANGE_EVENT = 'notification-center:changed'

const readStored = (): AppNotification[] => {
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
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, 80)))
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: items }))
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
  writeStored(readStored().filter((item) => !item.read))
}
