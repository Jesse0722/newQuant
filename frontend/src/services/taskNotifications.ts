import { getStockAiAnalysisTask } from '../api/stocks'
import { getTaskStatus, getRecentTasks } from '../api/sync'
import { getScreenResult, getBuySignalScanTask, getStrategyBacktestResult, getMainWaveBacktestResult } from '../api/strategy'
import { getMainWaveSectorBackfillTask } from '../api/market'
import { getNotifications, subscribeNotifications, upsertNotification, type AppNotification } from './notificationCenter'
import { pollTask, isTaskTerminal } from './taskPolling'

type QueryResult = { status: string; message?: string; result?: unknown }
const queryNotification = async (item: AppNotification): Promise<QueryResult> => {
  const id = item.taskId!
  switch (item.kind) {
    case 'stock_ai_analysis': return (await getStockAiAnalysisTask(id)).data
    case 'screen':
    case 'ai_screen': { const value = (await getScreenResult(id)).data; return { ...value, result: value } }
    case 'sync_task': return (await getTaskStatus(id)).data
    case 'buy_scan': return (await getBuySignalScanTask(id)).data
    case 'strategy_backtest': return (await getStrategyBacktestResult(id)).data
    case 'main_wave_backtest': return (await getMainWaveBacktestResult(id)).data
    case 'sector_sync': return (await getMainWaveSectorBackfillTask(id)).data
    default: throw new Error('暂未提供此任务的状态接口')
  }
}

export function startTaskNotifications(onComplete: (item: AppNotification) => void) {
  // Request-bound operations have no durable task id; a reload cannot prove their server outcome.
  for (const item of getNotifications()) if (item.status === 'running' && !item.taskId && item.kind !== 'buy_alert') {
    upsertNotification({ ...item, status: 'unknown', description: '页面已重新载入，执行结果尚未确认，请查看来源记录', read: false, updatedAt: new Date().toISOString() })
  }
  const controllers = new Map<string, () => void>()
  const reconcile = () => {
    const running = getNotifications().filter(item => item.status === 'running' && item.taskId)
    const ids = new Set(running.map(item => item.id))
    for (const [id, stop] of controllers) if (!ids.has(id)) { stop(); controllers.delete(id) }
    for (const item of running) {
      if (controllers.has(item.id)) continue
      const stop = pollTask({
        query: () => queryNotification(item), intervalMs: 3000,
        onUpdate: value => {
          const current = getNotifications().find(next => next.id === item.id)
          if (!current || current.status !== 'running') return
          if (!isTaskTerminal(value.status)) {
            upsertNotification({ ...current, description: value.message || '后台处理中', updatedAt: new Date().toISOString() })
            return
          }
          const next = upsertNotification({ ...current,
            status: value.status === 'completed' ? 'success' : 'error',
            description: value.message || (value.status === 'completed' ? '已完成，点击查看结果' : '任务失败，点击查看详情'),
            read: false, updatedAt: new Date().toISOString(),
            meta: { ...current.meta, taskResult: value.result,
              ...(item.kind === 'stock_ai_analysis' ? { result: value.result as NonNullable<AppNotification['meta']>['result'] } : {}) },
          })
          onComplete(next)
        },
        onRetry: () => {
          const current = getNotifications().find(next => next.id === item.id)
          if (current?.status === 'running') upsertNotification({ ...current,
            description: '状态暂时不可用，正在重试；后台任务可能仍在执行', updatedAt: new Date().toISOString() })
        },
      })
      controllers.set(item.id, stop)
    }
  }
  const unsubscribe = subscribeNotifications(reconcile)
  reconcile()
  return () => { unsubscribe(); controllers.forEach(stop => stop()); controllers.clear() }
}

/** Durable task feed includes scheduled jobs and results produced while this browser was closed. */
export function startSyncHistoryNotifications() {
  const storageKey = 'newQuant.notificationCenter.serverVersions'
  let versions: Record<string, string> = {}
  try { versions = JSON.parse(localStorage.getItem(storageKey) || '{}') } catch { /* unavailable cache is safe */ }
  return pollTask({
    intervalMs: 30000,
    query: async () => ({ status: 'running', items: (await getRecentTasks()).data.items }),
    onUpdate: ({ items }) => {
      for (const row of items) {
        if (!isTaskTerminal(row.status) && row.status !== 'skipped') continue
        if (versions[row.id] === row.updated_at) continue
        versions[row.id] = row.updated_at
        const existing = getNotifications().find(item => item.taskId === row.task_id || item.id === `server-task:${row.id}`)
        const failed = ['failed', 'interrupted', 'cancelled'].includes(row.status)
        const next = { ...existing,
          id: existing?.id || `server-task:${row.id}`, kind: existing?.kind || 'scheduled_task' as const,
          status: failed ? 'error' as const : 'success' as const,
          title: existing?.title || `${row.type} ${failed ? '执行失败或中断' : row.status === 'skipped' ? '已跳过' : '执行完成'}`,
          description: row.message || (failed ? '任务失败，点击查看详情' : '点击查看执行结果'),
          createdAt: row.created_at, updatedAt: row.updated_at,
          read: existing?.status === (failed ? 'error' : 'success') ? existing.read : false,
          link: existing?.link || row.link || '/data', meta: { ...existing?.meta, taskType: row.type, taskResult: row.result, ...(existing?.kind === 'stock_ai_analysis' ? { result: row.result as NonNullable<AppNotification['meta']>['result'] } : {}) },
        }
        upsertNotification(next)
      }
      versions = Object.fromEntries(Object.entries(versions).slice(-500))
      try { localStorage.setItem(storageKey, JSON.stringify(versions)) } catch { /* keep session deduplication */ }
    },
  })
}
