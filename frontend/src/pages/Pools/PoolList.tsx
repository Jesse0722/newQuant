import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  Button, Modal, Form, Input, InputNumber, Space, Card,
  Tag, Upload, message, Popconfirm, Select, AutoComplete,
  Segmented, Spin, Empty, Dropdown,
  DatePicker, Tooltip, Progress,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, SyncOutlined, ReloadOutlined,
  PushpinFilled, PushpinOutlined, HolderOutlined,
  DownOutlined, StarFilled, StarOutlined,
  EditOutlined, DeleteOutlined, RobotOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import * as echarts from 'echarts'
import {
  listPools, createPool, updatePool, deletePool, reorderPools,
  listStocks, addStock, deleteStock, updateStock, importCSV, exportStocksCSV,
  getCoreWatchCodes, toggleCoreWatch,
} from '../../api/pools'
import { searchStocks } from '../../api/stocks'
import { aiAnalyzeStock, getStockChartWithMarks } from '../../api/strategy'
import { syncPool, getTaskStatus } from '../../api/sync'
import { getPoolRules, createPoolRule, deleteRule, listTemplates } from '../../api/monitor'
import type {
  Pool, WatchStock, MonitorRule, MonitorTemplate,
  StockChartDataWithMarks, AiAnalysisResult,
} from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'

