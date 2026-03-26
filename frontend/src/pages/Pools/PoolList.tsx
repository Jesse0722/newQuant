import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import {
  Button, Modal, Form, Input, InputNumber, Space, Card,
  Tag, Upload, message, Popconfirm, Select, Tooltip, AutoComplete,
  Segmented, Spin, Empty, Dropdown, Table, Badge, Row, Col, Statistic, Descriptions,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, SyncOutlined, ReloadOutlined,
  PushpinFilled, FileAddOutlined, HolderOutlined,
  EllipsisOutlined, ArrowRightOutlined, ScanOutlined,
  CheckCircleFilled, CloseCircleFilled,
} from '@ant-design/icons'
import * as echarts from 'echarts'
import { useNavigate } from 'react-router-dom'
import {
  listPools, createPool, updatePool, deletePool, reorderPools,
  listStocks, addStock, deleteStock, updateStock, importCSV, getAllStocks,
} from '../../api/pools'
import { searchStocks } from '../../api/stocks'
import { scanBuySignals, getStockChartWithMarks } from '../../api/strategy'
import { createPlan } from '../../api/plans'
import { syncPool, getTaskStatus } from '../../api/sync'
import { getPoolRules, createPoolRule, deleteRule, listTemplates } from '../../api/monitor'
import type {
  Pool, WatchStock, MonitorRule, MonitorTemplate,
  BuySignal, BuySignalScanResult, BuySignalStatus, StockChartDataWithMarks,
} from '../../types'

const PAGE_SIZE = 50
const TRIGGER_OPTIONS = ['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合']

const STATUS_CFG: Record<string, { color: string; label: string }> = {
  triggered: { color: '#f5222d', label: '已触发' },
  approaching: { color: '#fa8c16', label: '接近' },
  tracking: { color: '#1890ff', label: '跟踪中' },
  invalidated: { color: '#bfbfbf', label: '已失效' },
}

type SignalFilter = 'all' | BuySignalStatus

