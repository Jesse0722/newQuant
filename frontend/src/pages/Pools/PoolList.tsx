import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Modal, Form, Input, InputNumber,
  Upload, message, Popconfirm, Select, AutoComplete,
} from 'antd'
import dayjs from 'dayjs'
import * as echarts from 'echarts'
import {
  listPools, createPool, updatePool, deletePool, reorderPools,
  listStocks, addStock, deleteStock, updateStock, importCSV, exportStocksCSV,
  getCoreWatchCodes, toggleCoreWatch,
} from '../../api/pools'
import { runStockAiAnalysis, runStockAiAnalysisTask, searchStocks } from '../../api/stocks'
import { getStockChartWithMarks } from '../../api/strategy'
import { syncPool } from '../../api/sync'
import { getPoolRules, createPoolRule, deleteRule, listTemplates } from '../../api/monitor'
import type {
  JsonObject, JsonValue, Pool, WatchStock, MonitorRule, MonitorTemplate,
  StockChartDataWithMarks,
} from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'
import PoolStockDetailPanel from './PoolStockDetailPanel'
import PoolStockListItem from './PoolStockListItem'
import PoolSidebar from './PoolSidebar'
import PoolToolbar from './PoolToolbar'
import MainWaveResearchPanel from './MainWaveResearchPanel'
import {
  getNotifications,
  subscribeNotifications,
  upsertNotification,
  type AppNotification,
} from '../../services/notificationCenter'

const PAGE_SIZE = 50
type ChartMark = Record<string, unknown>
type ChartSeries = Record<string, unknown>

interface CsvImportResult {
  imported: number
  skipped: number
}