const PAGE_SIZE = 50

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

  const initialLoaded = useRef(false)
  const listRef = useRef<HTMLDivElement>(null)
  const chartDivRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const selectedItemRef = useRef<HTMLDivElement>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const limitUpDateFromStr = limitUpDateFrom ? limitUpDateFrom.format('YYYYMMDD') : ''
  const limitUpDateToStr = limitUpDateTo ? limitUpDateTo.format('YYYYMMDD') : ''
  const filtersRef = useRef({ sortBy, sortOrder, limitUpDateFromStr, limitUpDateToStr })
  filtersRef.current = { sortBy, sortOrder, limitUpDateFromStr, limitUpDateToStr }
  const anyModalOpenRef = useRef(false)
  anyModalOpenRef.current = addModalOpen || importModalOpen || editPoolModalOpen || noteModalOpen || addRuleModalOpen

  /* ===== Computed ===== */

  const activePool = pools.find(p => p.id === activePoolId)

  const selectedStock = stocks.find(s => s.ts_code === selectedCode) || null
  const selectedIndex = stocks.findIndex(s => s.ts_code === selectedCode)
  const hasMore = stocks.length > 0 && stocks.length < total

  /* ===== Data Fetching ===== */

  const refreshCoreWatch = useCallback(() => {
    getCoreWatchCodes()
      .then(res => setCoreWatchCodes(new Set(res.data.ts_codes || [])))
      .catch(() => {})
  }, [])

  const fetchPools = async () => {
    const res = await listPools()
    setPools(res.data)
    return res.data
  }

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

  /* ===== Effects ===== */

  useEffect(() => {
    refreshCoreWatch()
    fetchPools().then(data => {
      if (!initialLoaded.current && data.length > 0) {
        setActivePoolId(data[0].id)
        initialLoaded.current = true
      }
    })
  }, [refreshCoreWatch])

  useEffect(() => {
    if (activePoolId) loadInitial(activePoolId)
  }, [activePoolId, limitUpDateFromStr, limitUpDateToStr, sortBy, sortOrder])

  useEffect(() => {
    const exists = stocks.some(s => s.ts_code === selectedCode)
    if (!exists && stocks.length > 0) setSelectedCode(stocks[0].ts_code)
  }, [stocks, selectedCode])

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

  const handleExport = async () => {
    if (!activePoolId || !activePool) return
    const f = filtersRef.current
    const params: {
      sort_by: 'created_at' | 'limit_up_date'
      order: 'asc' | 'desc'
      limit_up_date_from?: string
      limit_up_date_to?: string
    } = {
      sort_by: f.sortBy,
      order: f.sortOrder,
    }
    if (f.limitUpDateFromStr) params.limit_up_date_from = f.limitUpDateFromStr
    if (f.limitUpDateToStr) params.limit_up_date_to = f.limitUpDateToStr
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

  const handleAnalyzeStock = async () => {
    if (!selectedStock || !activePoolId) return
    setAiAnalyzingStockId(selectedStock.id)
    try {
      const res = await aiAnalyzeStock({ ts_code: selectedStock.ts_code, stock_id: selectedStock.id })
      const analysisText = JSON.stringify(res.data.analysis, null, 2)
      const analyzedAt = res.data.ai_analyzed_at
      setStocks(prev => prev.map(s => (
        s.id === selectedStock.id
          ? { ...s, ai_analysis: analysisText, ai_analyzed_at: analyzedAt }
          : s
      )))
      message.success('AI 分析完成')
    } catch (e: any) {
      const msg = e?.response?.data?.message || 'AI 分析失败，请稍后重试'
      message.error(msg)
    } finally {
      setAiAnalyzingStockId(null)
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

  const fmtLimitDate = (d?: string) => d ? `${d.slice(4, 6)}-${d.slice(6)}` : ''
  const parseAiAnalysis = (raw?: string): AiAnalysisResult | null => {
    if (!raw) return null
    try {
      return JSON.parse(raw) as AiAnalysisResult
    } catch {
      return null
    }
  }

  const trendColor = (trend?: string) => {
    if (trend === '上涨') return 'green'
    if (trend === '下跌') return 'red'
    return 'default'
  }

  /* ===== Render: Left panel stock item ===== */

  const renderStockItem = (stock: WatchStock) => {
    const isSelected = stock.ts_code === selectedCode
    const borderColor = isSelected ? '#1677ff' : 'transparent'
    const starred = coreWatchCodes.has(stock.ts_code)
    const starBusy = coreWatchBusyTsCode === stock.ts_code

    return (
      <div
        key={stock.id}
        ref={isSelected ? selectedItemRef : undefined}
        onClick={() => setSelectedCode(stock.ts_code)}
        tabIndex={0}
        style={{
          padding: '10px 14px',
          cursor: 'pointer',
          borderLeft: `3px solid ${borderColor}`,
          background: isSelected ? '#f0f5ff' : 'transparent',
          borderBottom: '1px solid #f0f0f0',
          transition: 'background 0.15s',
        }}
        onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '#fafafa' }}
        onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = isSelected ? '#f0f5ff' : 'transparent' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 14 }}>
            <Tooltip title={starred ? '取消特别关注（从核心关注移除）' : '加入核心关注'}>
              <span
                role="button"
                tabIndex={0}
                onClick={e => {
                  e.stopPropagation()
                  if (!starBusy) handleToggleCoreWatch(stock, !starred)
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    e.stopPropagation()
                    if (!starBusy) handleToggleCoreWatch(stock, !starred)
                  }
                }}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  color: starred ? '#faad14' : '#d9d9d9',
                  cursor: starBusy ? 'wait' : 'pointer',
                  opacity: starBusy ? 0.5 : 1,
                }}
              >
                {starred ? <StarFilled /> : <StarOutlined />}
              </span>
            </Tooltip>
            {stock.stock_name || '-'}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 12 }} />}
          </span>
        </div>

        <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>
          {stock.ts_code} {stock.industry ? `· ${stock.industry}` : ''}
          {stock.limit_up_date && <span style={{ marginLeft: 6 }}>涨停 {fmtLimitDate(stock.limit_up_date)}</span>}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
          <span style={{ fontFamily: "'Menlo', monospace", fontWeight: 600 }}>
            {stock.latest_price != null ? stock.latest_price.toFixed(2) : '-'}
          </span>
          {stock.pct_chg != null && (
            <span style={{ fontWeight: 600, color: stock.pct_chg > 0 ? '#cf1322' : stock.pct_chg < 0 ? '#3f8600' : '#666' }}>
              {stock.pct_chg > 0 ? '+' : ''}{stock.pct_chg.toFixed(2)}%
            </span>
          )}
        </div>
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

    const ai = parseAiAnalysis(selectedStock.ai_analysis)

    return (
      <div style={{ overflowY: 'auto', height: '100%', padding: '0 0 16px' }}>
        {/* Info header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Tooltip title={coreWatchCodes.has(selectedStock.ts_code) ? '取消特别关注' : '加入核心关注'}>
              <Button
                type="text"
                size="large"
                loading={coreWatchBusyTsCode === selectedStock.ts_code}
                icon={
                  coreWatchCodes.has(selectedStock.ts_code)
                    ? <StarFilled style={{ color: '#faad14', fontSize: 22 }} />
                    : <StarOutlined style={{ fontSize: 22, color: '#bfbfbf' }} />
                }
                onClick={() =>
                  coreWatchBusyTsCode !== selectedStock.ts_code &&
                  handleToggleCoreWatch(selectedStock, !coreWatchCodes.has(selectedStock.ts_code))
                }
                style={{ padding: '4px 8px' }}
              />
            </Tooltip>
            <span style={{ fontSize: 18, fontWeight: 700 }}>{selectedStock.stock_name || selectedStock.ts_code}</span>
            <span style={{ fontSize: 14, color: '#8c8c8c' }}>{selectedStock.ts_code}</span>
            {selectedStock.industry && <Tag>{selectedStock.industry}</Tag>}
          </div>
          <Space size={4}>
            <Tooltip title={selectedStock.pinned ? '取消置顶' : '置顶'}>
              <Button
                type="text"
                size="small"
                icon={selectedStock.pinned ? <PushpinFilled style={{ color: '#faad14' }} /> : <PushpinOutlined />}
                onClick={() => handleTogglePin(selectedStock)}
              />
            </Tooltip>
            <Tooltip title="从本池移除">
              <Popconfirm title="确定从本池移除该股票？" onConfirm={() => handleDeleteStock(selectedStock.id)}>
                <Button type="text" size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </Tooltip>
          </Space>
        </div>

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

        {/* 股票备注 */}
        <Card
          size="small"
          title={<span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>股票备注</span>}
          extra={
            <Tooltip title="编辑备注">
              <Button type="text" size="small" icon={<EditOutlined />} onClick={openNoteModal} />
            </Tooltip>
          }
          style={{
            marginTop: 12,
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            boxShadow: 'none',
          }}
          styles={{ body: { paddingTop: 12 } }}
        >
          <div
            style={{
              minHeight: 80,
              whiteSpace: 'pre-wrap',
              lineHeight: 1.6,
              fontSize: 14,
              color: selectedStock.note?.trim() ? '#262626' : '#bfbfbf',
            }}
          >
            {selectedStock.note?.trim() ? selectedStock.note : '暂无备注'}
          </div>
        </Card>

        <Card
          size="small"
          title={<span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>AI 智能分析</span>}
          extra={
            <Tooltip title="分析当前股票">
              <Button
                type="text"
                size="small"
                icon={<RobotOutlined />}
                loading={aiAnalyzingStockId === selectedStock.id}
                onClick={handleAnalyzeStock}
              />
            </Tooltip>
          }
          style={{
            marginTop: 12,
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 8,
            boxShadow: 'none',
          }}
          styles={{ body: { paddingTop: 12 } }}
        >
          {!ai ? (
            <div style={{ color: '#8c8c8c', minHeight: 80, lineHeight: 1.8 }}>
              点击右上角按钮进行 AI 分析，结果将独立保存，不覆盖手动备注。
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Progress
                  type="dashboard"
                  size={72}
                  percent={Math.max(0, Math.min(100, (Number(ai.score) || 0) * 10))}
                  format={() => `${ai.score || 0}/10`}
                />
                <div>
                  <div style={{ marginBottom: 4 }}>
                    <Tag color={trendColor(ai.trend)}>{ai.trend || '震荡'}</Tag>
                  </div>
                  <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                    分析时间：{selectedStock.ai_analyzed_at ? dayjs(selectedStock.ai_analyzed_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                  </div>
                </div>
              </div>
              <div style={{ lineHeight: 1.8, fontSize: 14 }}>
                <div><span style={{ color: '#8c8c8c' }}>技术面：</span>{ai.技术面 || '-'}</div>
                <div><span style={{ color: '#8c8c8c' }}>基本面：</span>{ai.基本面 || '-'}</div>
                <div><span style={{ color: '#8c8c8c' }}>量能：</span>{ai.量能 || '-'}</div>
                <div><span style={{ color: '#8c8c8c' }}>风险提示：</span>{ai.风险提示 || '-'}</div>
                <div><span style={{ color: '#8c8c8c' }}>操作建议：</span>{ai.操作建议 || '-'}</div>
              </div>
              <div style={{ fontWeight: 600, color: '#262626' }}>
                总结：{ai.summary || '-'}
              </div>
            </div>
          )}
        </Card>
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
          {/* 股票筛选：独立区域 */}
          <div
            style={{
              flexShrink: 0,
              padding: '10px 12px 12px',
              background: '#fafafa',
              borderBottom: '1px solid #f0f0f0',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#262626' }}>股票筛选</span>
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    {
                      key: 'add',
                      label: '添加股票',
                      icon: <PlusOutlined />,
                      onClick: () => setAddModalOpen(true),
                    },
                    {
                      key: 'import',
                      label: 'CSV 批量导入',
                      icon: <UploadOutlined />,
                      onClick: () => setImportModalOpen(true),
                    },
                    {
                      key: 'export',
                      label: '导出 CSV',
                      onClick: handleExport,
                    },
                  ],
                }}
              >
                <Button size="small">
                  操作 <DownOutlined style={{ fontSize: 10 }} />
                </Button>
              </Dropdown>
            </div>
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              {(activePool?.name?.includes('涨停') ?? false) && (
                <DatePicker.RangePicker
                  size="small"
                  style={{ width: '100%' }}
                  placeholder={['涨停起始日', '涨停截止日']}
                  value={limitUpDateFrom && limitUpDateTo ? [limitUpDateFrom, limitUpDateTo] : null}
                  onChange={dates => {
                    setLimitUpDateFrom(dates?.[0] ?? null)
                    setLimitUpDateTo(dates?.[1] ?? null)
                  }}
                  allowClear
                />
              )}
              <Select
                size="small"
                value={`${sortBy}-${sortOrder}`}
                onChange={v => {
                  const [s, o] = v.split('-') as ['created_at' | 'limit_up_date', 'asc' | 'desc']
                  setSortBy(s)
                  setSortOrder(o)
                }}
                style={{ width: '100%' }}
                options={[
                  { value: 'limit_up_date-desc', label: '排序：涨停日 新→旧' },
                  { value: 'limit_up_date-asc', label: '排序：涨停日 旧→新' },
                  { value: 'created_at-desc', label: '排序：加入时间 新→旧' },
                  { value: 'created_at-asc', label: '排序：加入时间 旧→新' },
                ]}
              />
            </Space>
          </div>

          {/* Stock count */}
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid #f0f0f0',
            fontSize: 13, color: '#8c8c8c', flexShrink: 0,
          }}>
            {stocks.length} 只股票
            <span style={{ float: 'right', color: '#bfbfbf', fontSize: 12 }}>↑↓ 切换</span>
          </div>

          {/* Stock list */}
          <div ref={listRef} onScroll={onListScroll} style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
            ) : stocks.length === 0 ? (
              <Empty description={activePool ? '暂无匹配股票' : '请选择或创建观察池'} style={{ padding: 48 }} />
            ) : (
              <>
                {stocks.map(s => renderStockItem(s))}
                {hasMore && (
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
