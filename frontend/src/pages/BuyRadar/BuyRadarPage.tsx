import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { Button, Segmented, Spin, message, Badge, Space, Select, Tooltip, Modal, DatePicker, Progress, Table, Row, Col, Statistic, Tag } from 'antd'
import { ScanOutlined, BarChartOutlined, BellOutlined, ClearOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import {
  getBuyStrategies,
  getBuySignalScanTask,
  submitBuySignalScanTask,
  submitStrategyBacktest,
  getStrategyBacktestResult,
} from '../../api/strategy'
import { getAlertsPendingCount } from '../../api/alerts'
import { cleanupLimitUpPool, listPools, getCoreWatchCodes, toggleCoreWatch } from '../../api/pools'
import type { LimitUpPoolCleanupResult } from '../../api/pools'
import SignalList from './SignalList'
import SignalDetail from './SignalDetail'
import Alerts from '../Alerts'
import type {
  BuySignal,
  BuySignalStatus,
  BuySignalScanResult,
  BuyStrategy,
  Pool,
  StrategyBacktestResult,
} from '../../types'

type FilterStatus = 'all' | BuySignalStatus

const ALL_STRATEGY_ID = 'all'
const BUY_RADAR_RESULT_STORAGE_KEY = 'newQuant.buyRadar.lastScanResult.v1'
const CLEANUP_REASON_LABELS: Record<string, string> = {
  no_recent_limit_up: '区间内无涨停',
}

type StoredBuyRadarResult = {
  savedAt: string
  activePoolId: string
  activeStrategyId: string
  limitUpRange: [string, string] | null
  scanResultsByStrategy: Record<string, BuySignalScanResult>
  selectedTsCode?: string | null
}

const loadStoredBuyRadarResult = (): StoredBuyRadarResult | null => {
  try {
    const raw = window.localStorage.getItem(BUY_RADAR_RESULT_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<StoredBuyRadarResult>
    if (!parsed.activePoolId || !parsed.activeStrategyId || !parsed.scanResultsByStrategy) return null
    return {
      savedAt: parsed.savedAt || new Date().toISOString(),
      activePoolId: parsed.activePoolId,
      activeStrategyId: parsed.activeStrategyId,
      limitUpRange: Array.isArray(parsed.limitUpRange) && parsed.limitUpRange.length === 2
        ? parsed.limitUpRange
        : null,
      scanResultsByStrategy: parsed.scanResultsByStrategy,
      selectedTsCode: parsed.selectedTsCode || null,
    }
  } catch {
    return null
  }
}

const hasCachedBuyRadarSignals = (cached: StoredBuyRadarResult | null) =>
  Object.values(cached?.scanResultsByStrategy || {}).some((result) => result?.signals?.length)

const saveStoredBuyRadarResult = (payload: Omit<StoredBuyRadarResult, 'savedAt'>) => {
  try {
    window.localStorage.setItem(BUY_RADAR_RESULT_STORAGE_KEY, JSON.stringify({
      ...payload,
      savedAt: new Date().toISOString(),
    }))
  } catch {
    // 本地缓存不可用时不影响扫描结果展示。
  }
}

const BuyRadarPage: React.FC = () => {
  const cachedScanRef = useRef<StoredBuyRadarResult | null>(loadStoredBuyRadarResult())
  const restoredCacheRef = useRef(false)
  const cachedScan = cachedScanRef.current
  const [cachedSelectedTsCode, setCachedSelectedTsCode] = useState<string | null>(() => cachedScan?.selectedTsCode || null)
  const [pendingAlertCount, setPendingAlertCount] = useState(0)
  const [alertsOpen, setAlertsOpen] = useState(false)
  const [pools, setPools] = useState<Pool[]>([])
  const [activePoolId, setActivePoolId] = useState(() => cachedScan?.activePoolId || '')
  const [strategies, setStrategies] = useState<BuyStrategy[]>([])
  const [activeStrategyId, setActiveStrategyId] = useState(() => cachedScan?.activeStrategyId || ALL_STRATEGY_ID)
  const [scanResultsByStrategy, setScanResultsByStrategy] = useState<Record<string, BuySignalScanResult>>(
    () => cachedScan?.scanResultsByStrategy || {}
  )
  const [manualMinConfirmHits] = useState<number>(2)
  const [loading, setLoading] = useState(false)
  const [scanMessage, setScanMessage] = useState('')
  const [scanTaskId, setScanTaskId] = useState<string | null>(null)
  const [scanProgress, setScanProgress] = useState(0)
  const [cleanupBusy, setCleanupBusy] = useState(false)
  const [cleanupDays, setCleanupDays] = useState(20)
  const [filter, setFilter] = useState<FilterStatus>('all')
  const [selectedSignal, setSelectedSignal] = useState<BuySignal | null>(null)
  const [coreWatchCodes, setCoreWatchCodes] = useState<Set<string>>(new Set())
  const [coreWatchBusyTsCode, setCoreWatchBusyTsCode] = useState<string | null>(null)
  const [backtestVisible, setBacktestVisible] = useState(false)
  const [backtestRunning, setBacktestRunning] = useState(false)
  const [backtestTaskId, setBacktestTaskId] = useState<string | null>(null)
  const [backtestProgress, setBacktestProgress] = useState(0)
  const [backtestMessage, setBacktestMessage] = useState('')
  const [backtestResult, setBacktestResult] = useState<StrategyBacktestResult | null>(null)
  const [backtestRange, setBacktestRange] = useState<[Dayjs, Dayjs]>([
    dayjs().subtract(90, 'day'),
    dayjs().subtract(1, 'day'),
  ])
  const [limitUpRange, setLimitUpRange] = useState<[Dayjs, Dayjs] | null>(() => (
    cachedScan?.limitUpRange
      ? [dayjs(cachedScan.limitUpRange[0], 'YYYYMMDD'), dayjs(cachedScan.limitUpRange[1], 'YYYYMMDD')]
      : null
  ))
  const containerRef = useRef<HTMLDivElement>(null)
  const scanPollingRef = useRef<number | null>(null)
  const backtestPollingRef = useRef<number | null>(null)
  const activePool = useMemo(() => pools.find((pool) => pool.id === activePoolId), [activePoolId, pools])
  const isLimitUpPool = !!activePool && activePool.name.includes('涨停')

  const refreshCoreWatch = useCallback(() => {
    getCoreWatchCodes()
      .then((res) => setCoreWatchCodes(new Set(res.data.ts_codes || [])))
      .catch(() => {})
  }, [])

  const refreshPendingAlerts = useCallback(() => {
    getAlertsPendingCount({ source: 'buy_radar' })
      .then((res) => {
        setPendingAlertCount(res.data.count)
        window.dispatchEvent(new Event('buy-alerts:changed'))
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshPendingAlerts()
    const id = window.setInterval(refreshPendingAlerts, 60_000)
    return () => window.clearInterval(id)
  }, [refreshPendingAlerts])

  useEffect(() => {
    listPools()
      .then((res) => {
        const list = res.data || []
        setPools(list)
        setActivePoolId((prev) => {
          if (prev && list.some((p) => p.id === prev)) return prev
          return list[0]?.id ?? ''
        })
      })
      .catch(() => message.error('加载股票池失败'))

    refreshCoreWatch()

    getBuyStrategies()
      .then((res) => {
        const list = res.data || []
        setStrategies(list)
        if (list.length > 0 && activeStrategyId !== ALL_STRATEGY_ID && !list.some((s) => s.id === activeStrategyId)) {
          setActiveStrategyId(ALL_STRATEGY_ID)
        }
      })
      .catch(() => {})
  }, [refreshCoreWatch, activeStrategyId])

  const mergeAllStrategyResults = useCallback((results: BuySignalScanResult[]): BuySignalScanResult => {
    const statusOrder: Record<BuySignalStatus, number> = {
      confirmed_triggered: 0,
      triggered: 0,
      provisional_triggered: 1,
      approaching: 1,
      tracking: 2,
      invalidated: 3,
    }
    const byCode = new Map<string, BuySignal>()
    results.forEach((r) => {
      const strategyId = r.strategy_id || ''
      const strategyName = r.strategy_name || strategyId || '未知策略'
      const strategyDescription = r.strategy_description || ''
      ;(r.signals || []).forEach((s) => {
        const enriched: BuySignal = {
          ...s,
          strategy_id: s.strategy_id || strategyId,
          strategy_name: s.strategy_name || strategyName,
          strategy_description: s.strategy_description || strategyDescription,
        }
        const isStrategyHit = !['tracking', 'invalidated'].includes(enriched.signal_status)
        const cur = byCode.get(s.ts_code)
        if (!cur) {
          byCode.set(s.ts_code, {
            ...enriched,
            matched_strategies: isStrategyHit
              ? [{
                  strategy_id: enriched.strategy_id || strategyId,
                  strategy_name: enriched.strategy_name || strategyName,
                  strategy_description: enriched.strategy_description || strategyDescription,
                  signal_status: enriched.signal_status,
                  signal_score: enriched.signal_score || 0,
                }]
              : [],
          })
          return
        }
        const existingMatches = cur.matched_strategies || []
        const nextMatches = isStrategyHit
          ? [
              ...existingMatches.filter((m) => m.strategy_id !== (enriched.strategy_id || strategyId)),
              {
                strategy_id: enriched.strategy_id || strategyId,
                strategy_name: enriched.strategy_name || strategyName,
                strategy_description: enriched.strategy_description || strategyDescription,
                signal_status: enriched.signal_status,
                signal_score: enriched.signal_score || 0,
              },
            ]
          : existingMatches
        const curRank = statusOrder[cur.signal_status] ?? 9
        const nextRank = statusOrder[enriched.signal_status] ?? 9
        if (nextRank < curRank || (nextRank === curRank && (enriched.signal_score || 0) > (cur.signal_score || 0))) {
          byCode.set(s.ts_code, { ...enriched, matched_strategies: nextMatches })
        } else {
          byCode.set(s.ts_code, { ...cur, matched_strategies: nextMatches })
        }
      })
    })
    const signals = Array.from(byCode.values()).sort((a, b) => {
      const ra = statusOrder[a.signal_status] ?? 9
      const rb = statusOrder[b.signal_status] ?? 9
      if (ra !== rb) return ra - rb
      return (b.signal_score || 0) - (a.signal_score || 0)
    })
    const latestScanTime = results
      .map((r) => r.scan_time)
      .filter(Boolean)
      .sort()
      .slice(-1)[0] || new Date().toISOString()
    return {
      signals,
      scan_time: latestScanTime,
      total: signals.length,
      triggered_count: signals.filter(
        (s) => s.signal_status === 'triggered' || s.signal_status === 'confirmed_triggered'
      ).length,
      approaching_count: signals.filter((s) => s.signal_status === 'approaching').length,
      strategy_id: ALL_STRATEGY_ID,
      strategy_name: '所有策略',
    }
  }, [])

  const scanResultsList = useMemo(
    () => Object.entries(scanResultsByStrategy)
      .filter(([strategyId, result]) => strategyId !== ALL_STRATEGY_ID && !!result)
      .map(([strategyId, result]) => ({
        ...result,
        strategy_id: result.strategy_id || strategyId,
      })),
    [scanResultsByStrategy],
  )

  const activeScanResult = activeStrategyId === ALL_STRATEGY_ID
    ? (scanResultsByStrategy[ALL_STRATEGY_ID] ?? mergeAllStrategyResults(
        scanResultsList
      ))
    : (scanResultsByStrategy[activeStrategyId] ?? null)

  useEffect(() => {
    const cached = cachedScanRef.current
    if (restoredCacheRef.current || !cached || !hasCachedBuyRadarSignals(cached)) return
    if (pools.length === 0 || strategies.length === 0) return
    const poolExists = pools.some((pool) => pool.id === cached.activePoolId)
    const strategyExists = cached.activeStrategyId === ALL_STRATEGY_ID
      || strategies.some((strategy) => strategy.id === cached.activeStrategyId)
    if (!poolExists || !strategyExists) return
    restoredCacheRef.current = true
    setActivePoolId(cached.activePoolId)
    setActiveStrategyId(cached.activeStrategyId)
    setScanResultsByStrategy(cached.scanResultsByStrategy)
    setCachedSelectedTsCode(cached.selectedTsCode || null)
    setFilter('all')
    if (cached.limitUpRange) {
      setLimitUpRange([dayjs(cached.limitUpRange[0], 'YYYYMMDD'), dayjs(cached.limitUpRange[1], 'YYYYMMDD')])
    } else {
      setLimitUpRange(null)
    }
  }, [pools, strategies])

  const handleToggleCoreWatch = async (sig: BuySignal, starred: boolean) => {
    setCoreWatchBusyTsCode(sig.ts_code)
    try {
      await toggleCoreWatch({
        ts_code: sig.ts_code,
        starred,
        limit_up_date: sig.life_line_date || undefined,
      })
      setCoreWatchCodes((prev) => {
        const next = new Set(prev)
        if (starred) next.add(sig.ts_code)
        else next.delete(sig.ts_code)
        return next
      })
      message.success(starred ? '已加入「核心关注」股票池' : '已取消特别关注')
      listPools()
        .then((res) => setPools(res.data || []))
        .catch(() => {})
    } catch {
      message.error('操作失败，请重试')
    } finally {
      setCoreWatchBusyTsCode(null)
    }
  }

  const filteredSignals = useMemo(() => {
    if (!activeScanResult) return []
    if (filter === 'all') {
      return activeScanResult.signals.filter((s) => s.signal_status !== 'invalidated')
    }
    if (filter === 'triggered') {
      return activeScanResult.signals.filter(
        (s) => s.signal_status === 'triggered' || s.signal_status === 'confirmed_triggered'
      )
    }
    return activeScanResult.signals.filter((s) => s.signal_status === filter)
  }, [activeScanResult, filter])

  useEffect(() => {
    if (loading) return
    if (filteredSignals.length === 0) {
      if (selectedSignal) setSelectedSignal(null)
      return
    }
    if (selectedSignal && filteredSignals.some((s) => s.ts_code === selectedSignal.ts_code)) return
    const cachedSelected = cachedSelectedTsCode
      ? filteredSignals.find((s) => s.ts_code === cachedSelectedTsCode)
      : null
    setSelectedSignal(cachedSelected || filteredSignals[0])
  }, [cachedSelectedTsCode, filteredSignals, loading, selectedSignal])

  const handlePoolChange = (poolId: string) => {
    setActivePoolId(poolId)
    setScanResultsByStrategy({})
    setFilter('all')
    setSelectedSignal(null)
    setCachedSelectedTsCode(null)
  }

  const handleStrategyChange = (strategyId: string) => {
    setActiveStrategyId(strategyId)
    setFilter('all')
    setSelectedSignal(null)
    setCachedSelectedTsCode(null)
  }

  const stopScanPolling = () => {
    if (scanPollingRef.current != null) {
      window.clearTimeout(scanPollingRef.current)
      scanPollingRef.current = null
    }
  }

  const applyScanResult = useCallback((result: BuySignalScanResult, strategyId: string) => {
    const limitUpDateFrom = limitUpRange?.[0]?.format('YYYYMMDD')
    const limitUpDateTo = limitUpRange?.[1]?.format('YYYYMMDD')
    let selectedTsCode: string | null = null
    if (result.signals.length > 0) {
      const first = result.signals.find((s) => s.signal_status !== 'invalidated') || result.signals[0]
      selectedTsCode = first.ts_code
      setSelectedSignal(first)
    } else {
      setSelectedSignal(null)
    }

    setScanResultsByStrategy((prev) => {
      const nextResults = { ...prev, [strategyId]: result }
      setCachedSelectedTsCode(selectedTsCode)
      saveStoredBuyRadarResult({
        activePoolId,
        activeStrategyId,
        limitUpRange: limitUpDateFrom && limitUpDateTo ? [limitUpDateFrom, limitUpDateTo] : null,
        scanResultsByStrategy: nextResults,
        selectedTsCode,
      })
      return nextResults
    })
    refreshPendingAlerts()
    message.success(
      strategyId === ALL_STRATEGY_ID
        ? `全部策略扫描完成: ${result.triggered_count} 只触发, 共 ${result.total} 只。`
        : `扫描完成: ${result.triggered_count} 只触发, 共 ${result.total} 只。待处理提醒已更新，可到买点提醒查看。`
    )
  }, [activePoolId, activeStrategyId, limitUpRange, refreshPendingAlerts])

  const pollScanTask = useCallback((taskId: string, strategyId: string) => {
    const tick = async () => {
      try {
        const res = await getBuySignalScanTask(taskId)
        const data = res.data
        setScanProgress(Math.max(3, Math.round((data.progress || 0) * 100)))
        setScanMessage(data.message || '买点雷达扫描中...')
        if (data.status === 'completed') {
          if (data.result) {
            applyScanResult(data.result, strategyId)
          } else {
            message.warning('扫描任务已完成，但未返回结果')
          }
          setLoading(false)
          stopScanPolling()
          return
        }
        if (data.status === 'failed') {
          setLoading(false)
          message.error(data.message || '扫描失败，请确保已同步K线')
          stopScanPolling()
          return
        }
      } catch {
        setLoading(false)
        message.error('扫描任务状态查询失败')
        stopScanPolling()
        return
      }
      scanPollingRef.current = window.setTimeout(tick, 1500)
    }
    tick()
  }, [applyScanResult])

  const handleScan = async () => {
    if (!activePoolId) {
      message.warning('暂无可用股票池，请先在观察池页面创建')
      return
    }
    if (activeStrategyId === ALL_STRATEGY_ID && strategies.length === 0) {
      message.warning('暂无可用策略')
      return
    }
    const limitUpDateFrom = limitUpRange?.[0]?.format('YYYYMMDD')
    const limitUpDateTo = limitUpRange?.[1]?.format('YYYYMMDD')
    stopScanPolling()
    setLoading(true)
    setScanTaskId(null)
    setScanProgress(0)
    setScanMessage('提交扫描任务中...')
    try {
      const res = await submitBuySignalScanTask(
        activePoolId,
        activeStrategyId,
        manualMinConfirmHits,
        limitUpDateFrom,
        limitUpDateTo
      )
      const taskId = res.data.task_id
      setScanTaskId(taskId)
      setScanProgress(3)
      setScanMessage(activeStrategyId === ALL_STRATEGY_ID ? '全部策略扫描任务已提交，等待后台执行' : '扫描任务已提交，等待后台执行')
      pollScanTask(taskId, activeStrategyId)
    } catch {
      setLoading(false)
      setScanProgress(0)
      message.error('扫描失败，请确保已同步K线')
    }
  }

  const stopBacktestPolling = () => {
    if (backtestPollingRef.current != null) {
      window.clearTimeout(backtestPollingRef.current)
      backtestPollingRef.current = null
    }
  }

  const pollBacktest = useCallback((taskId: string) => {
    const tick = async () => {
      try {
        const res = await getStrategyBacktestResult(taskId)
        const data = res.data
        setBacktestProgress(Math.round((data.progress || 0) * 100))
        setBacktestMessage(data.message || '')
        if (data.status === 'completed') {
          setBacktestRunning(false)
          setBacktestResult(data.result || null)
          message.success('回测完成')
          stopBacktestPolling()
          return
        }
        if (data.status === 'failed') {
          setBacktestRunning(false)
          message.error(data.message || '回测失败')
          stopBacktestPolling()
          return
        }
      } catch {
        setBacktestRunning(false)
        message.error('回测结果查询失败')
        stopBacktestPolling()
        return
      }
      backtestPollingRef.current = window.setTimeout(tick, 1500)
    }
    tick()
  }, [])

  const handleRunBacktest = async () => {
    if (!activePoolId) {
      message.warning('请先选择股票池')
      return
    }
    const trade_date_from = backtestRange[0].format('YYYYMMDD')
    const trade_date_to = backtestRange[1].format('YYYYMMDD')
    setBacktestRunning(true)
    setBacktestProgress(0)
    setBacktestMessage('提交回测任务中...')
    setBacktestResult(null)
    try {
      const res = await submitStrategyBacktest({
        strategy_id: activeStrategyId,
        trade_date_from,
        trade_date_to,
        pool_id: activePoolId,
      })
      const taskId = res.data.task_id
      setBacktestTaskId(taskId)
      pollBacktest(taskId)
    } catch {
      setBacktestRunning(false)
      message.error('提交回测任务失败')
    }
  }

  const renderCleanupPreview = (preview: LimitUpPoolCleanupResult) => (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <div style={{ fontSize: 13, color: '#595959' }}>
        将从 {preview.pool_name} 清理 {preview.candidate_count} / {preview.total} 只股票。
        下方已展示全部 {preview.preview.length} 只候选。
        截止交易日：{preview.cutoff_trade_date_display || preview.cutoff_trade_date}。
        {preview.protected_pinned_count > 0 && ` 已保护 ${preview.protected_pinned_count} 只置顶股票。`}
      </div>
      <Space wrap>
        <Tag color="orange">近{preview.days}交易日无涨停 {preview.reason_counts.no_recent_limit_up}</Tag>
      </Space>
      <Table
        className="cleanup-preview-table"
        size="small"
        rowKey="stock_id"
        pagination={{ pageSize: 10, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100], showTotal: (total) => `共 ${total} 只` }}
        scroll={{ y: 420 }}
        dataSource={preview.preview}
        columns={[
          { title: '股票', dataIndex: 'stock_name', key: 'stock_name', width: 120 },
          { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 110 },
          { title: '最近涨停', dataIndex: 'limit_up_date_display', key: 'limit_up_date_display', width: 100, render: (v) => v || '-' },
          {
            title: '清理原因',
            dataIndex: 'reasons',
            key: 'reasons',
            render: (reasons: string[]) => (
              <Space size={4} wrap>
                {reasons.map((reason) => (
                  <Tag key={reason}>{CLEANUP_REASON_LABELS[reason] || reason}</Tag>
                ))}
              </Space>
            ),
          },
        ]}
      />
    </Space>
  )

  const handleCleanupLimitUpPool = async () => {
    if (!activePoolId) return
    setCleanupBusy(true)
    try {
      const previewRes = await cleanupLimitUpPool(activePoolId, {
        days: cleanupDays,
        dry_run: true,
        include_pinned: false,
      })
      const preview = previewRes.data
      if (preview.candidate_count === 0) {
        message.success('涨停股票池暂无需要清理的股票')
        return
      }
      Modal.confirm({
        title: `清理近${cleanupDays}交易日无涨停标的`,
        width: 820,
        content: renderCleanupPreview(preview),
        okText: `确认清理 ${preview.candidate_count} 只`,
        okButtonProps: { danger: true },
        cancelText: '取消',
        onOk: async () => {
          const res = await cleanupLimitUpPool(activePoolId, {
            days: cleanupDays,
            dry_run: false,
            include_pinned: false,
          })
          message.success(`已清理 ${res.data.deleted_count} 只无效股票`)
          setScanResultsByStrategy({})
          setSelectedSignal(null)
          setCachedSelectedTsCode(null)
          const poolsRes = await listPools()
          setPools(poolsRes.data || [])
        },
      })
    } catch {
      message.error('清理预览失败，请稍后重试')
    } finally {
      setCleanupBusy(false)
    }
  }


  const handleSelect = useCallback((signal: BuySignal) => {
    setSelectedSignal(signal)
  }, [])

  // 键盘快捷键：上下切换
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!filteredSignals.length) return
      const currentIdx = selectedSignal
        ? filteredSignals.findIndex((s) => s.ts_code === selectedSignal.ts_code)
        : -1

      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        const next = Math.min(currentIdx + 1, filteredSignals.length - 1)
        setSelectedSignal(filteredSignals[next])
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        const prev = Math.max(currentIdx - 1, 0)
        setSelectedSignal(filteredSignals[prev])
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [filteredSignals, selectedSignal])

  useEffect(() => {
    return () => {
      stopScanPolling()
      stopBacktestPolling()
    }
  }, [])

  const scanTime = activeScanResult?.scan_time
    ? new Date(activeScanResult.scan_time).toLocaleString('zh-CN')
    : null

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)' }}>
      {/* 顶部工具栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 0', borderBottom: '1px solid #f0f0f0', marginBottom: 0, flexShrink: 0,
      }}>
        <Space size="middle" wrap>
          <Tooltip title="待处理买点提醒，点击进入买点提醒">
            <Badge count={pendingAlertCount} size="small" offset={[-4, 4]}>
              <Button
                type="text"
                aria-label="买点提醒"
                icon={<BellOutlined style={{ fontSize: 18 }} />}
                onClick={() => setAlertsOpen(true)}
              />
            </Badge>
          </Tooltip>
          <span style={{ fontSize: 13, color: '#595959' }}>股票池</span>
          <Select
            style={{ minWidth: 180 }}
            placeholder="选择股票池"
            value={activePoolId || undefined}
            options={pools.map((p) => ({ value: p.id, label: `${p.name} (${p.stock_count})` }))}
            onChange={handlePoolChange}
            disabled={pools.length === 0}
          />
          <span style={{ fontSize: 13, color: '#595959' }}>策略</span>
          <Select
            style={{ minWidth: 160 }}
            value={activeStrategyId}
            options={[
              { value: ALL_STRATEGY_ID, label: '所有策略' },
              ...strategies.map((s) => ({ value: s.id, label: s.name })),
            ]}
            onChange={handleStrategyChange}
            optionRender={(option) => {
              if (option.value === ALL_STRATEGY_ID) {
                return (
                  <Tooltip title="按顺序执行全部策略扫描并汇总结果" placement="right">
                    <span>{option.label}</span>
                  </Tooltip>
                )
              }
              const st = strategies.find((s) => s.id === option.value)
              return (
                <Tooltip title={st?.description} placement="right">
                  <span>{option.label}</span>
                </Tooltip>
              )
            }}
          />

          <Button
            type="primary"
            icon={<ScanOutlined />}
            loading={loading}
            onClick={handleScan}
            size="large"
            disabled={!activePoolId}
          >
            扫描买点
          </Button>
          <DatePicker.RangePicker
            size="small"
            value={limitUpRange}
            onChange={(v) => {
              if (!v || !v[0] || !v[1]) {
                setLimitUpRange(null)
                return
              }
              setLimitUpRange([v[0], v[1]])
            }}
            format="YYYY-MM-DD"
            placeholder={['涨停起始日', '涨停截止日']}
            allowClear
          />
          <Button
            icon={<BarChartOutlined />}
            onClick={() => setBacktestVisible(true)}
            disabled={!activePoolId || activeStrategyId === ALL_STRATEGY_ID}
          >
            回测验证
          </Button>
          {isLimitUpPool && (
            <>
              <Select
                size="small"
                value={cleanupDays}
                style={{ width: 150 }}
                options={[20, 30, 40, 60].map((days) => ({
                  value: days,
                  label: `${days}交易日无涨停`,
                }))}
                onChange={setCleanupDays}
                disabled={cleanupBusy || loading}
              />
              <Button
                icon={<ClearOutlined />}
                loading={cleanupBusy}
                onClick={handleCleanupLimitUpPool}
                disabled={!activePoolId || loading}
              >
                清理无效
              </Button>
            </>
          )}
          <Segmented
            options={[
              { label: `全部${activeScanResult ? ` (${activeScanResult.signals.filter(s => s.signal_status !== 'invalidated').length})` : ''}`, value: 'all' },
              {
                label: (
                  <Badge count={activeScanResult?.triggered_count || 0} size="small" offset={[8, -2]}>
                    <span style={{ padding: '0 4px' }}>已触发</span>
                  </Badge>
                ),
                value: 'triggered',
              },
              {
                label: (
                  <Badge count={activeScanResult?.approaching_count || 0} size="small" offset={[8, -2]} color="#fa8c16">
                    <span style={{ padding: '0 4px' }}>接近</span>
                  </Badge>
                ),
                value: 'approaching',
              },
              { label: '跟踪中', value: 'tracking' },
              { label: '已失效', value: 'invalidated' },
            ]}
            value={filter}
            onChange={(v) => setFilter(v as FilterStatus)}
          />
        </Space>
        <div style={{ fontSize: 12, color: '#8c8c8c' }}>
          {activeScanResult?.strategy_name && (
            <span style={{ marginRight: 12, color: '#1890ff' }}>{activeScanResult.strategy_name}</span>
          )}
          {scanTime && <>扫描时间: {scanTime}</>}
          <span style={{ marginLeft: 12, color: '#bfbfbf' }}>
            快捷键: <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11 }}>↑</kbd>
            <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11, marginLeft: 2 }}>↓</kbd> 切换
          </span>
        </div>
      </div>

      {(loading || scanTaskId) && (
        <div style={{
          padding: '8px 0 10px',
          borderBottom: '1px solid #f5f5f5',
          flexShrink: 0,
        }}>
          <Space size="small" wrap style={{ marginBottom: 4 }}>
            <Tag color={loading ? 'processing' : 'success'}>
              {loading ? '扫描中' : '最近任务'}
            </Tag>
            <span style={{ fontSize: 12, color: '#595959' }}>
              {scanMessage || '买点雷达扫描任务已提交'}
            </span>
            {scanTaskId && (
              <span style={{ fontSize: 12, color: '#8c8c8c' }}>
                任务ID: {scanTaskId.slice(0, 8)}
              </span>
            )}
          </Space>
          <Progress
            percent={scanProgress}
            size="small"
            status={loading ? 'active' : 'normal'}
            showInfo
          />
        </div>
      )}

      <Modal
        title="买点提醒"
        open={alertsOpen}
        onCancel={() => {
          setAlertsOpen(false)
          refreshPendingAlerts()
        }}
        width={1280}
        footer={null}
        destroyOnClose
      >
        <Alerts />
      </Modal>

      <Modal
        title="策略回测验证"
        open={backtestVisible}
        onCancel={() => {
          if (!backtestRunning) {
            setBacktestVisible(false)
          }
        }}
        width={980}
        footer={[
          <Button key="close" onClick={() => setBacktestVisible(false)} disabled={backtestRunning}>
            关闭
          </Button>,
          <Button key="run" type="primary" loading={backtestRunning} onClick={handleRunBacktest}>
            开始回测
          </Button>,
        ]}
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Space wrap>
            <span style={{ color: '#595959' }}>策略:</span>
            <b>{strategies.find((s) => s.id === activeStrategyId)?.name || activeStrategyId}</b>
            <span style={{ color: '#595959', marginLeft: 12 }}>区间:</span>
            <DatePicker.RangePicker
              value={backtestRange}
              onChange={(v) => {
                if (v && v[0] && v[1]) {
                  setBacktestRange([v[0], v[1]])
                }
              }}
              format="YYYY-MM-DD"
              allowClear={false}
            />
          </Space>

          {(backtestRunning || backtestTaskId) && (
            <div>
              <Progress percent={backtestProgress} status={backtestRunning ? 'active' : 'normal'} />
              <div style={{ fontSize: 12, color: '#8c8c8c', marginTop: 4 }}>{backtestMessage || (backtestTaskId ? `任务ID: ${backtestTaskId}` : '')}</div>
            </div>
          )}

          {backtestResult && (
            <>
              <Row gutter={12}>
                <Col span={6}><Statistic title="总信号数" value={backtestResult.total_signals} /></Col>
                <Col span={6}><Statistic title="次日胜率" value={backtestResult.win_rate_1d} suffix="%" precision={1} /></Col>
                <Col span={6}><Statistic title="次日均收益" value={backtestResult.avg_return_1d} suffix="%" precision={2} /></Col>
                <Col span={6}><Statistic title="最大回撤(5日)" value={backtestResult.max_drawdown} suffix="%" precision={2} valueStyle={{ color: backtestResult.max_drawdown < 0 ? '#cf1322' : undefined }} /></Col>
              </Row>
              <Row gutter={12}>
                <Col span={6}><Statistic title="3日胜率" value={backtestResult.win_rate_3d} suffix="%" precision={1} /></Col>
                <Col span={6}><Statistic title="3日均收益" value={backtestResult.avg_return_3d} suffix="%" precision={2} /></Col>
                <Col span={6}><Statistic title="5日胜率" value={backtestResult.win_rate_5d} suffix="%" precision={1} /></Col>
                <Col span={6}><Statistic title="盈亏因子(1日)" value={backtestResult.profit_factor} precision={2} /></Col>
              </Row>
              <Table
                size="small"
                rowKey={(r) => `${r.ts_code}-${r.trigger_date}`}
                pagination={{ pageSize: 8 }}
                dataSource={backtestResult.signals}
                columns={[
                  { title: '代码', dataIndex: 'ts_code', width: 110 },
                  { title: '名称', dataIndex: 'name', width: 120 },
                  {
                    title: '触发日',
                    dataIndex: 'trigger_date',
                    width: 120,
                    render: (v: string) => `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}`,
                  },
                  { title: '入场价', dataIndex: 'entry_price', width: 90 },
                  { title: '1日收益%', dataIndex: 'return_1d', width: 100 },
                  { title: '3日收益%', dataIndex: 'return_3d', width: 100 },
                  { title: '5日收益%', dataIndex: 'return_5d', width: 100 },
                  { title: '评分', dataIndex: 'signal_score', width: 80 },
                ]}
              />
            </>
          )}
        </Space>
      </Modal>

      {/* 主体：左右分栏 */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, marginTop: 0 }}>
        {/* 左侧信号列表 */}
        <div style={{
          width: 320, minWidth: 280, maxWidth: 360, flexShrink: 0,
          borderRight: '1px solid var(--border-subtle)', background: 'var(--bg-surface)',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid var(--border-subtle)',
            fontSize: 13, color: 'var(--text-muted)', flexShrink: 0,
          }}>
            {filteredSignals.length} 只股票
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 48 }}><Spin tip="扫描中..." /></div>
            ) : (
              <SignalList
                signals={filteredSignals}
                selectedCode={selectedSignal?.ts_code || null}
                onSelect={handleSelect}
                coreWatchCodes={coreWatchCodes}
                onToggleCoreWatch={handleToggleCoreWatch}
                coreWatchBusyTsCode={coreWatchBusyTsCode}
              />
            )}
          </div>
        </div>

        {/* 右侧详情 */}
        <div style={{ flex: 1, minWidth: 0, padding: '12px 16px', overflowY: 'auto' }}>
          <SignalDetail
            signal={selectedSignal}
            coreWatchCodes={coreWatchCodes}
            onToggleCoreWatch={handleToggleCoreWatch}
            coreWatchBusyTsCode={coreWatchBusyTsCode}
          />
        </div>
      </div>
    </div>
  )
}

export default BuyRadarPage