const PoolList: React.FC = () => {
  const [pools, setPools] = useState<Pool[]>([])
  const [activePoolId, setActivePoolId] = useState('')
  const [stocks, setStocks] = useState<WatchStock[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const pageRef = useRef(1)

  const [selectedCode, setSelectedCode] = useState('')
  const [chartPeriod, setChartPeriod] = useState(120)
  const [subIndicator, setSubIndicator] = useState<'macd' | 'rsi'>('macd')
  const [chartData, setChartData] = useState<StockChartDataWithMarks | null>(null)
  const [chartLoading, setChartLoading] = useState(false)

  const [scanResult, setScanResult] = useState<BuySignalScanResult | null>(null)
  const [scanning, setScanning] = useState(false)
  const [signalFilter, setSignalFilter] = useState<SignalFilter>('all')

  const [limitUpDateFrom, setLimitUpDateFrom] = useState('')
  const [limitUpDateTo, setLimitUpDateTo] = useState('')
  const [sortBy, setSortBy] = useState<'created_at' | 'limit_up_date'>('limit_up_date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  const [addModalOpen, setAddModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [editPoolModalOpen, setEditPoolModalOpen] = useState(false)
  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [planStock, setPlanStock] = useState<WatchStock | null>(null)
  const [createPlanModalOpen, setCreatePlanModalOpen] = useState(false)
  const [addRuleModalOpen, setAddRuleModalOpen] = useState(false)

  const [addForm] = Form.useForm()
  const [poolForm] = Form.useForm()
  const [planForm] = Form.useForm()
  const [createPlanForm] = Form.useForm()
  const [ruleForm] = Form.useForm()

  const [allStocks, setAllStocks] = useState<Array<{ ts_code: string; stock_name?: string }>>([])
  const [stockSearchOptions, setStockSearchOptions] = useState<Array<{ value: string; label: string }>>([])
  const [stockSearching, setStockSearching] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [poolRules, setPoolRules] = useState<MonitorRule[]>([])
  const [monitorTemplates, setMonitorTemplates] = useState<MonitorTemplate[]>([])
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)

  const navigate = useNavigate()
  const initialLoaded = useRef(false)
  const listRef = useRef<HTMLDivElement>(null)
  const chartDivRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const selectedItemRef = useRef<HTMLDivElement>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const filtersRef = useRef({ sortBy, sortOrder, limitUpDateFrom, limitUpDateTo })
  filtersRef.current = { sortBy, sortOrder, limitUpDateFrom, limitUpDateTo }
  const anyModalOpenRef = useRef(false)
  anyModalOpenRef.current = addModalOpen || importModalOpen || editPoolModalOpen || planModalOpen || createPlanModalOpen || addRuleModalOpen

  /* ===== Computed ===== */

  const activePool = pools.find(p => p.id === activePoolId)

  const signalMap = useMemo(() => {
    if (!scanResult) return new Map<string, BuySignal>()
    const m = new Map<string, BuySignal>()
    for (const s of scanResult.signals) m.set(s.ts_code, s)
    return m
  }, [scanResult])

  const displayStocks = useMemo(() => {
    if (!scanResult || signalFilter === 'all') return stocks
    return stocks.filter(s => {
      const sig = signalMap.get(s.ts_code)
      return sig && sig.signal_status === signalFilter
    })
  }, [stocks, scanResult, signalFilter, signalMap])

  const selectedStock = displayStocks.find(s => s.ts_code === selectedCode) || null
  const selectedSignal = signalMap.get(selectedCode) || null
  const selectedIndex = displayStocks.findIndex(s => s.ts_code === selectedCode)
  const hasMore = stocks.length > 0 && stocks.length < total

  /* ===== Data Fetching ===== */

  const fetchPools = async () => {
    const res = await listPools()
    setPools(res.data)
    return res.data
  }

  const fetchPage = async (poolId: string, pageNum: number) => {
    const f = filtersRef.current
    const params: Record<string, string | number> = {
      page: pageNum, size: PAGE_SIZE, sort_by: f.sortBy, order: f.sortOrder,
    }
    if (f.limitUpDateFrom) params.limit_up_date_from = f.limitUpDateFrom.replace(/-/g, '')
    if (f.limitUpDateTo) params.limit_up_date_to = f.limitUpDateTo.replace(/-/g, '')
    return listStocks(poolId, params)
  }

  const loadInitial = async (poolId: string) => {
    if (!poolId) { setStocks([]); setTotal(0); return }
    pageRef.current = 1
    setLoading(true)
    try {
      const res = await fetchPage(poolId, 1)
      setStocks(res.data.items)
      setTotal(res.data.total)
      setSelectedCode(res.data.items[0]?.ts_code || '')
    } finally {
      setLoading(false)
    }
  }

  const loadMore = useCallback(async () => {
    if (loadingMore || loading || stocks.length >= total || !activePoolId) return
    pageRef.current += 1
    setLoadingMore(true)
    try {
      const res = await fetchPage(activePoolId, pageRef.current)
      setStocks(prev => [...prev, ...res.data.items])
      setTotal(res.data.total)
    } finally {
      setLoadingMore(false)
    }
  }, [loadingMore, loading, stocks.length, total, activePoolId])

  const handleScan = async () => {
    if (!activePoolId) return
    setScanning(true)
    try {
      const res = await scanBuySignals(activePoolId)
      setScanResult(res.data)
      setSignalFilter('all')
      message.success(
        `扫描完成: ${res.data.triggered_count} 只触发, ${res.data.approaching_count} 只接近, 共 ${res.data.total} 只`
      )
    } catch {
      message.error('扫描失败')
    } finally {
      setScanning(false)
    }
  }

  /* ===== Effects ===== */

  useEffect(() => {
    fetchPools().then(data => {
      if (!initialLoaded.current && data.length > 0) {
        setActivePoolId(data[0].id)
        initialLoaded.current = true
      }
    })
  }, [])

  useEffect(() => {
    if (activePoolId) {
      loadInitial(activePoolId)
      setScanResult(null)
      setSignalFilter('all')
    }
  }, [activePoolId, limitUpDateFrom, limitUpDateTo, sortBy, sortOrder])

  useEffect(() => {
    const exists = displayStocks.some(s => s.ts_code === selectedCode)
    if (!exists && displayStocks.length > 0) setSelectedCode(displayStocks[0].ts_code)
  }, [displayStocks])

  useEffect(() => { setChartData(null) }, [selectedCode])

  useEffect(() => {
    if (!selectedCode) return
    setChartLoading(true)
    const stock = stocks.find(s => s.ts_code === selectedCode)
    getStockChartWithMarks(selectedCode, chartPeriod, stock?.limit_up_date || undefined)
      .then(res => setChartData(res.data))
      .catch(() => setChartData(null))
      .finally(() => setChartLoading(false))
  }, [selectedCode, chartPeriod])

  // Chart rendering with signal marks
  useEffect(() => {
    if (chartInstance.current) {
      try { chartInstance.current.dispose() } catch { /* noop */ }
      chartInstance.current = null
    }
    const timer = setTimeout(() => {
      if (!chartDivRef.current || !chartData?.quotes?.length) return
      chartInstance.current = echarts.init(chartDivRef.current)
      const { quotes, indicators, signal_marks } = chartData
      const dates = quotes.map(q => q.date)
      const ohlc = quotes.map(q => [q.open, q.close, q.low, q.high])
      const volumes = quotes.map(q => ({
        value: q.vol,
        itemStyle: { color: q.close >= q.open ? '#ec0000' : '#00da3c' },
      }))

      const markPoints: any[] = []
      const markLines: any[] = []
      if (signal_marks) {
        for (const mark of signal_marks) {
          if (mark.type === 'life_line' && mark.value != null) {
            markLines.push({
              name: mark.label, yAxis: mark.value,
              lineStyle: { color: '#722ed1', type: 'dashed', width: 1.5 },
              label: { formatter: `${mark.label} ${mark.value.toFixed(2)}`, color: '#722ed1', fontSize: 11 },
            })
          }
          if (mark.type === 'phase2_high' && dates.includes(mark.date)) {
            markPoints.push({
              name: mark.label, coord: [mark.date, mark.value],
              symbol: 'triangle', symbolSize: 10, symbolRotate: 180,
              itemStyle: { color: '#faad14' },
              label: { show: true, formatter: mark.label, position: 'top', fontSize: 10, color: '#faad14' },
            })
          }
          if (mark.type === 'buy_signal' && dates.includes(mark.date)) {
            markPoints.push({
              name: mark.label, coord: [mark.date, mark.value],
              symbol: 'triangle', symbolSize: 12,
              itemStyle: { color: '#f5222d' },
              label: { show: true, formatter: mark.label, position: 'bottom', fontSize: 10, color: '#f5222d', fontWeight: 'bold' },
            })
          }
        }
      }

      const candleSeries: any = {
        name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
      }
      if (markPoints.length > 0) candleSeries.markPoint = { data: markPoints }
      if (markLines.length > 0) candleSeries.markLine = { data: markLines, silent: true, symbol: 'none' }

      const series: any[] = [
        candleSeries,
        { name: 'MA5', type: 'line', data: indicators.ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
        { name: 'MA10', type: 'line', data: indicators.ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
        { name: 'MA20', type: 'line', data: indicators.ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
        { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 },
      ]
      if (subIndicator === 'macd') {
        series.push(
          { name: 'DIF', type: 'line', data: indicators.macd.dif, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1 } },
          { name: 'DEA', type: 'line', data: indicators.macd.dea, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1 } },
          {
            name: 'MACD', type: 'bar',
            data: indicators.macd.histogram.map(v => ({ value: v, itemStyle: { color: v != null && v >= 0 ? '#ec0000' : '#00da3c' } })),
            xAxisIndex: 2, yAxisIndex: 2,
          },
        )
      } else {
        series.push({
          name: 'RSI', type: 'line', data: indicators.rsi,
          xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1.5, color: '#9b59b6' },
        })
      }
      chartInstance.current.setOption({
        animation: false,
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: ['MA5', 'MA10', 'MA20'], top: 0, left: 'center', textStyle: { fontSize: 11 } },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
          { left: 56, right: 16, top: 28, height: '46%' },
          { left: 56, right: 16, top: '58%', height: '12%' },
          { left: 56, right: 16, top: '74%', height: '18%' },
        ],
        xAxis: [
          { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, boundaryGap: true },
          { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false }, boundaryGap: true },
          { type: 'category', data: dates, gridIndex: 2, boundaryGap: true, axisLabel: { fontSize: 10 } },
        ],
        yAxis: [
          { scale: true, gridIndex: 0, splitNumber: 4 },
          { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false } },
          { scale: true, gridIndex: 2, splitNumber: 3 },
        ],
        dataZoom: [
          { type: 'inside', xAxisIndex: [0, 1, 2], start: 50, end: 100 },
          { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 4, height: 16, start: 50, end: 100 },
        ],
        series,
      }, true)
    }, 80)
    return () => clearTimeout(timer)
  }, [chartData, subIndicator, selectedCode])

  useEffect(() => {
    const onResize = () => chartInstance.current?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (anyModalOpenRef.current) return
      const idx = displayStocks.findIndex(s => s.ts_code === selectedCode)
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        if (idx < displayStocks.length - 1) setSelectedCode(displayStocks[idx + 1].ts_code)
        else if (hasMore) loadMore()
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        if (idx > 0) setSelectedCode(displayStocks[idx - 1].ts_code)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        if (selectedCode) navigate(`/stocks/${selectedCode}`)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [displayStocks, selectedCode, hasMore, loadMore, navigate])

  useEffect(() => {
    selectedItemRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selectedCode])

  useEffect(() => {
    if (selectedIndex >= displayStocks.length - 5 && hasMore && !loadingMore) loadMore()
  }, [selectedIndex, displayStocks.length, hasMore, loadingMore, loadMore])

  useEffect(() => {
    if (createPlanModalOpen) getAllStocks().then(res => setAllStocks(res.data || []))
  }, [createPlanModalOpen])

  /* ===== Handlers ===== */

  const handleAddPool = async () => {
    const res = await createPool({ name: `新观察池 ${pools.length + 1}` })
    await fetchPools()
    setActivePoolId(res.data.id)
    message.success('已创建')
  }

  const handleDeletePool = (poolId: string) => {
    Modal.confirm({
      title: '确定删除该观察池？', content: '池内所有股票将一并删除',
      onOk: async () => {
        await deletePool(poolId)
        const updated = await fetchPools()
        if (activePoolId === poolId) setActivePoolId(updated.length > 0 ? updated[0].id : '')
        message.success('已删除')
      },
    })
  }

  const openEditPoolModal = () => {
    const pool = pools.find(p => p.id === activePoolId)
    if (!pool) return
    poolForm.setFieldsValue({ name: pool.name, description: pool.description, trigger_target_pool_id: pool.trigger_target_pool_id || undefined })
    setEditPoolModalOpen(true)
    getPoolRules(activePoolId).then(res => setPoolRules(res.data || []))
    listTemplates().then(res => setMonitorTemplates(res.data || []))
  }

  const handleEditPool = async () => {
    const values = await poolForm.validateFields()
    await updatePool(activePoolId, values)
    message.success('更新成功')
    setEditPoolModalOpen(false)
    fetchPools()
  }

  const handleAddRule = async () => {
    const values = await ruleForm.validateFields()
    const template = monitorTemplates.find(t => t.id === values.template_id)
    const merged = template?.default_params ? { ...template.default_params } : {}
    Object.entries(values.params || {}).forEach(([k, v]) => { if (v != null && v !== '') merged[k] = v })
    await createPoolRule(activePoolId, { template_id: values.template_id, params: merged })
    message.success('规则已添加')
    setAddRuleModalOpen(false)
    ruleForm.resetFields()
    getPoolRules(activePoolId).then(res => setPoolRules(res.data || []))
  }

  const handleDeleteRule = async (ruleId: string) => {
    await deleteRule(ruleId)
    message.success('规则已删除')
    getPoolRules(activePoolId).then(res => setPoolRules(res.data || []))
  }

  const handleStockSearch = (q: string) => {
    const v = (q || '').trim()
    if (v.length < 2) { setStockSearchOptions([]); return }
    if (searchTimer.current) clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => {
      setStockSearching(true)
      searchStocks(v)
        .then(res => setStockSearchOptions((res.data || []).map(s => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` }))))
        .catch(() => setStockSearchOptions([]))
        .finally(() => setStockSearching(false))
    }, 300)
  }

  const handleAddStock = async () => {
    const values = await addForm.validateFields()
    await addStock(activePoolId, values)
    message.success('添加成功')
    setAddModalOpen(false)
    addForm.resetFields()
    setStockSearchOptions([])
    loadInitial(activePoolId)
    fetchPools()
  }

  const handleDeleteStock = async (stockId: string) => {
    await deleteStock(activePoolId, stockId)
    message.success('已移除')
    const deleted = stocks.find(s => s.id === stockId)
    setStocks(prev => prev.filter(s => s.id !== stockId))
    setTotal(prev => prev - 1)
    if (deleted?.ts_code === selectedCode) {
      const idx = stocks.findIndex(s => s.id === stockId)
      const next = stocks[idx + 1] || stocks[idx - 1]
      setSelectedCode(next?.ts_code || '')
    }
    fetchPools()
  }

  const handleImport = async (file: File) => {
    const res = await importCSV(activePoolId, file)
    const r = res.data as any
    message.success(`导入 ${r.imported} 只，跳过 ${r.skipped} 只`)
    setImportModalOpen(false)
    loadInitial(activePoolId)
    fetchPools()
    return false
  }

  const handleSync = async () => {
    if (!activePoolId) return
    setSyncing(true)
    try {
      const res = await syncPool(activePoolId)
      const taskId = res.data.task_id
      const poll = setInterval(async () => {
        try {
          const st = await getTaskStatus(taskId)
          if (st.data.status === 'completed' || st.data.status === 'failed') {
            clearInterval(poll)
            setSyncing(false)
            message[st.data.status === 'completed' ? 'success' : 'error'](st.data.status === 'completed' ? '同步完成' : '同步失败')
            loadInitial(activePoolId)
          }
        } catch { clearInterval(poll); setSyncing(false) }
      }, 2000)
    } catch { setSyncing(false) }
  }

  const handleTogglePin = async (stock: WatchStock) => {
    await updateStock(activePoolId, stock.id, { pinned: !stock.pinned })
    setStocks(prev => prev.map(s => s.id === stock.id ? { ...s, pinned: !s.pinned } : s))
  }

  const openCreatePlanModal = (stock: WatchStock) => {
    setPlanStock(stock)
    planForm.resetFields()
    planForm.setFieldsValue({
      title: `${stock.stock_name || stock.ts_code} - 计划`,
      stocks: [{ ts_code: stock.ts_code, risk_level: 2, planned_buy_price: stock.added_price }],
    })
    setPlanModalOpen(true)
  }

  const handleCreatePlan = async () => {
    const values = await planForm.validateFields()
    const ss = values.stocks.map((s: any) => ({
      ts_code: s.ts_code, risk_level: s.risk_level ?? 2, trigger_strategy: s.trigger_strategy,
      planned_buy_price: s.planned_buy_price, target_price: s.target_price,
      stop_loss_price: s.stop_loss_price, position_plan: s.position_plan, note: s.note,
    }))
    await createPlan({ title: values.title, stocks: ss, note: values.note })
    message.success('交易计划已创建')
    setPlanModalOpen(false)
    setPlanStock(null)
  }

  const handleCreatePlanFromToolbar = async () => {
    const values = await createPlanForm.validateFields()
    const ss = values.stocks.map((s: any) => ({
      ts_code: s.ts_code, risk_level: s.risk_level ?? 2, trigger_strategy: s.trigger_strategy,
      planned_buy_price: s.planned_buy_price, target_price: s.target_price,
      stop_loss_price: s.stop_loss_price, position_plan: s.position_plan, note: s.note,
    }))
    await createPlan({ title: values.title, stocks: ss, note: values.note })
    message.success('交易计划已创建')
    setCreatePlanModalOpen(false)
    createPlanForm.resetFields()
  }

  const handleTabDragStart = (e: React.DragEvent, i: number) => { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(i)) }
  const handleTabDragOver = (e: React.DragEvent, i: number) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDragOverIndex(i) }
  const handleTabDragLeave = () => setDragOverIndex(null)
  const handleTabDrop = async (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault(); setDragOverIndex(null)
    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'), 10)
    if (Number.isNaN(fromIndex) || fromIndex === targetIndex) return
    const np = [...pools]; const [removed] = np.splice(fromIndex, 1); np.splice(targetIndex, 0, removed); setPools(np)
    try { await reorderPools(np.map(p => p.id)); message.success('排序已保存') } catch { setPools(pools); message.error('排序保存失败') }
  }
  const handleTabDragEnd = () => setDragOverIndex(null)

  const onListScroll = useCallback(() => {
    const el = listRef.current
    if (!el || !hasMore || loadingMore || loading) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 300) loadMore()
  }, [hasMore, loadingMore, loading, loadMore])

  const stockOptions = allStocks.map(s => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` }))
  const fmtLimitDate = (d?: string) => d ? `${d.slice(4, 6)}-${d.slice(6)}` : ''

  /* ===== Render: Left panel stock item ===== */

  const renderStockItem = (stock: WatchStock) => {
    const isSelected = stock.ts_code === selectedCode
    const sig = signalMap.get(stock.ts_code)
    const cfg = sig ? STATUS_CFG[sig.signal_status] || STATUS_CFG.tracking : null

    return (
      <div
        key={stock.id}
        ref={isSelected ? selectedItemRef : undefined}
        onClick={() => setSelectedCode(stock.ts_code)}
        style={{
          padding: '10px 14px',
          cursor: 'pointer',
          borderLeft: cfg ? `3px solid ${isSelected ? cfg.color : 'transparent'}` : '3px solid transparent',
          background: isSelected ? '#f0f5ff' : undefined,
          borderBottom: '1px solid #f0f0f0',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '#fafafa' }}
        onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: sig ? 4 : 0 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>{stock.stock_name || '-'}</span>
          {sig && cfg && (
            <Tag color={cfg.color} style={{ margin: 0, fontSize: 11, lineHeight: '18px', padding: '0 6px' }}>{cfg.label}</Tag>
          )}
        </div>
        <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: sig ? 4 : 2 }}>
          {stock.ts_code} {stock.industry ? `· ${stock.industry}` : ''}
          {stock.limit_up_date && <span style={{ marginLeft: 6 }}>涨停 {fmtLimitDate(stock.limit_up_date)}</span>}
        </div>
        {sig && sig.signal_status !== 'invalidated' ? (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
            <span>评分: <b style={{ color: sig.signal_score >= 70 ? '#f5222d' : sig.signal_score >= 50 ? '#fa8c16' : '#8c8c8c' }}>{sig.signal_score}</b></span>
            {sig.pullback_pct != null && <span>回调: <b style={{ color: '#3f8600' }}>-{sig.pullback_pct}%</b></span>}
            {sig.latest_pct_chg != null && (
              <span>今涨: <b style={{ color: sig.latest_pct_chg >= 0 ? '#cf1322' : '#3f8600' }}>{sig.latest_pct_chg >= 0 ? '+' : ''}{sig.latest_pct_chg.toFixed(2)}%</b></span>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
            <span style={{ fontFamily: "'Menlo', monospace", fontWeight: 600 }}>
              {stock.latest_price != null ? stock.latest_price.toFixed(2) : '-'}
            </span>
            {stock.pct_chg != null && (
              <span style={{ fontWeight: 600, color: stock.pct_chg > 0 ? '#cf1322' : stock.pct_chg < 0 ? '#3f8600' : '#666' }}>
                {stock.pct_chg > 0 ? '+' : ''}{stock.pct_chg.toFixed(2)}%
              </span>
            )}
            {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 11 }} />}
          </div>
        )}
        {sig?.signal_status === 'approaching' && sig.unmet_conditions.length > 0 && (
          <div style={{ fontSize: 11, color: '#fa8c16', marginTop: 2 }}>
            差{sig.unmet_conditions.length}条件: {sig.unmet_conditions.slice(0, 2).join('、')}
          </div>
        )}
      </div>
    )
  }

  /* ===== Render: Right detail panel ===== */

  const renderDetailPanel = () => {
    if (!selectedStock) {
      return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#bfbfbf' }}>
        <Empty description="从左侧列表选择一只股票" />
      </div>
    }

    const sig = selectedSignal
    const statusCfg = sig ? STATUS_CFG[sig.signal_status] || STATUS_CFG.tracking : null

    return (
      <div style={{ overflowY: 'auto', height: '100%', padding: '0 0 16px' }}>
        {/* Info header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 18, fontWeight: 700 }}>{selectedStock.stock_name || selectedStock.ts_code}</span>
            <span style={{ fontSize: 14, color: '#8c8c8c' }}>{selectedStock.ts_code}</span>
            {selectedStock.industry && <Tag>{selectedStock.industry}</Tag>}
            {sig && statusCfg && <Tag color={statusCfg.color}>{statusCfg.label}</Tag>}
          </div>
          <Space size="small">
            <Dropdown trigger={['click']} menu={{
              items: [
                { key: 'plan', label: '创建交易计划', onClick: () => openCreatePlanModal(selectedStock) },
                { key: 'pin', label: selectedStock.pinned ? '取消置顶' : '置顶', onClick: () => handleTogglePin(selectedStock) },
                { type: 'divider' as const },
                { key: 'delete', label: '移除', danger: true, onClick: () => Modal.confirm({ title: '确定移除？', onOk: () => handleDeleteStock(selectedStock.id) }) },
              ],
            }}>
              <Button size="small">操作 <EllipsisOutlined /></Button>
            </Dropdown>
            <Button size="small" onClick={() => navigate(`/stocks/${selectedStock.ts_code}`)}>完整详情 <ArrowRightOutlined /></Button>
          </Space>
        </div>

        {/* Metrics row (when signal available) */}
        {sig && sig.signal_status !== 'invalidated' && (
          <Row gutter={16} style={{ marginBottom: 12 }}>
            <Col span={4}><Statistic title="最新价" value={sig.latest_close ?? '-'} precision={2} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={4}>
              <Statistic title="今涨幅" value={sig.latest_pct_chg ?? 0} precision={2} suffix="%"
                valueStyle={{ fontSize: 16, color: (sig.latest_pct_chg ?? 0) >= 0 ? '#cf1322' : '#3f8600' }} />
            </Col>
            <Col span={4}>
              <Statistic title="信号评分" value={sig.signal_score} suffix="/ 100"
                valueStyle={{ fontSize: 16, color: sig.signal_score >= 70 ? '#f5222d' : '#595959' }} />
            </Col>
            <Col span={4}><Statistic title="回调幅度" value={sig.pullback_pct ?? '-'} precision={1} suffix="%" valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="距生命线" value={sig.days_since_life_line ?? '-'} suffix="天" valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={4}><Statistic title="RSI" value={sig.rsi ?? '-'} precision={1} valueStyle={{ fontSize: 16 }} /></Col>
          </Row>
        )}

        {/* K-line chart */}
        <Card size="small" style={{ marginBottom: 12 }} extra={
          <Space>
            <Segmented size="small" options={[{ label: '60日', value: 60 }, { label: '120日', value: 120 }, { label: '250日', value: 250 }]}
              value={chartPeriod} onChange={v => setChartPeriod(v as number)} />
            <Segmented size="small" options={[{ label: 'MACD', value: 'macd' }, { label: 'RSI', value: 'rsi' }]}
              value={subIndicator} onChange={v => setSubIndicator(v as 'macd' | 'rsi')} />
          </Space>
        }>
          {chartLoading && !chartData ? (
            <div style={{ height: 440, display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Spin /></div>
          ) : (
            <div ref={chartDivRef} style={{ width: '100%', height: 440, opacity: chartLoading ? 0.4 : 1, transition: 'opacity 0.2s' }} />
          )}
        </Card>

        {/* Buy conditions (when signal available) */}
        {sig && sig.signal_status !== 'invalidated' && (
          <Card size="small" title="买点条件检查">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {sig.met_conditions.map(c => <Tag key={c} color="success" icon={<CheckCircleFilled />}>{c}</Tag>)}
              {sig.unmet_conditions.map(c => <Tag key={c} color="default" icon={<CloseCircleFilled />}>{c}</Tag>)}
            </div>
            {sig.life_line_date && (
              <Descriptions size="small" column={3} style={{ marginTop: 12 }} bordered>
                <Descriptions.Item label="生命线日期">
                  {sig.life_line_date.slice(0, 4)}-{sig.life_line_date.slice(4, 6)}-{sig.life_line_date.slice(6)}
                </Descriptions.Item>
                <Descriptions.Item label="生命线价格">{sig.life_line_price?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="阶段高点">{sig.phase2_high?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="量比">{sig.volume_ratio?.toFixed(2) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="MACD柱">{sig.macd_hist?.toFixed(4) ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="RSI">{sig.rsi?.toFixed(1) ?? '-'}</Descriptions.Item>
              </Descriptions>
            )}
          </Card>
        )}
      </div>
    )
  }

  /* ===== Main return ===== */

  return (
    <div style={{ height: 'calc(100vh - 112px)', display: 'flex', flexDirection: 'column' }}>
      {/* Top bar: pool tabs + toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexShrink: 0 }}>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', flex: 1, minWidth: 0 }}
          onDragEnd={handleTabDragEnd} onDragLeave={handleTabDragLeave}>
          {pools.map((p, i) => (
            <div key={p.id} draggable onDragStart={e => handleTabDragStart(e, i)} onDragOver={e => handleTabDragOver(e, i)}
              onDrop={e => handleTabDrop(e, i)} onClick={() => setActivePoolId(p.id)}
              style={{
                display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontSize: 13,
                cursor: 'pointer', userSelect: 'none', borderRadius: 6,
                background: activePoolId === p.id ? '#1677ff' : dragOverIndex === i ? '#e6f7ff' : '#f5f5f5',
                color: activePoolId === p.id ? '#fff' : '#333',
                fontWeight: activePoolId === p.id ? 600 : 400, transition: 'all 0.15s',
              }}>
              <HolderOutlined style={{ fontSize: 10, opacity: 0.4, cursor: 'grab' }} />
              <span>{p.name}</span>
              <span style={{ opacity: 0.6, fontSize: 12 }}>({p.stock_count})</span>
              <span onClick={e => { e.stopPropagation(); handleDeletePool(p.id) }}
                style={{ marginLeft: 2, cursor: 'pointer', opacity: 0.4, fontSize: 11, lineHeight: 1 }}>×</span>
            </div>
          ))}
          <div onClick={handleAddPool} style={{ padding: '4px 10px', fontSize: 13, cursor: 'pointer', borderRadius: 6, border: '1px dashed #d9d9d9', color: '#999' }}>+ 新建</div>
        </div>
        {activePool && (
          <Space size="small" style={{ flexShrink: 0, marginLeft: 8 }}>
            <Button size="small" type="primary" icon={<ScanOutlined />} loading={scanning} onClick={handleScan}>扫描买点</Button>
            <Button size="small" icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={handleSync}>同步</Button>
            <Button size="small" onClick={openEditPoolModal}>编辑池</Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadInitial(activePoolId)} />
          </Space>
        )}
      </div>

      {/* Main body: left-right split */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff', overflow: 'hidden' }}>
        {/* Left panel: filters + stock list */}
        <div style={{ width: 340, minWidth: 280, maxWidth: 380, flexShrink: 0, borderRight: '1px solid #f0f0f0', display: 'flex', flexDirection: 'column' }}>
          {/* Toolbar row */}
          <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexShrink: 0 }}>
            <Space size="small">
              {(activePool?.name?.includes('涨停') ?? false) && (
                <>
                  <Input size="small" placeholder="起 YYYYMMDD" value={limitUpDateFrom}
                    onChange={e => setLimitUpDateFrom(e.target.value.replace(/-/g, '').slice(0, 8))} style={{ width: 90 }} />
                  <Input size="small" placeholder="止 YYYYMMDD" value={limitUpDateTo}
                    onChange={e => setLimitUpDateTo(e.target.value.replace(/-/g, '').slice(0, 8))} style={{ width: 90 }} />
                </>
              )}
              <Select size="small" value={`${sortBy}-${sortOrder}`} onChange={v => {
                const [s, o] = v.split('-') as ['created_at' | 'limit_up_date', 'asc' | 'desc']
                setSortBy(s); setSortOrder(o)
              }} style={{ width: 130 }} options={[
                { value: 'limit_up_date-desc', label: '涨停 新→旧' }, { value: 'limit_up_date-asc', label: '涨停 旧→新' },
                { value: 'created_at-desc', label: '加入 新→旧' }, { value: 'created_at-asc', label: '加入 旧→新' },
              ]} />
            </Space>
            <Space size={4}>
              <Tooltip title="CSV 导入"><Button size="small" icon={<UploadOutlined />} onClick={() => setImportModalOpen(true)} /></Tooltip>
              <Tooltip title="添加股票"><Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)} /></Tooltip>
            </Space>
          </div>

          {/* Signal filter (after scan) */}
          {scanResult && (
            <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', flexShrink: 0 }}>
              <Segmented size="small" block options={[
                { label: `全部 (${stocks.length})`, value: 'all' },
                { label: <Badge count={scanResult.triggered_count} size="small" offset={[6, -2]}><span style={{ padding: '0 2px' }}>触发</span></Badge>, value: 'triggered' },
                { label: <Badge count={scanResult.approaching_count} size="small" offset={[6, -2]} color="#fa8c16"><span style={{ padding: '0 2px' }}>接近</span></Badge>, value: 'approaching' },
                { label: '跟踪', value: 'tracking' },
                { label: '失效', value: 'invalidated' },
              ]} value={signalFilter} onChange={v => setSignalFilter(v as SignalFilter)} />
            </div>
          )}

          {/* Stock count */}
          <div style={{ padding: '6px 14px', fontSize: 12, color: '#8c8c8c', borderBottom: '1px solid #f5f5f5', flexShrink: 0 }}>
            {displayStocks.length} 只 {scanResult ? '(已扫描)' : ''} · {selectedIndex >= 0 ? selectedIndex + 1 : '-'}/{displayStocks.length}
            <span style={{ float: 'right', color: '#bfbfbf' }}>↑↓ 切换</span>
          </div>

          {/* Stock list */}
          <div ref={listRef} onScroll={onListScroll} style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
            ) : displayStocks.length === 0 ? (
              <Empty description={activePool ? '暂无匹配股票' : '请选择或创建观察池'} style={{ padding: 48 }} />
            ) : (
              <>
                {displayStocks.map(s => renderStockItem(s))}
                {hasMore && signalFilter === 'all' && (
                  <div style={{ textAlign: 'center', padding: 10 }}>
                    {loadingMore ? <Spin size="small" /> : <Button type="link" size="small" onClick={loadMore}>加载更多 ({stocks.length}/{total})</Button>}
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Right panel: detail */}
        <div style={{ flex: 1, minWidth: 0, padding: '12px 16px', overflowY: 'auto' }}>
          {renderDetailPanel()}
        </div>
      </div>

      {pools.length === 0 && !loading && (
        <div style={{ textAlign: 'center', padding: 48, color: '#999' }}>暂无观察池，点击上方「+ 新建」创建</div>
      )}

      {/* ===== Modals ===== */}

      <Modal title="添加股票" open={addModalOpen} onOk={handleAddStock} onCancel={() => { setAddModalOpen(false); setStockSearchOptions([]) }}>
        <Form form={addForm} layout="vertical">
          <Form.Item name="ts_code" label="股票" rules={[{ required: true, message: '请输入股票代码或名称' }]}>
            <AutoComplete options={stockSearchOptions} placeholder="输入代码或名称搜索" onSearch={handleStockSearch}
              notFoundContent={stockSearching ? '搜索中...' : stockSearchOptions.length === 0 ? '输入至少2个字符' : null} />
          </Form.Item>
          <Form.Item name="added_price" label="加入价格"><InputNumber style={{ width: '100%' }} placeholder="可选" /></Form.Item>
          <Form.Item name="note" label="备注"><Input.TextArea placeholder="可选" /></Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑观察池" open={editPoolModalOpen} onOk={handleEditPool} onCancel={() => setEditPoolModalOpen(false)} width={560}>
        <Form form={poolForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea /></Form.Item>
          <Form.Item name="trigger_target_pool_id" label="买点触发后加入">
            <Select allowClear placeholder="选择目标池" options={pools.filter(p => p.id !== activePoolId).map(p => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item label="监控规则">
            <div style={{ marginBottom: 8 }}>
              {poolRules.map(r => (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <span>{r.template_name || r.template_id || '组合'} {r.params && Object.keys(r.params).length > 0 && `(${JSON.stringify(r.params)})`}</span>
                  <Popconfirm title="确定删除？" onConfirm={() => handleDeleteRule(r.id)}><a style={{ color: '#ff4d4f', fontSize: 12 }}>删除</a></Popconfirm>
                </div>
              ))}
              {poolRules.length === 0 && <span style={{ color: '#999' }}>暂无规则</span>}
            </div>
            <Button size="small" type="dashed" onClick={() => { setAddRuleModalOpen(true); ruleForm.resetFields() }} block>添加规则</Button>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="添加买点规则" open={addRuleModalOpen} onOk={handleAddRule} onCancel={() => setAddRuleModalOpen(false)}>
        <Form form={ruleForm} layout="vertical" initialValues={{ template_id: 'ma_support', params: { n: 10 } }}>
          <Form.Item name="template_id" label="规则模板" rules={[{ required: true }]}>
            <Select placeholder="选择买点条件" options={monitorTemplates.map(t => ({ value: t.id, label: `${t.name} - ${t.description}` }))}
              onChange={v => { const t = monitorTemplates.find(x => x.id === v); ruleForm.setFieldsValue({ params: t?.default_params || {} }) }} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.template_id !== curr.template_id}>
            {({ getFieldValue }) => {
              const tid = getFieldValue('template_id')
              const t = monitorTemplates.find(x => x.id === tid)
              if (!t?.default_params) return null
              return <Form.Item name={['params', 'n']} label="均线周期" hidden={tid !== 'ma_support'}><InputNumber min={5} max={60} style={{ width: 100 }} /></Form.Item>
            }}
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.template_id !== curr.template_id}>
            {({ getFieldValue }) => {
              const tid = getFieldValue('template_id')
              return <>
                <Form.Item name={['params', 'tolerance']} label="容差" hidden={!['limit_up_price_support', 'fibonacci_retrace'].includes(tid)}>
                  <InputNumber min={0.01} max={0.2} step={0.01} style={{ width: 120 }} placeholder="0.03" />
                </Form.Item>
                <Form.Item name={['params', 'min_days']} label="最少天数" hidden={tid !== 'days_since_limit_up'}><InputNumber min={1} max={60} style={{ width: 100 }} /></Form.Item>
                <Form.Item name={['params', 'max_days']} label="最多天数" hidden={tid !== 'days_since_limit_up'}><InputNumber min={1} max={60} style={{ width: 100 }} /></Form.Item>
                <Form.Item name={['params', 'level']} label="黄金分割位" hidden={tid !== 'fibonacci_retrace'}>
                  <Select style={{ width: 120 }} options={[{ value: 0.382, label: '0.382' }, { value: 0.5, label: '0.5' }]} />
                </Form.Item>
              </>
            }}
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={`创建交易计划 - ${planStock?.stock_name || planStock?.ts_code || ''}`} open={planModalOpen}
        onOk={handleCreatePlan} onCancel={() => { setPlanModalOpen(false); setPlanStock(null) }} width={560}>
        <Form form={planForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}><Input placeholder="计划标题" /></Form.Item>
          <Form.Item name={['stocks', 0, 'ts_code']} hidden><Input /></Form.Item>
          <Form.Item noStyle shouldUpdate>
            {() => (
              <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 8 }}>
                <div style={{ marginBottom: 8 }}>股票：{planStock?.stock_name || planStock?.ts_code || '-'}</div>
                <Form.Item name={['stocks', 0, 'trigger_strategy']} label="触发策略">
                  <AutoComplete options={TRIGGER_OPTIONS.map(o => ({ value: o }))} placeholder="输入或选择" />
                </Form.Item>
                <Space wrap>
                  <Form.Item name={['stocks', 0, 'planned_buy_price']} label="买入价"><InputNumber style={{ width: 120 }} /></Form.Item>
                  <Form.Item name={['stocks', 0, 'target_price']} label="目标价"><InputNumber style={{ width: 120 }} /></Form.Item>
                  <Form.Item name={['stocks', 0, 'stop_loss_price']} label="止损价"><InputNumber style={{ width: 120 }} /></Form.Item>
                </Space>
                <Form.Item name={['stocks', 0, 'position_plan']} label="仓位(%)"><InputNumber min={0} max={100} addonAfter="%" style={{ width: 140 }} /></Form.Item>
                <Form.Item name={['stocks', 0, 'risk_level']} label="风险程度">
                  <Select style={{ width: 120 }} options={[{ value: 1, label: '低风险' }, { value: 2, label: '中风险' }, { value: 3, label: '高风险' }]} />
                </Form.Item>
                <Form.Item name={['stocks', 0, 'note']} label="备注"><Input.TextArea rows={2} /></Form.Item>
              </div>
            )}
          </Form.Item>
          <Form.Item name="note" label="计划备注"><Input.TextArea rows={2} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="CSV 批量导入" open={importModalOpen} footer={null} onCancel={() => setImportModalOpen(false)}>
        <p>CSV 格式：必须包含 <code>ts_code</code> 列。可选 <code>added_price</code>、<code>note</code></p>
        <Upload.Dragger accept=".csv" showUploadList={false} beforeUpload={file => { handleImport(file); return false }}>
          <p>点击或拖拽 CSV 文件到此处</p>
        </Upload.Dragger>
      </Modal>

      <Modal title="新建交易计划" open={createPlanModalOpen} onOk={handleCreatePlanFromToolbar}
        onCancel={() => { setCreatePlanModalOpen(false); createPlanForm.resetFields() }} width={900}>
        <Form form={createPlanForm} layout="vertical" initialValues={{ stocks: [{ risk_level: 2 }] }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}><Input placeholder="计划标题" /></Form.Item>
          <Form.Item name="note" label="计划备注"><Input.TextArea rows={2} /></Form.Item>
          <Form.Item label="股票列表">
            <Form.List name="stocks" rules={[{ validator: (_, v) => v?.length ? Promise.resolve() : Promise.reject('至少添加一只股票') }]}>
              {(fields, { add, remove }) => (<>
                <Table dataSource={fields} rowKey={f => String(f.key)} pagination={false} size="small" scroll={{ x: 1100 }} columns={[
                  { title: '股票', key: 'ts_code', width: 180, render: (_, __, i) => (
                    <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true, message: '请选择' }]}>
                      <Select showSearch placeholder="搜索" size="small" style={{ width: 160 }} options={stockOptions}
                        filterOption={(input, opt) => (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                    </Form.Item>
                  )},
                  { title: '策略', key: 'trigger_strategy', width: 130, render: (_, __, i) => (
                    <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle>
                      <AutoComplete options={TRIGGER_OPTIONS.map(o => ({ value: o }))} size="small" style={{ width: 120 }} />
                    </Form.Item>
                  )},
                  { title: '买入价', key: 'buy', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                  { title: '目标', key: 'target', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'target_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                  { title: '止损', key: 'sl', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                  { title: '仓位%', key: 'pos', width: 90, render: (_, __, i) => <Form.Item name={[fields[i].name, 'position_plan']} noStyle><InputNumber size="small" min={0} max={100} addonAfter="%" style={{ width: 80 }} /></Form.Item> },
                  { title: '风险', key: 'risk', width: 100, render: (_, __, i) => (
                    <Form.Item name={[fields[i].name, 'risk_level']} noStyle>
                      <Select size="small" style={{ width: 90 }} options={[{ value: 1, label: '低' }, { value: 2, label: '中' }, { value: 3, label: '高' }]} />
                    </Form.Item>
                  )},
                  { title: '备注', key: 'note', width: 100, render: (_, __, i) => <Form.Item name={[fields[i].name, 'note']} noStyle><Input size="small" /></Form.Item> },
                  { title: '', key: 'action', width: 40, render: (_, __, i) => fields.length > 1 ? <a onClick={() => remove(fields[i].name)} style={{ color: '#ff4d4f' }}>删</a> : null },
                ]} />
                <Button type="dashed" onClick={() => add({ risk_level: 2 })} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加股票</Button>
              </>)}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PoolList