const PoolList: React.FC = () => {
  const navigate = useNavigate()
  const { poolId: routePoolId } = useParams<{ poolId?: string }>()
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

  const [limitUpDateFrom, setLimitUpDateFrom] = useState<dayjs.Dayjs | null>(null)
  const [limitUpDateTo, setLimitUpDateTo] = useState<dayjs.Dayjs | null>(null)
  const [sortBy, setSortBy] = useState<'created_at' | 'limit_up_date'>('limit_up_date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  const [addModalOpen, setAddModalOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [editPoolModalOpen, setEditPoolModalOpen] = useState(false)
  const [noteModalOpen, setNoteModalOpen] = useState(false)
  const [noteEditingStockId, setNoteEditingStockId] = useState<string | null>(null)
  const [addRuleModalOpen, setAddRuleModalOpen] = useState(false)

  const [addForm] = Form.useForm()
  const [poolForm] = Form.useForm()
  const [noteForm] = Form.useForm()
  const [ruleForm] = Form.useForm()

  const [stockSearchOptions, setStockSearchOptions] = useState<Array<{ value: string; label: string }>>([])
  const [stockSearching, setStockSearching] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [poolRules, setPoolRules] = useState<MonitorRule[]>([])
  const [monitorTemplates, setMonitorTemplates] = useState<MonitorTemplate[]>([])
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [coreWatchCodes, setCoreWatchCodes] = useState<Set<string>>(new Set())
  const [coreWatchBusyTsCode, setCoreWatchBusyTsCode] = useState<string | null>(null)
  const [aiAnalyzingStockId, setAiAnalyzingStockId] = useState<string | null>(null)
  const [aiAnalyzingMode, setAiAnalyzingMode] = useState<'fast' | 'deep' | null>(null)

  const initialLoaded = useRef(false)
  const listRef = useRef<HTMLDivElement>(null)
  const chartDivRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const chartCacheRef = useRef<Map<string, StockChartDataWithMarks>>(new Map())
  const chartReqSeqRef = useRef(0)
  const processedNotificationKeysRef = useRef<Set<string>>(new Set())
  const selectedItemRef = useRef<HTMLDivElement>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const limitUpDateFromStr = limitUpDateFrom ? limitUpDateFrom.format('YYYYMMDD') : ''
  const limitUpDateToStr = limitUpDateTo ? limitUpDateTo.format('YYYYMMDD') : ''

  const [priceMin, setPriceMin] = useState<number | null>(null)
  const [priceMax, setPriceMax] = useState<number | null>(null)
  const [circMvMin, setCircMvMin] = useState<number | null>(null)
  const [circMvMax, setCircMvMax] = useState<number | null>(null)
  const [limitUpStatsFrom, setLimitUpStatsFrom] = useState<dayjs.Dayjs | null>(null)
  const [limitUpStatsTo, setLimitUpStatsTo] = useState<dayjs.Dayjs | null>(null)
  const [limitUpCountMin, setLimitUpCountMin] = useState<number | null>(null)
  const [limitUpCountMax, setLimitUpCountMax] = useState<number | null>(null)
  const [risingTrendOnly, setRisingTrendOnly] = useState(false)

  const limitUpStatsFromStr = limitUpStatsFrom ? limitUpStatsFrom.format('YYYYMMDD') : ''
  const limitUpStatsToStr = limitUpStatsTo ? limitUpStatsTo.format('YYYYMMDD') : ''
  const filtersRef = useRef({
    sortBy,
    sortOrder,
    limitUpDateFromStr,
    limitUpDateToStr,
    priceMin,
    priceMax,
    circMvMin,
    circMvMax,
    limitUpStatsFromStr,
    limitUpStatsToStr,
    limitUpCountMin,
    limitUpCountMax,
    risingTrendOnly,
  })
  filtersRef.current = {
    sortBy,
    sortOrder,
    limitUpDateFromStr,
    limitUpDateToStr,
    priceMin,
    priceMax,
    circMvMin,
    circMvMax,
    limitUpStatsFromStr,
    limitUpStatsToStr,
    limitUpCountMin,
    limitUpCountMax,
    risingTrendOnly,
  }
  const anyModalOpenRef = useRef(false)
  anyModalOpenRef.current = addModalOpen || importModalOpen || editPoolModalOpen || noteModalOpen || addRuleModalOpen

  /* ===== Computed ===== */

  const activePool = pools.find(p => p.id === activePoolId)
  const isMainWavePool = useMemo(() => {
    const text = `${activePool?.name || ''} ${activePool?.description || ''}`
    return text.includes('主升浪')
  }, [activePool?.description, activePool?.name])

  const selectedStock = stocks.find(s => s.ts_code === selectedCode) || null
  const selectedIndex = stocks.findIndex(s => s.ts_code === selectedCode)
  const hasMore = stocks.length > 0 && stocks.length < total
  const selectedLimitUpDate = selectedStock?.limit_up_date || undefined

  /* ===== Data Fetching ===== */

  const refreshCoreWatch = useCallback(() => {
    getCoreWatchCodes()
      .then(res => setCoreWatchCodes(new Set(res.data.ts_codes || [])))
      .catch(() => {})
  }, [])

  const fetchPools = useCallback(async () => {
    const res = await listPools()
    setPools(res.data)
    return res.data
  }, [])

  const handleToggleCoreWatch = async (stock: WatchStock, starred: boolean) => {
    setCoreWatchBusyTsCode(stock.ts_code)
    try {
      await toggleCoreWatch({
        ts_code: stock.ts_code,
        starred,
        limit_up_date: stock.limit_up_date || undefined,
      })
      setCoreWatchCodes(prev => {
        const next = new Set(prev)
        if (starred) next.add(stock.ts_code)
        else next.delete(stock.ts_code)
        return next
      })
      message.success(starred ? '已加入「核心关注」股票池' : '已取消特别关注')
      fetchPools().catch(() => {})
    } catch {
      message.error('操作失败，请重试')
    } finally {
      setCoreWatchBusyTsCode(null)
    }
  }

  const fetchPage = async (poolId: string, pageNum: number) => {
    const f = filtersRef.current
    const params: Record<string, string | number> = {
      page: pageNum, size: PAGE_SIZE, sort_by: f.sortBy, order: f.sortOrder,
    }
    if (f.limitUpDateFromStr) params.limit_up_date_from = f.limitUpDateFromStr
    if (f.limitUpDateToStr) params.limit_up_date_to = f.limitUpDateToStr
    if (f.priceMin != null) params.price_min = f.priceMin
    if (f.priceMax != null) params.price_max = f.priceMax
    if (f.circMvMin != null) params.circ_mv_min = f.circMvMin
    if (f.circMvMax != null) params.circ_mv_max = f.circMvMax
    if (f.limitUpStatsFromStr) params.limit_up_stats_from = f.limitUpStatsFromStr
    if (f.limitUpStatsToStr) params.limit_up_stats_to = f.limitUpStatsToStr
    if (f.limitUpStatsFromStr && f.limitUpStatsToStr) {
      if (f.limitUpCountMin != null) params.limit_up_count_min = f.limitUpCountMin
      if (f.limitUpCountMax != null) params.limit_up_count_max = f.limitUpCountMax
    }
    if (f.risingTrendOnly) params.rising_trend = 1
    return listStocks(poolId, params)
  }

  const loadInitial = useCallback(async (poolId: string) => {
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
  }, [])

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

  /* ===== Effects ===== */

  useEffect(() => {
    refreshCoreWatch()
    fetchPools().then(data => {
      if (!initialLoaded.current && data.length > 0) {
        const routedPool = routePoolId ? data.find(pool => pool.id === routePoolId) : null
        const nextPoolId = routedPool?.id || data[0].id
        setActivePoolId(nextPoolId)
        if (!routePoolId || !routedPool) {
          navigate(`/pools/${nextPoolId}`, { replace: true })
        }
        initialLoaded.current = true
      }
    })
  }, [fetchPools, navigate, refreshCoreWatch, routePoolId])

  useEffect(() => {
    if (!initialLoaded.current || !routePoolId || routePoolId === activePoolId) return
    if (pools.some(pool => pool.id === routePoolId)) {
      setActivePoolId(routePoolId)
    }
  }, [activePoolId, pools, routePoolId])

  const selectPool = useCallback((poolId: string) => {
    setActivePoolId(poolId)
    navigate(`/pools/${poolId}`)
  }, [navigate])

  useEffect(() => {
    const completionKey = (item: AppNotification) => `${item.id}:${item.status}:${item.updatedAt}`
    getNotifications()
      .filter((item) => item.status === 'success')
      .forEach((item) => processedNotificationKeysRef.current.add(completionKey(item)))

    return subscribeNotifications((items: AppNotification[]) => {
      const completed = items.filter((item) =>
        item.status === 'success' &&
        !processedNotificationKeysRef.current.has(completionKey(item)) &&
        (
          (item.kind === 'stock_ai_analysis' && item.meta?.watchStockId && item.meta.result?.analysis) ||
          (item.kind === 'sync_task' && item.meta?.tsCode === activePoolId)
        )
      )
      if (!completed.length) return
      completed.forEach((item) => processedNotificationKeysRef.current.add(completionKey(item)))
      if (completed.some((item) => item.kind === 'sync_task' && item.meta?.tsCode === activePoolId)) {
        loadInitial(activePoolId)
        fetchPools().catch(() => {})
      }
      setStocks(prev => prev.map((stock) => {
        const item = completed.find((n) => n.kind === 'stock_ai_analysis' && n.meta?.watchStockId === stock.id)
        if (!item?.meta?.result) return stock
        return {
          ...stock,
          ai_analysis: JSON.stringify(item.meta.result.analysis, null, 2),
          ai_analyzed_at: item.meta.result.ai_analyzed_at || stock.ai_analyzed_at,
        }
      }))
    })
  }, [activePoolId, fetchPools, loadInitial])

  useEffect(() => {
    if (activePoolId) loadInitial(activePoolId)
  }, [
    activePoolId,
    loadInitial,
    limitUpDateFromStr,
    limitUpDateToStr,
    sortBy,
    sortOrder,
    priceMin,
    priceMax,
    circMvMin,
    circMvMax,
    limitUpStatsFromStr,
    limitUpStatsToStr,
    limitUpCountMin,
    limitUpCountMax,
    risingTrendOnly,
  ])

  useEffect(() => {
    const exists = stocks.some(s => s.ts_code === selectedCode)
    if (!exists && stocks.length > 0) setSelectedCode(stocks[0].ts_code)
  }, [stocks, selectedCode])

  useEffect(() => {
    if (!selectedCode) return
    const cacheKey = `${selectedCode}|${chartPeriod}|${selectedLimitUpDate || ''}`
    const cached = chartCacheRef.current.get(cacheKey)
    if (cached) {
      setChartData(cached)
      setChartLoading(false)
      return
    }
    const reqSeq = ++chartReqSeqRef.current
    setChartLoading(true)
    getStockChartWithMarks(selectedCode, chartPeriod, selectedLimitUpDate)
      .then(res => {
        if (reqSeq !== chartReqSeqRef.current) return
        chartCacheRef.current.set(cacheKey, res.data)
        // 轻量 LRU：限制缓存数量，避免无上限增长
        if (chartCacheRef.current.size > 120) {
          const oldestKey = chartCacheRef.current.keys().next().value
          if (oldestKey) chartCacheRef.current.delete(oldestKey)
        }
        setChartData(res.data)
      })
      .catch(() => {
        if (reqSeq !== chartReqSeqRef.current) return
        setChartData(null)
      })
      .finally(() => {
        if (reqSeq !== chartReqSeqRef.current) return
        setChartLoading(false)
      })
  }, [selectedCode, chartPeriod, selectedLimitUpDate])

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

      const markPoints: ChartMark[] = []
      const markLines: ChartMark[] = []
      const addedDate = selectedStock?.added_at ? dayjs(selectedStock.added_at).format('YYYYMMDD') : ''
      if (addedDate && dates.includes(addedDate)) {
        const addedQuote = quotes.find(q => q.date === addedDate)
        const addedY = addedQuote?.low ?? addedQuote?.close
        if (typeof addedY === 'number' && Number.isFinite(addedY) && addedY > 0) {
        markPoints.push({
          name: '加入池时间',
          coord: [addedDate, addedY],
          symbol: 'circle',
          symbolSize: 12,
          itemStyle: { color: '#1677ff' },
          label: {
            show: true,
            formatter: '自',
            position: 'bottom',
            fontSize: 10,
            color: '#1677ff',
            fontWeight: 'bold',
          },
        })
        }
      }
      if (signal_marks) {
        for (const mark of signal_marks) {
          const value = mark.value
          if (mark.type === 'life_line' && typeof value === 'number') {
            markLines.push({
              name: mark.label, yAxis: value,
              lineStyle: { color: '#722ed1', type: 'dashed', width: 1.5 },
              label: { formatter: `${mark.label} ${value.toFixed(2)}`, color: '#722ed1', fontSize: 11 },
            })
          }
          if (mark.type === 'phase2_high' && dates.includes(mark.date) && typeof value === 'number' && Number.isFinite(value) && value > 0) {
            markPoints.push({
              name: mark.label, coord: [mark.date, value],
              symbol: 'triangle', symbolSize: 10, symbolRotate: 180,
              itemStyle: { color: '#faad14' },
              label: { show: true, formatter: mark.label, position: 'top', fontSize: 10, color: '#faad14' },
            })
          }
          if (mark.type === 'buy_signal' && dates.includes(mark.date) && typeof value === 'number' && Number.isFinite(value) && value > 0) {
            markPoints.push({
              name: mark.label, coord: [mark.date, value],
              symbol: 'triangle', symbolSize: 12,
              itemStyle: { color: '#f5222d' },
              label: { show: true, formatter: mark.label, position: 'bottom', fontSize: 10, color: '#f5222d', fontWeight: 'bold' },
            })
          }
        }
      }

      const candleSeries: ChartSeries = {
        name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
      }
      if (markPoints.length > 0) candleSeries.markPoint = { data: markPoints }
      if (markLines.length > 0) candleSeries.markLine = { data: markLines, silent: true, symbol: 'none' }

      const series: ChartSeries[] = [
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
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: makeKlineAxisTooltipFormatter(quotes),
        },
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
  }, [chartData, subIndicator, selectedCode, selectedStock?.added_at])

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
      const idx = stocks.findIndex(s => s.ts_code === selectedCode)
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        if (idx < stocks.length - 1) setSelectedCode(stocks[idx + 1].ts_code)
        else if (hasMore) loadMore()
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        if (idx > 0) setSelectedCode(stocks[idx - 1].ts_code)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [stocks, selectedCode, hasMore, loadMore])

  useEffect(() => {
    selectedItemRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selectedCode])

  useEffect(() => {
    if (selectedIndex >= stocks.length - 5 && hasMore && !loadingMore) loadMore()
  }, [selectedIndex, stocks.length, hasMore, loadingMore, loadMore])

  /* ===== Handlers ===== */

  const handleAddPool = async () => {
    const res = await createPool({ name: `新观察池 ${pools.length + 1}` })
    await fetchPools()
    selectPool(res.data.id)
    message.success('已创建')
  }

  const handleCreateMainWavePool = async () => {
    const existing = pools.find(pool => `${pool.name} ${pool.description || ''}`.includes('主升浪'))
    if (existing) {
      selectPool(existing.id)
      message.info('已切换到主升浪样本库')
      return
    }
    const res = await createPool({
      name: '主升浪样本库',
      description: '主升浪趋势结构、MA20修复与板块共振研究池',
    })
    await fetchPools()
    selectPool(res.data.id)
    message.success('已创建主升浪样本库')
  }

  const handleDeletePool = (poolId: string) => {
    Modal.confirm({
      title: '确定删除该观察池？', content: '池内所有股票将一并删除',
      onOk: async () => {
        await deletePool(poolId)
        const updated = await fetchPools()
        if (activePoolId === poolId) {
          const nextPoolId = updated.length > 0 ? updated[0].id : ''
          if (nextPoolId) selectPool(nextPoolId)
          else {
            setActivePoolId('')
            navigate('/pools', { replace: true })
          }
        }
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
    const payload = {
      ...values,
      name: String(values.name || '').trim(),
      description: values.description ? String(values.description).trim() : undefined,
    }
    if (!payload.name) {
      message.warning('请输入观察池名称')
      return
    }
    try {
      const res = await updatePool(activePoolId, payload)
      setPools(prev => prev.map(pool => (
        pool.id === activePoolId ? { ...pool, ...res.data } : pool
      )))
      message.success('观察池已更新')
      setEditPoolModalOpen(false)
    } catch (error: unknown) {
      const apiError = error as { response?: { data?: { message?: string } } }
      message.error(apiError.response?.data?.message || '观察池更新失败')
    }
  }

  const handleAddRule = async () => {
    const values = await ruleForm.validateFields()
    const template = monitorTemplates.find(t => t.id === values.template_id)
    const merged: JsonObject = template?.default_params ? { ...template.default_params } : {}
    Object.entries(values.params || {}).forEach(([k, v]) => { if (v != null && v !== '') merged[k] = v as JsonValue })
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
    const r = res.data as CsvImportResult
    message.success(`导入 ${r.imported} 只，跳过 ${r.skipped} 只`)
    setImportModalOpen(false)
    loadInitial(activePoolId)
    fetchPools()
    return false
  }

  const handleExport = async () => {
    if (!activePoolId || !activePool) return
    const f = filtersRef.current
    const params: Record<string, string | number> = {
      sort_by: f.sortBy,
      order: f.sortOrder,
    }
    if (f.limitUpDateFromStr) params.limit_up_date_from = f.limitUpDateFromStr
    if (f.limitUpDateToStr) params.limit_up_date_to = f.limitUpDateToStr
    if (f.priceMin != null) params.price_min = f.priceMin
    if (f.priceMax != null) params.price_max = f.priceMax
    if (f.circMvMin != null) params.circ_mv_min = f.circMvMin
    if (f.circMvMax != null) params.circ_mv_max = f.circMvMax
    if (f.limitUpStatsFromStr) params.limit_up_stats_from = f.limitUpStatsFromStr
    if (f.limitUpStatsToStr) params.limit_up_stats_to = f.limitUpStatsToStr
    if (f.limitUpStatsFromStr && f.limitUpStatsToStr) {
      if (f.limitUpCountMin != null) params.limit_up_count_min = f.limitUpCountMin
      if (f.limitUpCountMax != null) params.limit_up_count_max = f.limitUpCountMax
    }
    if (f.risingTrendOnly) params.rising_trend = 1
    const res = await exportStocksCSV(activePoolId, params)
    const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8;' })
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${activePool.name || 'watch_pool'}_stocks.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
    message.success('导出成功')
  }

  const handleSync = async () => {
    if (!activePoolId) return
    setSyncing(true)
    try {
      const res = await syncPool(activePoolId)
      const now = new Date().toISOString()
      upsertNotification({
        id: `sync-task:${res.data.task_id}`,
        kind: 'sync_task',
        status: 'running',
        title: `${activePool?.name || '股票池'} 同步中`,
        description: '任务已提交，完成后会在顶部消息中心提醒',
        createdAt: now,
        updatedAt: now,
        read: false,
        taskId: res.data.task_id,
        link: '/pools',
        meta: {
          tsCode: activePoolId,
          stockName: activePool?.name || '股票池',
        },
      })
      message.success('同步任务已提交，可稍后在顶部消息中心查看')
    } catch {
      message.error('同步任务提交失败')
    } finally {
      setSyncing(false)
    }
  }

  const handleTogglePin = async (stock: WatchStock) => {
    await updateStock(activePoolId, stock.id, { pinned: !stock.pinned })
    setStocks(prev => prev.map(s => s.id === stock.id ? { ...s, pinned: !s.pinned } : s))
  }

  const openNoteModal = () => {
    if (!selectedStock) return
    setNoteEditingStockId(selectedStock.id)
    noteForm.setFieldsValue({ note: selectedStock.note || '' })
    setNoteModalOpen(true)
  }

  const handleSaveNote = async () => {
    const sid = noteEditingStockId
    if (!sid || !activePoolId) return
    const stock = stocks.find(s => s.id === sid)
    if (!stock) return
    const values = await noteForm.validateFields()
    const noteVal = (values.note as string)?.trim() || undefined
    await updateStock(activePoolId, sid, { note: noteVal })
    setStocks(prev => prev.map(s => (s.id === sid ? { ...s, note: noteVal } : s)))
    message.success('备注已保存')
    setNoteModalOpen(false)
    setNoteEditingStockId(null)
  }

  const handleAnalyzeStock = async (mode: 'fast' | 'deep') => {
    if (!selectedStock || !activePoolId) return
    setAiAnalyzingStockId(selectedStock.id)
    setAiAnalyzingMode(mode)
    try {
      if (mode === 'deep') {
        const res = await runStockAiAnalysisTask(selectedStock.ts_code, {
          mode,
          scope: 'watch_pool',
          pool_id: activePoolId,
          watch_stock_id: selectedStock.id,
          force_refresh: true,
        })
        const now = new Date().toISOString()
        upsertNotification({
          id: `stock-ai-analysis:${res.data.task_id}`,
          kind: 'stock_ai_analysis',
          status: 'running',
          title: `${selectedStock.stock_name || selectedStock.ts_code} 深度分析中`,
          description: '任务已提交，完成后会在顶部消息中心提醒',
          createdAt: now,
          updatedAt: now,
          read: false,
          taskId: res.data.task_id,
          link: `/stocks/${selectedStock.ts_code}`,
          meta: {
            tsCode: selectedStock.ts_code,
            stockName: selectedStock.stock_name,
            watchStockId: selectedStock.id,
            mode,
          },
        })
        message.success('深度分析已提交，可稍后在顶部消息中心查看')
        return
      }
      const res = await runStockAiAnalysis(selectedStock.ts_code, {
        mode,
        scope: 'watch_pool',
        pool_id: activePoolId,
        watch_stock_id: selectedStock.id,
        force_refresh: true,
      })
      const analysisText = JSON.stringify(res.data.analysis, null, 2)
      const analyzedAt = res.data.ai_analyzed_at || undefined
      setStocks(prev => prev.map(s => (
        s.id === selectedStock.id
          ? { ...s, ai_analysis: analysisText, ai_analyzed_at: analyzedAt }
          : s
      )))
      message.success(mode === 'fast' ? '快速分析完成' : '深度分析完成')
    } catch (error: unknown) {
      const maybeResponse = (error as { response?: { data?: { message?: string } } }).response
      const msg = maybeResponse?.data?.message || 'AI 分析失败，请稍后重试'
      message.error(msg)
    } finally {
      setAiAnalyzingStockId(null)
      setAiAnalyzingMode(null)
    }
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

  const renderStockItem = (stock: WatchStock) => {
    const isSelected = stock.ts_code === selectedCode
    const starred = coreWatchCodes.has(stock.ts_code)
    const selectedRef = isSelected ? selectedItemRef : undefined

    return (
      <PoolStockListItem
        key={stock.id}
        stock={stock}
        isSelected={isSelected}
        isStarred={starred}
        isStarBusy={coreWatchBusyTsCode === stock.ts_code}
        onSelect={setSelectedCode}
        onToggleCoreWatch={handleToggleCoreWatch}
        selectedItemRef={selectedRef}
      />
    )
  }

  /* ===== Main return ===== */

  return (
    <div style={{ height: 'calc(100vh - 112px)', display: 'flex', flexDirection: 'column' }}>
      <PoolToolbar
        activePool={activePool}
        activePoolId={activePoolId}
        dragOverIndex={dragOverIndex}
        onAddPool={handleAddPool}
        onCreateMainWavePool={handleCreateMainWavePool}
        onDeletePool={handleDeletePool}
        onDragEnd={handleTabDragEnd}
        onDragLeave={handleTabDragLeave}
        onDragOver={handleTabDragOver}
        onDragStart={handleTabDragStart}
        onDrop={handleTabDrop}
        onEditPool={openEditPoolModal}
        onReload={() => loadInitial(activePoolId)}
        onSelectPool={selectPool}
        onSync={handleSync}
        pools={pools}
        syncing={syncing}
      />

      {/* Main body: left-right split */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, border: '1px solid var(--border-default)', borderRadius: 10, background: 'var(--bg-card)', overflow: 'hidden' }}>
        {!isMainWavePool && (
        <PoolSidebar
          activePool={activePool}
          circMvMax={circMvMax}
          circMvMin={circMvMin}
          hasMore={hasMore}
          limitUpCountMax={limitUpCountMax}
          limitUpCountMin={limitUpCountMin}
          limitUpDateFrom={limitUpDateFrom}
          limitUpDateTo={limitUpDateTo}
          limitUpStatsFrom={limitUpStatsFrom}
          limitUpStatsTo={limitUpStatsTo}
          listRef={listRef}
          loading={loading}
          loadingMore={loadingMore}
          onAddStock={() => setAddModalOpen(true)}
          onExport={handleExport}
          onImport={() => setImportModalOpen(true)}
          onListScroll={onListScroll}
          onLoadMore={loadMore}
          onRenderStockItem={renderStockItem}
          onSetCircMvMax={setCircMvMax}
          onSetCircMvMin={setCircMvMin}
          onSetLimitUpCountMax={setLimitUpCountMax}
          onSetLimitUpCountMin={setLimitUpCountMin}
          onSetLimitUpDateFrom={setLimitUpDateFrom}
          onSetLimitUpDateTo={setLimitUpDateTo}
          onSetLimitUpStatsFrom={setLimitUpStatsFrom}
          onSetLimitUpStatsTo={setLimitUpStatsTo}
          onSetPriceMax={setPriceMax}
          onSetPriceMin={setPriceMin}
          onSetRisingTrendOnly={setRisingTrendOnly}
          onSetSort={(nextSortBy, nextSortOrder) => {
            setSortBy(nextSortBy)
            setSortOrder(nextSortOrder)
          }}
          priceMax={priceMax}
          priceMin={priceMin}
          risingTrendOnly={risingTrendOnly}
          sortBy={sortBy}
          sortOrder={sortOrder}
          stocks={stocks}
          total={total}
        />
        )}

        {/* Right panel: detail */}
        <div style={{ flex: 1, minWidth: 0, padding: '12px 16px', overflowY: 'auto' }}>
          {isMainWavePool ? (
            <MainWaveResearchPanel
              chartData={chartData}
              chartLoading={chartLoading}
              onAddStock={() => setAddModalOpen(true)}
              onDeleteStock={handleDeleteStock}
              onEditNote={openNoteModal}
              onExport={handleExport}
              onImport={() => setImportModalOpen(true)}
              onSelectStock={setSelectedCode}
              onTogglePin={handleTogglePin}
              selectedStock={selectedStock}
              stocks={stocks}
            />
          ) : (
            <PoolStockDetailPanel
              aiAnalyzingMode={aiAnalyzingMode}
              aiAnalyzingStockId={aiAnalyzingStockId}
              chartData={chartData}
              chartLoading={chartLoading}
              chartPeriod={chartPeriod}
              chartRef={chartDivRef}
              coreWatchBusyTsCode={coreWatchBusyTsCode}
              coreWatchCodes={coreWatchCodes}
              onAnalyzeStock={handleAnalyzeStock}
              onDeleteStock={handleDeleteStock}
              onEditNote={openNoteModal}
              onSetChartPeriod={setChartPeriod}
              onSetSubIndicator={setSubIndicator}
              onToggleCoreWatch={handleToggleCoreWatch}
              onTogglePin={handleTogglePin}
              selectedStock={selectedStock}
              subIndicator={subIndicator}
            />
          )}
        </div>
      </div>

      {pools.length === 0 && !loading && (
        <div style={{ textAlign: 'center', padding: 48, color: 'var(--text-muted)' }}>暂无观察池，点击上方「+ 新建」创建</div>
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

      <Modal
        title="编辑股票备注"
        open={noteModalOpen}
        onOk={handleSaveNote}
        onCancel={() => { setNoteModalOpen(false); setNoteEditingStockId(null); noteForm.resetFields() }}
        destroyOnClose
      >
        <Form form={noteForm} layout="vertical">
          <Form.Item name="note" label="备注内容">
            <Input.TextArea rows={6} placeholder="记录看盘要点、策略思路等" showCount maxLength={2000} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="CSV 批量导入" open={importModalOpen} footer={null} onCancel={() => setImportModalOpen(false)}>
        <p>CSV 格式：必须包含 <code>ts_code</code> 列。可选 <code>added_price</code>、<code>note</code></p>
        <Upload.Dragger accept=".csv" showUploadList={false} beforeUpload={file => { handleImport(file); return false }}>
          <p>点击或拖拽 CSV 文件到此处</p>
        </Upload.Dragger>
      </Modal>

    </div>
  )
}

export default PoolList
