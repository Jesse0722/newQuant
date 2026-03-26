import React, { useEffect, useState, useRef, useCallback } from 'react'
import {
  Button, Modal, Form, Input, InputNumber, Space,
  Tag, Upload, message, Popconfirm, Select, Tooltip, AutoComplete,
  Segmented, Spin, Empty, Dropdown, Table,
} from 'antd'
import {
  PlusOutlined, UploadOutlined, SyncOutlined, ReloadOutlined,
  PushpinFilled, FileAddOutlined, HolderOutlined,
  EllipsisOutlined, RightOutlined,
} from '@ant-design/icons'
import * as echarts from 'echarts'
import { useNavigate } from 'react-router-dom'
import {
  listPools, createPool, updatePool, deletePool, reorderPools,
  listStocks, addStock, deleteStock, updateStock, importCSV, getAllStocks,
} from '../../api/pools'
import { searchStocks, getStockChart } from '../../api/stocks'
import { createPlan } from '../../api/plans'
import { syncPool, getTaskStatus } from '../../api/sync'
import { getPoolRules, createPoolRule, deleteRule, listTemplates } from '../../api/monitor'
import type { Pool, WatchStock, MonitorRule, MonitorTemplate, StockChartData } from '../../types'

const PAGE_SIZE = 50
const TRIGGER_OPTIONS = ['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合']

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
  const [chartData, setChartData] = useState<StockChartData | null>(null)
  const [chartLoading, setChartLoading] = useState(false)

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

  const activePool = pools.find(p => p.id === activePoolId)
  const selectedIndex = stocks.findIndex(s => s.ts_code === selectedCode)
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
      page: pageNum,
      size: PAGE_SIZE,
      sort_by: f.sortBy,
      order: f.sortOrder,
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
    if (activePoolId) loadInitial(activePoolId)
  }, [activePoolId, limitUpDateFrom, limitUpDateTo, sortBy, sortOrder])

  useEffect(() => {
    setChartData(null)
  }, [selectedCode])

  useEffect(() => {
    if (!selectedCode) return
    setChartLoading(true)
    getStockChart(selectedCode, chartPeriod)
      .then(res => setChartData(res.data))
      .catch(() => setChartData(null))
      .finally(() => setChartLoading(false))
  }, [selectedCode, chartPeriod])

  useEffect(() => {
    if (chartInstance.current) {
      try { chartInstance.current.dispose() } catch { /* noop */ }
      chartInstance.current = null
    }
    const timer = setTimeout(() => {
      if (!chartDivRef.current || !chartData?.quotes?.length) return
      chartInstance.current = echarts.init(chartDivRef.current)
      const { quotes, indicators } = chartData
      const dates = quotes.map(q => q.date)
      const ohlc = quotes.map(q => [q.open, q.close, q.low, q.high])
      const volumes = quotes.map(q => ({
        value: q.vol,
        itemStyle: { color: q.close >= q.open ? '#ec0000' : '#00da3c' },
      }))
      const series: any[] = [
        {
          name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
        },
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
            data: indicators.macd.histogram.map(v => ({
              value: v, itemStyle: { color: v != null && v >= 0 ? '#ec0000' : '#00da3c' },
            })),
            xAxisIndex: 2, yAxisIndex: 2,
          },
        )
      } else {
        series.push({
          name: 'RSI', type: 'line', data: indicators.rsi,
          xAxisIndex: 2, yAxisIndex: 2, symbol: 'none',
          lineStyle: { width: 1.5, color: '#9b59b6' },
        })
      }
      chartInstance.current.setOption({
        animation: false,
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: ['MA5', 'MA10', 'MA20'], top: 0, left: 'center', textStyle: { fontSize: 11 } },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
          { left: 48, right: 12, top: 24, height: '48%' },
          { left: 48, right: 12, top: '58%', height: '12%' },
          { left: 48, right: 12, top: '74%', height: '18%' },
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
        else if (stocks.length < total) loadMore()
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        if (idx > 0) setSelectedCode(stocks[idx - 1].ts_code)
      } else if (e.key === 'Enter') {
        e.preventDefault()
        if (selectedCode) navigate(`/stocks/${selectedCode}`)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [stocks, selectedCode, total, loadMore, navigate])

  useEffect(() => {
    selectedItemRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [selectedCode])

  useEffect(() => {
    if (selectedIndex >= stocks.length - 5 && hasMore && !loadingMore) loadMore()
  }, [selectedIndex, stocks.length, hasMore, loadingMore, loadMore])

  useEffect(() => {
    if (createPlanModalOpen) getAllStocks().then(res => setAllStocks(res.data || []))
  }, [createPlanModalOpen])

  /* ===== Handlers ===== */

  const handleAddPool = async () => {
    const name = `新观察池 ${pools.length + 1}`
    const res = await createPool({ name })
    await fetchPools()
    setActivePoolId(res.data.id)
    message.success('已创建')
  }

  const handleDeletePool = (poolId: string) => {
    Modal.confirm({
      title: '确定删除该观察池？',
      content: '池内所有股票将一并删除',
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
    poolForm.setFieldsValue({
      name: pool.name,
      description: pool.description,
      trigger_target_pool_id: pool.trigger_target_pool_id || undefined,
    })
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
        .then(res => {
          const list = res.data || []
          setStockSearchOptions(list.map(s => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` })))
        })
        .catch(() => setStockSearchOptions([]))
        .finally(() => setStockSearching(false))
    }, 300)
  }

  const handleAddStock = async () => {
    const values = await addForm.validateFields()
    await addStock(activePoolId, values)
    message.success('添加成功，数据同步中...')
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
            message[st.data.status === 'completed' ? 'success' : 'error'](
              st.data.status === 'completed' ? '同步完成' : '同步失败'
            )
            loadInitial(activePoolId)
          }
        } catch {
          clearInterval(poll)
          setSyncing(false)
        }
      }, 2000)
    } catch {
      setSyncing(false)
    }
  }

  const handleTogglePin = async (stock: WatchStock) => {
    await updateStock(activePoolId, stock.id, { pinned: !stock.pinned })
    setStocks(prev => prev.map(s => s.id === stock.id ? { ...s, pinned: !s.pinned } : s))
  }

  const handleFieldUpdate = async (stockId: string, field: string, value: any) => {
    await updateStock(activePoolId, stockId, { [field]: value } as any)
    setStocks(prev => prev.map(s => s.id === stockId ? { ...s, [field]: value } : s))
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

  const handleTabDragStart = (e: React.DragEvent, index: number) => {
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', String(index))
  }
  const handleTabDragOver = (e: React.DragEvent, index: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIndex(index)
  }
  const handleTabDragLeave = () => setDragOverIndex(null)
  const handleTabDrop = async (e: React.DragEvent, targetIndex: number) => {
    e.preventDefault()
    setDragOverIndex(null)
    const fromIndex = parseInt(e.dataTransfer.getData('text/plain'), 10)
    if (Number.isNaN(fromIndex) || fromIndex === targetIndex) return
    const newPools = [...pools]
    const [removed] = newPools.splice(fromIndex, 1)
    newPools.splice(targetIndex, 0, removed)
    setPools(newPools)
    try {
      await reorderPools(newPools.map(p => p.id))
      message.success('排序已保存')
    } catch {
      setPools(pools)
      message.error('排序保存失败')
    }
  }
  const handleTabDragEnd = () => setDragOverIndex(null)

  const onListScroll = useCallback(() => {
    const el = listRef.current
    if (!el || !hasMore || loadingMore || loading) return
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 300) loadMore()
  }, [hasMore, loadingMore, loading, loadMore])

  const stockOptions = allStocks.map(s => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` }))

  const fmtLimitDate = (d?: string) => d ? `${d.slice(4, 6)}-${d.slice(6)}` : ''

  /* ===== Render ===== */

  const renderStockItem = (stock: WatchStock) => {
    const isSelected = stock.ts_code === selectedCode
    return (
      <div
        key={stock.id}
        ref={isSelected ? selectedItemRef : undefined}
        onClick={() => setSelectedCode(stock.ts_code)}
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid #f0f0f0',
          cursor: 'pointer',
          transition: 'background 0.15s',
          background: isSelected ? '#f0f5ff' : undefined,
        }}
        onMouseEnter={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '#fafafa' }}
        onMouseLeave={e => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, overflow: 'hidden' }}>
            {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 12, flexShrink: 0 }} />}
            {stock.monitor_status === 'monitoring' && (
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#52c41a', display: 'inline-block', flexShrink: 0 }} />
            )}
            {stock.monitor_status === 'triggered' && (
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#faad14', display: 'inline-block', flexShrink: 0 }} />
            )}
            <span style={{ fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap' }}>{stock.stock_name || '-'}</span>
            <span style={{ color: '#999', fontSize: 12, whiteSpace: 'nowrap' }}>{stock.ts_code}</span>
            {stock.industry && (
              <Tag style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px', margin: 0, flexShrink: 0 }}>{stock.industry}</Tag>
            )}
            {stock.limit_up_date && (
              <Tag color="volcano" style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px', margin: 0, flexShrink: 0 }}>
                涨停 {fmtLimitDate(stock.limit_up_date)}
              </Tag>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
            <span style={{ fontWeight: 600, fontSize: 15, fontFamily: "'Menlo', monospace" }}>
              {stock.latest_price != null ? stock.latest_price.toFixed(2) : '-'}
            </span>
            {stock.pct_chg != null && (
              <span style={{
                fontWeight: 600, fontSize: 13, fontFamily: "'Menlo', monospace",
                minWidth: 60, textAlign: 'right',
                color: stock.pct_chg > 0 ? '#cf1322' : stock.pct_chg < 0 ? '#3f8600' : '#666',
              }}>
                {stock.pct_chg > 0 ? '+' : ''}{stock.pct_chg.toFixed(2)}%
              </span>
            )}
            {isSelected && (
              <Dropdown
                trigger={['click']}
                menu={{
                  items: [
                    { key: 'detail', label: '查看详情', onClick: () => navigate(`/stocks/${stock.ts_code}`) },
                    { key: 'plan', label: '创建交易计划', onClick: () => openCreatePlanModal(stock) },
                    { key: 'pin', label: stock.pinned ? '取消置顶' : '置顶', onClick: () => handleTogglePin(stock) },
                    { type: 'divider' as const },
                    {
                      key: 'delete', label: '移除', danger: true,
                      onClick: () => Modal.confirm({ title: '确定移除该股票？', onOk: () => handleDeleteStock(stock.id) }),
                    },
                  ],
                }}
              >
                <EllipsisOutlined
                  onClick={e => e.stopPropagation()}
                  style={{ fontSize: 16, padding: 4, cursor: 'pointer', color: '#999' }}
                />
              </Dropdown>
            )}
          </div>
        </div>

        {isSelected && (
          <div style={{ marginTop: 8 }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <Space size="small">
                <Segmented
                  size="small"
                  options={[{ label: '60日', value: 60 }, { label: '120日', value: 120 }, { label: '250日', value: 250 }]}
                  value={chartPeriod}
                  onChange={v => setChartPeriod(v as number)}
                />
                <Segmented
                  size="small"
                  options={[{ label: 'MACD', value: 'macd' }, { label: 'RSI', value: 'rsi' }]}
                  value={subIndicator}
                  onChange={v => setSubIndicator(v as 'macd' | 'rsi')}
                />
              </Space>
              <Space size="small" style={{ fontSize: 12, color: '#999' }}>
                {stock.added_price != null && <span>加入价 {stock.added_price.toFixed(2)}</span>}
                {stock.note && (
                  <Tooltip title={stock.note}>
                    <span style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'inline-block' }}>
                      {stock.note}
                    </span>
                  </Tooltip>
                )}
                <Button size="small" type="link" style={{ padding: 0, fontSize: 12 }} onClick={() => navigate(`/stocks/${stock.ts_code}`)}>
                  详情 <RightOutlined />
                </Button>
              </Space>
            </div>
            {chartLoading && !chartData ? (
              <div style={{ height: 340, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Spin />
              </div>
            ) : (
              <div
                ref={chartDivRef}
                style={{ width: '100%', height: 340, opacity: chartLoading ? 0.4 : 1, transition: 'opacity 0.2s' }}
              />
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ height: 'calc(100vh - 112px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>观察池</h3>
        {activePool && (
          <Space size="small">
            <Button size="small" type="primary" icon={<FileAddOutlined />} onClick={() => setCreatePlanModalOpen(true)}>
              交易计划
            </Button>
            <Button size="small" onClick={openEditPoolModal}>编辑池</Button>
            <Button size="small" icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={handleSync}>同步</Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadInitial(activePoolId)}>刷新</Button>
          </Space>
        )}
      </div>

      {/* Pool tabs */}
      <div
        style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10 }}
        onDragEnd={handleTabDragEnd}
        onDragLeave={handleTabDragLeave}
      >
        {pools.map((p, i) => (
          <div
            key={p.id}
            draggable
            onDragStart={e => handleTabDragStart(e, i)}
            onDragOver={e => handleTabDragOver(e, i)}
            onDrop={e => handleTabDrop(e, i)}
            onClick={() => setActivePoolId(p.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              padding: '5px 12px', fontSize: 13, cursor: 'pointer', userSelect: 'none',
              borderRadius: 6,
              background: activePoolId === p.id ? '#1677ff' : dragOverIndex === i ? '#e6f7ff' : '#f5f5f5',
              color: activePoolId === p.id ? '#fff' : '#333',
              fontWeight: activePoolId === p.id ? 600 : 400,
              transition: 'all 0.15s',
            }}
          >
            <HolderOutlined style={{ fontSize: 10, opacity: 0.4, cursor: 'grab' }} />
            <span>{p.name}</span>
            <span style={{ opacity: 0.6, fontSize: 12 }}>({p.stock_count})</span>
            <span
              onClick={e => { e.stopPropagation(); handleDeletePool(p.id) }}
              style={{ marginLeft: 2, cursor: 'pointer', opacity: 0.4, fontSize: 11, lineHeight: 1 }}
            >
              ×
            </span>
          </div>
        ))}
        <div
          onClick={handleAddPool}
          style={{
            padding: '5px 12px', fontSize: 13, cursor: 'pointer',
            borderRadius: 6, border: '1px dashed #d9d9d9', color: '#999',
          }}
        >
          + 新建
        </div>
      </div>

      {/* Filters */}
      {activePool && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 4 }}>
          <Space size="small">
            {(activePool.name?.includes('涨停') ?? false) && (
              <>
                <span style={{ fontSize: 12, color: '#999' }}>涨停日期</span>
                <Input size="small" placeholder="起 YYYYMMDD" value={limitUpDateFrom}
                  onChange={e => setLimitUpDateFrom(e.target.value.replace(/-/g, '').slice(0, 8))} style={{ width: 100 }} />
                <span style={{ color: '#d9d9d9' }}>—</span>
                <Input size="small" placeholder="止 YYYYMMDD" value={limitUpDateTo}
                  onChange={e => setLimitUpDateTo(e.target.value.replace(/-/g, '').slice(0, 8))} style={{ width: 100 }} />
              </>
            )}
            <Select
              size="small"
              value={`${sortBy}-${sortOrder}`}
              onChange={v => {
                const [s, o] = v.split('-') as ['created_at' | 'limit_up_date', 'asc' | 'desc']
                setSortBy(s); setSortOrder(o)
              }}
              style={{ width: 140 }}
              options={[
                { value: 'limit_up_date-desc', label: '涨停日期 新→旧' },
                { value: 'limit_up_date-asc', label: '涨停日期 旧→新' },
                { value: 'created_at-desc', label: '加入时间 新→旧' },
                { value: 'created_at-asc', label: '加入时间 旧→新' },
              ]}
            />
          </Space>
          <Space size="small">
            <Button size="small" icon={<UploadOutlined />} onClick={() => setImportModalOpen(true)}>CSV导入</Button>
            <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setAddModalOpen(true)}>添加</Button>
          </Space>
        </div>
      )}

      {/* Stock list */}
      <div
        ref={listRef}
        onScroll={onListScroll}
        style={{
          flex: 1, overflowY: 'auto', minHeight: 0,
          border: '1px solid #f0f0f0', borderRadius: 8, background: '#fff',
        }}
      >
        {loading ? (
          <div style={{ padding: 60, textAlign: 'center' }}><Spin /></div>
        ) : stocks.length === 0 ? (
          <Empty description={activePool ? '暂无股票' : '请选择或创建观察池'} style={{ padding: 60 }} />
        ) : (
          <>
            {stocks.map(stock => renderStockItem(stock))}
            {hasMore && (
              <div style={{ textAlign: 'center', padding: 12 }}>
                {loadingMore ? <Spin size="small" /> : (
                  <Button type="link" size="small" onClick={loadMore}>
                    加载更多（{stocks.length}/{total}）
                  </Button>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer status */}
      {stocks.length > 0 && (
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '6px 0 0', fontSize: 12, color: '#bbb',
        }}>
          <span>{selectedIndex >= 0 ? selectedIndex + 1 : '-'} / {total} 只</span>
          <Space size={4}>
            <Tag style={{ fontSize: 11, margin: 0, padding: '0 4px', lineHeight: '18px' }}>↑↓</Tag>
            <span>切换</span>
            <Tag style={{ fontSize: 11, margin: 0, padding: '0 4px', lineHeight: '18px' }}>Enter</Tag>
            <span>详情</span>
          </Space>
        </div>
      )}

      {pools.length === 0 && !loading && (
        <div style={{ textAlign: 'center', padding: 48, color: '#999' }}>
          暂无观察池，点击上方「+ 新建」创建
        </div>
      )}

      {/* ===== Modals ===== */}

      <Modal title="添加股票" open={addModalOpen} onOk={handleAddStock} onCancel={() => { setAddModalOpen(false); setStockSearchOptions([]) }}>
        <Form form={addForm} layout="vertical">
          <Form.Item name="ts_code" label="股票" rules={[{ required: true, message: '请输入股票代码或名称' }]}>
            <AutoComplete
              options={stockSearchOptions}
              placeholder="输入代码或名称搜索"
              onSearch={handleStockSearch}
              notFoundContent={stockSearching ? '搜索中...' : stockSearchOptions.length === 0 ? '输入至少2个字符搜索' : null}
            />
          </Form.Item>
          <Form.Item name="added_price" label="加入价格">
            <InputNumber style={{ width: '100%' }} placeholder="可选" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea placeholder="可选" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="编辑观察池" open={editPoolModalOpen} onOk={handleEditPool} onCancel={() => setEditPoolModalOpen(false)} width={560}>
        <Form form={poolForm} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input.TextArea /></Form.Item>
          <Form.Item name="trigger_target_pool_id" label="买点触发后加入">
            <Select allowClear placeholder="选择目标池"
              options={pools.filter(p => p.id !== activePoolId).map(p => ({ value: p.id, label: p.name }))} />
          </Form.Item>
          <Form.Item label="监控规则">
            <div style={{ marginBottom: 8 }}>
              {poolRules.map(r => (
                <div key={r.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}>
                  <span>{r.template_name || r.template_id || '组合'} {r.params && Object.keys(r.params).length > 0 && `(${JSON.stringify(r.params)})`}</span>
                  <Popconfirm title="确定删除？" onConfirm={() => handleDeleteRule(r.id)}>
                    <a style={{ color: '#ff4d4f', fontSize: 12 }}>删除</a>
                  </Popconfirm>
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
            <Select
              placeholder="选择买点条件"
              options={monitorTemplates.map(t => ({ value: t.id, label: `${t.name} - ${t.description}` }))}
              onChange={v => {
                const t = monitorTemplates.find(x => x.id === v)
                ruleForm.setFieldsValue({ params: t?.default_params || {} })
              }}
            />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.template_id !== curr.template_id}>
            {({ getFieldValue }) => {
              const tid = getFieldValue('template_id')
              const t = monitorTemplates.find(x => x.id === tid)
              if (!t?.default_params) return null
              return (
                <Form.Item name={['params', 'n']} label="均线周期" hidden={tid !== 'ma_support'}>
                  <InputNumber min={5} max={60} style={{ width: 100 }} />
                </Form.Item>
              )
            }}
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, curr) => prev.template_id !== curr.template_id}>
            {({ getFieldValue }) => {
              const tid = getFieldValue('template_id')
              return (
                <>
                  <Form.Item name={['params', 'tolerance']} label="容差（如 0.03=±3%）" hidden={!['limit_up_price_support', 'fibonacci_retrace'].includes(tid)}>
                    <InputNumber min={0.01} max={0.2} step={0.01} style={{ width: 120 }} placeholder="0.03" />
                  </Form.Item>
                  <Form.Item name={['params', 'min_days']} label="最少天数" hidden={tid !== 'days_since_limit_up'}>
                    <InputNumber min={1} max={60} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item name={['params', 'max_days']} label="最多天数" hidden={tid !== 'days_since_limit_up'}>
                    <InputNumber min={1} max={60} style={{ width: 100 }} />
                  </Form.Item>
                  <Form.Item name={['params', 'level']} label="黄金分割位" hidden={tid !== 'fibonacci_retrace'}>
                    <Select style={{ width: 120 }} options={[{ value: 0.382, label: '0.382' }, { value: 0.5, label: '0.5' }]} />
                  </Form.Item>
                </>
              )
            }}
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`创建交易计划 - ${planStock?.stock_name || planStock?.ts_code || ''}`}
        open={planModalOpen}
        onOk={handleCreatePlan}
        onCancel={() => { setPlanModalOpen(false); setPlanStock(null) }}
        width={560}
      >
        <Form form={planForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name={['stocks', 0, 'ts_code']} hidden><Input /></Form.Item>
          <Form.Item noStyle shouldUpdate>
            {() => (
              <div style={{ marginBottom: 16, padding: 12, background: '#fafafa', borderRadius: 8 }}>
                <div style={{ marginBottom: 8 }}>股票：{planStock?.stock_name || planStock?.ts_code || '-'}</div>
                <Form.Item name={['stocks', 0, 'trigger_strategy']} label="触发策略">
                  <AutoComplete options={TRIGGER_OPTIONS.map(o => ({ value: o }))} placeholder="输入或选择" />
                </Form.Item>
                <Space wrap>
                  <Form.Item name={['stocks', 0, 'planned_buy_price']} label="计划买入价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name={['stocks', 0, 'target_price']} label="目标价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                  <Form.Item name={['stocks', 0, 'stop_loss_price']} label="止损价">
                    <InputNumber style={{ width: 120 }} />
                  </Form.Item>
                </Space>
                <Form.Item name={['stocks', 0, 'position_plan']} label="仓位(%)">
                  <InputNumber min={0} max={100} addonAfter="%" style={{ width: 140 }} />
                </Form.Item>
                <Form.Item name={['stocks', 0, 'risk_level']} label="风险程度">
                  <Select style={{ width: 120 }} options={[
                    { value: 1, label: '低风险' }, { value: 2, label: '中风险' }, { value: 3, label: '高风险' },
                  ]} />
                </Form.Item>
                <Form.Item name={['stocks', 0, 'note']} label="备注">
                  <Input.TextArea rows={2} />
                </Form.Item>
              </div>
            )}
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="CSV 批量导入" open={importModalOpen} footer={null} onCancel={() => setImportModalOpen(false)}>
        <p>CSV 格式：必须包含 <code>ts_code</code>（或 <code>股票代码</code>/<code>code</code>）列。可选 <code>added_price</code>、<code>note</code></p>
        <Upload.Dragger accept=".csv" showUploadList={false} beforeUpload={file => { handleImport(file); return false }}>
          <p>点击或拖拽 CSV 文件到此处</p>
        </Upload.Dragger>
      </Modal>

      <Modal title="新建交易计划" open={createPlanModalOpen} onOk={handleCreatePlanFromToolbar}
        onCancel={() => { setCreatePlanModalOpen(false); createPlanForm.resetFields() }} width={900}>
        <Form form={createPlanForm} layout="vertical" initialValues={{ stocks: [{ risk_level: 2 }] }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="股票列表">
            <Form.List name="stocks" rules={[{ validator: (_, v) => v?.length ? Promise.resolve() : Promise.reject('至少添加一只股票') }]}>
              {(fields, { add, remove }) => (
                <>
                  <Table
                    dataSource={fields}
                    rowKey={f => String(f.key)}
                    pagination={false}
                    size="small"
                    scroll={{ x: 1100 }}
                    columns={[
                      {
                        title: '股票', key: 'ts_code', width: 180,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true, message: '请选择' }]}>
                            <Select showSearch placeholder="选择或搜索" size="small" style={{ width: 160 }} options={stockOptions}
                              filterOption={(input, opt) => (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '触发策略', key: 'trigger_strategy', width: 130,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle>
                            <AutoComplete options={TRIGGER_OPTIONS.map(o => ({ value: o }))} placeholder="输入或选择" size="small" style={{ width: 120 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '买入价', key: 'planned_buy_price', width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '目标价', key: 'target_price', width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'target_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '止损价', key: 'stop_loss_price', width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '仓位(%)', key: 'position_plan', width: 90,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'position_plan']} noStyle>
                            <InputNumber size="small" min={0} max={100} addonAfter="%" style={{ width: 80 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '风险', key: 'risk_level', width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'risk_level']} noStyle>
                            <Select size="small" style={{ width: 90 }} options={[
                              { value: 1, label: '低风险' }, { value: 2, label: '中风险' }, { value: 3, label: '高风险' },
                            ]} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '备注', key: 'note', width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'note']} noStyle>
                            <Input placeholder="备注" size="small" />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '', key: 'action', width: 40,
                        render: (_, __, i) => fields.length > 1 ? <a onClick={() => remove(fields[i].name)} style={{ color: '#ff4d4f' }}>删</a> : null,
                      },
                    ]}
                  />
                  <Button type="dashed" onClick={() => add({ risk_level: 2 })} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加股票</Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PoolList
