import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Segmented, Spin, message, Badge, Space, Select, Tooltip, Modal, DatePicker, Progress, Table, Row, Col, Statistic, InputNumber, Switch } from 'antd'
import { ScanOutlined, BarChartOutlined, BellOutlined } from '@ant-design/icons'
import dayjs, { Dayjs } from 'dayjs'
import {
  scanBuySignals,
  getBuyStrategies,
  submitStrategyBacktest,
  getStrategyBacktestResult,
  getTradingSession,
  listIntradayScanConfig,
  upsertIntradayScanConfig,
} from '../../api/strategy'
import { getAlertsPendingCount } from '../../api/alerts'
import { listPools, getCoreWatchCodes, toggleCoreWatch } from '../../api/pools'
import SignalList from './SignalList'
import SignalDetail from './SignalDetail'
import type {
  BuySignal,
  BuySignalStatus,
  BuySignalScanResult,
  BuyStrategy,
  Pool,
  StrategyBacktestResult,
  IntradayScanConfigItem,
} from '../../types'

type FilterStatus = 'all' | BuySignalStatus

const LS_AUTO = 'buyRadar:autoScanByStrategy'
const LS_INTERVAL = 'buyRadar:intervalMinutes'
const ALL_STRATEGY_ID = 'all'

const BuyRadarPage: React.FC = () => {
  const navigate = useNavigate()
  const [pendingAlertCount, setPendingAlertCount] = useState(0)
  const [pools, setPools] = useState<Pool[]>([])
  const [activePoolId, setActivePoolId] = useState('')
  const [strategies, setStrategies] = useState<BuyStrategy[]>([])
  const [activeStrategyId, setActiveStrategyId] = useState(ALL_STRATEGY_ID)
  const [scanResultsByStrategy, setScanResultsByStrategy] = useState<Record<string, BuySignalScanResult>>({})
  const [autoScanByStrategy, setAutoScanByStrategy] = useState<Record<string, boolean>>(() => {
    try {
      const s = localStorage.getItem(LS_AUTO)
      return s ? JSON.parse(s) : {}
    } catch {
      return {}
    }
  })
  const [intervalMinutes, setIntervalMinutes] = useState<number>(() => {
    const s = localStorage.getItem(LS_INTERVAL)
    const n = s ? parseInt(s, 10) : 3
    return Number.isFinite(n) && n >= 1 && n <= 30 ? n : 3
  })
  const [inSession, setInSession] = useState(false)
  const [intradayConfigs, setIntradayConfigs] = useState<IntradayScanConfigItem[]>([])
  const [manualMinConfirmHits, setManualMinConfirmHits] = useState<number>(2)
  const [loading, setLoading] = useState(false)
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
  const containerRef = useRef<HTMLDivElement>(null)
  const backtestPollingRef = useRef<number | null>(null)
  const autoScanIntervalRef = useRef<number | null>(null)
  const sessionPollRef = useRef<number | null>(null)

  const refreshCoreWatch = useCallback(() => {
    getCoreWatchCodes()
      .then((res) => setCoreWatchCodes(new Set(res.data.ts_codes || [])))
      .catch(() => {})
  }, [])

  const loadIntradayConfigs = useCallback((poolId?: string) => {
    listIntradayScanConfig(poolId)
      .then((res) => setIntradayConfigs(res.data || []))
      .catch(() => {})
  }, [])

  const refreshPendingAlerts = useCallback(() => {
    getAlertsPendingCount({ source: 'buy_radar' })
      .then((res) => setPendingAlertCount(res.data.count))
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

  useEffect(() => {
    if (activePoolId) {
      loadIntradayConfigs(activePoolId)
    } else {
      setIntradayConfigs([])
    }
  }, [activePoolId, loadIntradayConfigs])

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
      ;(r.signals || []).forEach((s) => {
        const cur = byCode.get(s.ts_code)
        if (!cur) {
          byCode.set(s.ts_code, s)
          return
        }
        const curRank = statusOrder[cur.signal_status] ?? 9
        const nextRank = statusOrder[s.signal_status] ?? 9
        if (nextRank < curRank || (nextRank === curRank && (s.signal_score || 0) > (cur.signal_score || 0))) {
          byCode.set(s.ts_code, s)
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

  const activeScanResult = activeStrategyId === ALL_STRATEGY_ID
    ? mergeAllStrategyResults(
        Object.values(scanResultsByStrategy).filter((r) => !!r?.strategy_id && r.strategy_id !== ALL_STRATEGY_ID)
      )
    : (scanResultsByStrategy[activeStrategyId] ?? null)

  useEffect(() => {
    try {
      localStorage.setItem(LS_AUTO, JSON.stringify(autoScanByStrategy))
    } catch {
      // 本地存储不可用时忽略持久化失败
    }
  }, [autoScanByStrategy])

  useEffect(() => {
    try {
      localStorage.setItem(LS_INTERVAL, String(intervalMinutes))
    } catch {
      // 本地存储不可用时忽略持久化失败
    }
  }, [intervalMinutes])

  useEffect(() => {
    const poll = () => {
      getTradingSession()
        .then((res) => setInSession(!!res.data?.in_session))
        .catch(() => {})
    }
    poll()
    sessionPollRef.current = window.setInterval(poll, 60_000)
    return () => {
      if (sessionPollRef.current != null) window.clearInterval(sessionPollRef.current)
    }
  }, [])

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

  const handlePoolChange = (poolId: string) => {
    setActivePoolId(poolId)
    setScanResultsByStrategy({})
    setFilter('all')
    setSelectedSignal(null)
  }

  const handleStrategyChange = (strategyId: string) => {
    setActiveStrategyId(strategyId)
    setFilter('all')
    setSelectedSignal(null)
  }

  const handleScan = async () => {
    if (!activePoolId) {
      message.warning('暂无可用股票池，请先在观察池页面创建')
      return
    }
    setLoading(true)
    try {
      if (activeStrategyId === ALL_STRATEGY_ID) {
        const targets = strategies.map((s) => s.id)
        if (targets.length === 0) {
          message.warning('暂无可用策略')
          return
        }
        const collected: BuySignalScanResult[] = []
        const patch: Record<string, BuySignalScanResult> = {}
        for (let i = 0; i < targets.length; i++) {
          const sid = targets[i]
          const res = await scanBuySignals(activePoolId, sid, manualMinConfirmHits)
          collected.push(res.data)
          patch[sid] = res.data
          if (i < targets.length - 1) {
            await new Promise((r) => setTimeout(r, 150))
          }
        }
        setScanResultsByStrategy((prev) => ({ ...prev, ...patch }))
        const merged = mergeAllStrategyResults(collected)
        message.success(
          `全部策略扫描完成: ${merged.triggered_count} 只触发, ${merged.approaching_count} 只接近, 共 ${merged.total} 只。`
        )
        refreshPendingAlerts()
        if (merged.signals.length > 0) {
          const first = merged.signals.find((s) => s.signal_status !== 'invalidated') || merged.signals[0]
          setSelectedSignal(first)
        }
      } else {
        const res = await scanBuySignals(activePoolId, activeStrategyId, manualMinConfirmHits)
        setScanResultsByStrategy((prev) => ({ ...prev, [activeStrategyId]: res.data }))
        message.success(
          `扫描完成: ${res.data.triggered_count} 只触发, ${res.data.approaching_count} 只接近, 共 ${res.data.total} 只。待处理提醒已更新，可到买点提醒查看。`
        )
        refreshPendingAlerts()
        if (res.data.signals.length > 0) {
          const first = res.data.signals.find((s) => s.signal_status !== 'invalidated') || res.data.signals[0]
          setSelectedSignal(first)
        }
      }
    } catch {
      message.error('扫描失败，请确保已同步K线')
    } finally {
      setLoading(false)
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


  useEffect(() => {
    if (autoScanIntervalRef.current != null) {
      window.clearInterval(autoScanIntervalRef.current)
      autoScanIntervalRef.current = null
    }
    if (!inSession || !activePoolId) return () => {}
    const enabled = Object.entries(autoScanByStrategy).filter(([, v]) => v).map(([k]) => k)
    if (enabled.length === 0) return () => {}

    const run = async () => {
      for (let i = 0; i < enabled.length; i++) {
        const sid = enabled[i]
        try {
          const res = await scanBuySignals(activePoolId, sid, manualMinConfirmHits)
          setScanResultsByStrategy((prev) => ({ ...prev, [sid]: res.data }))
        } catch {
          // 后台轮询单次失败不打断整个自动扫描周期
        }
        if (i < enabled.length - 1) await new Promise((r) => setTimeout(r, 200))
      }
      refreshPendingAlerts()
    }
    void run()
    autoScanIntervalRef.current = window.setInterval(run, Math.max(1, intervalMinutes) * 60 * 1000)
    return () => {
      if (autoScanIntervalRef.current != null) {
        window.clearInterval(autoScanIntervalRef.current)
        autoScanIntervalRef.current = null
      }
    }
  }, [inSession, activePoolId, autoScanByStrategy, intervalMinutes, refreshPendingAlerts, manualMinConfirmHits])

  const selectedCfg = intradayConfigs.find(
    (c) => c.pool_id === activePoolId && c.strategy_id === activeStrategyId
  )

  const handleUpdateIntradayConfig = async (patch: Partial<IntradayScanConfigItem>) => {
    if (!activePoolId || activeStrategyId === ALL_STRATEGY_ID) return
    const base = selectedCfg || {
      pool_id: activePoolId,
      strategy_id: activeStrategyId,
      enabled: false,
      interval_minutes: 5,
      min_confirm_hits: 2,
    }
    await upsertIntradayScanConfig({
      pool_id: base.pool_id,
      strategy_id: base.strategy_id,
      enabled: patch.enabled ?? base.enabled,
      interval_minutes: patch.interval_minutes ?? base.interval_minutes,
      min_confirm_hits: patch.min_confirm_hits ?? base.min_confirm_hits,
    })
    loadIntradayConfigs(activePoolId)
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
    return () => stopBacktestPolling()
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
                onClick={() => navigate('/alerts?from=radar')}
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

          <Tooltip title={inSession ? '交易时段内按间隔自动扫描' : '非交易时段不轮询，进入时段后自动开始（若开关已开）'}>
            <Space size={4}>
              <span style={{ fontSize: 13, color: '#595959' }}>实时</span>
              <Switch
                disabled={activeStrategyId === ALL_STRATEGY_ID}
                checked={!!autoScanByStrategy[activeStrategyId]}
                onChange={(checked) => {
                  const others = Object.entries(autoScanByStrategy).filter(([id, v]) => v && id !== activeStrategyId).length
                  if (checked && !autoScanByStrategy[activeStrategyId] && others >= 3) {
                    message.warning('最多同时开启 3 个策略的实时扫描')
                    return
                  }
                  setAutoScanByStrategy((prev) => ({ ...prev, [activeStrategyId]: checked }))
                }}
              />
            </Space>
          </Tooltip>
          <Tooltip title="后端盘中轮询（服务端执行，低误报优先）">
            <Space size={4}>
              <span style={{ fontSize: 13, color: '#595959' }}>后端轮询</span>
              <Switch
                disabled={!activePoolId || activeStrategyId === ALL_STRATEGY_ID}
                checked={!!selectedCfg?.enabled}
                onChange={(checked) => {
                  handleUpdateIntradayConfig({ enabled: checked }).catch(() => {
                    message.error('更新后端轮询配置失败')
                  })
                }}
              />
            </Space>
          </Tooltip>
          <span style={{ fontSize: 13, color: '#595959' }}>确证次数</span>
          <InputNumber
            min={1}
            max={5}
            value={selectedCfg?.min_confirm_hits ?? manualMinConfirmHits}
            onChange={(v) => {
              const n = typeof v === 'number' ? v : 2
              setManualMinConfirmHits(n)
              if (activePoolId && activeStrategyId !== ALL_STRATEGY_ID) {
                handleUpdateIntradayConfig({ min_confirm_hits: n }).catch(() => {})
              }
            }}
            size="small"
            style={{ width: 72 }}
          />
          <span style={{ fontSize: 13, color: '#595959' }}>后端间隔</span>
          <InputNumber
            min={1}
            max={30}
            value={selectedCfg?.interval_minutes ?? 5}
            disabled={!selectedCfg?.enabled || activeStrategyId === ALL_STRATEGY_ID}
            onChange={(v) => {
              const n = typeof v === 'number' ? v : 5
              if (activePoolId && activeStrategyId !== ALL_STRATEGY_ID) {
                handleUpdateIntradayConfig({ interval_minutes: n }).catch(() => {
                  message.error('更新后端轮询间隔失败')
                })
              }
            }}
            size="small"
            style={{ width: 80 }}
          />
          <span style={{ fontSize: 13, color: '#595959' }}>间隔(分)</span>
          <InputNumber min={1} max={30} value={intervalMinutes} onChange={(v) => setIntervalMinutes(typeof v === 'number' ? v : 3)} size="small" style={{ width: 64 }} />

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
          <Button
            icon={<BarChartOutlined />}
            onClick={() => setBacktestVisible(true)}
            disabled={!activePoolId || activeStrategyId === ALL_STRATEGY_ID}
          >
            回测验证
          </Button>
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
              { label: '盘中候选', value: 'provisional_triggered' },
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
          {activeScanResult?.intraday_provisional && (
            <span style={{ marginLeft: 8, color: '#fa8c16' }}>盘中快照</span>
          )}
          <span style={{ marginLeft: 12, color: '#bfbfbf' }}>
            快捷键: <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11 }}>↑</kbd>
            <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11, marginLeft: 2 }}>↓</kbd> 切换
          </span>
        </div>
      </div>

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
          borderRight: '1px solid #f0f0f0', background: '#fff',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid #f0f0f0',
            fontSize: 13, color: '#8c8c8c', flexShrink: 0,
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
