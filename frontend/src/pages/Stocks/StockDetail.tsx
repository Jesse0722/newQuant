import React, { useEffect, useState, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  Card, Tag, Table, Button, Tabs, Space, Statistic, Row, Col, Segmented,
  Modal, Form, Input, InputNumber, Select, DatePicker, message, Upload, Popconfirm, Tooltip,
  Progress, Alert,
} from 'antd'
import dayjs from 'dayjs'
import {
  ThunderboltOutlined,
  PlusOutlined,
  InboxOutlined,
  EditOutlined,
  StarOutlined,
  StarFilled,
  RobotOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import * as echarts from 'echarts'
import {
  getStockChart,
  getStockAlerts,
  getStockDetails,
  createStockDetail,
  getStockAiAnalysis,
  runStockAiAnalysis,
  runStockAiAnalysisTask,
} from '../../api/stocks'
import { getCoreWatchCodes, toggleCoreWatch } from '../../api/pools'
import { updateDetail, deleteDetail } from '../../api/plans'
import { extractTradeFromImage } from '../../api/ocr'
import type { JsonObject, StockAiAnalysisRecord, StockAiAnalysisSection, StockChartData, StockAlertItem, TradeDetail } from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'
import { getNotifications, subscribeNotifications, upsertNotification } from '../../services/notificationCenter'

const SHOW_STOCK_DETAIL_TRADING_ENTRIES = false
const SHOW_STOCK_DETAIL_ALERTS_AND_DETAILS = false

const statusColors: Record<string, string> = {
  pending: 'default', active: 'blue', completed: 'green', cancelled: 'red', processed: 'purple',
}

interface PoolNavStock {
  ts_code: string
  stock_name?: string
  industry?: string
  latest_price?: number
  pct_chg?: number
  limit_up_date?: string
}

interface StockDetailLocationState {
  stockList?: PoolNavStock[]
  poolName?: string
}

interface StockDetailProps {
  embedded?: boolean
  tsCode?: string
  stockNote?: string
  onEditNote?: () => void
}

interface DetailFormValues {
  trade_date?: dayjs.Dayjs
  trade_time?: string
  direction?: 'buy' | 'sell'
  price?: number
  quantity?: number
  commission?: number
  exec_note?: string
}

const StockDetail: React.FC<StockDetailProps> = ({ embedded = false, tsCode: propTsCode, stockNote, onEditNote }) => {
  const { tsCode: routeTsCode } = useParams<{ tsCode: string }>()
  const tsCode = propTsCode || routeTsCode
  const navigate = useNavigate()
  const location = useLocation()
  const [chartData, setChartData] = useState<StockChartData | null>(null)
  const [alerts, setAlerts] = useState<StockAlertItem[]>([])
  const [details, setDetails] = useState<TradeDetail[]>([])
  const [period, setPeriod] = useState(120)
  const [subIndicator, setSubIndicator] = useState<string>('macd')
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [quickRecordModalOpen, setQuickRecordModalOpen] = useState(false)
  const [editDetailModalOpen, setEditDetailModalOpen] = useState(false)
  const [editingDetail, setEditingDetail] = useState<TradeDetail | null>(null)
  const [ocrLoading, setOcrLoading] = useState(false)
  const [ocrRawText, setOcrRawText] = useState<string>('')
  const [coreStarred, setCoreStarred] = useState(false)
  const [coreStarLoading, setCoreStarLoading] = useState(false)
  const [aiAnalysis, setAiAnalysis] = useState<StockAiAnalysisRecord | null>(null)
  const [aiLoadingMode, setAiLoadingMode] = useState<'fast' | 'deep' | null>(null)
  const [quickRecordForm] = Form.useForm()
  const [detailForm] = Form.useForm()
  const [editDetailForm] = Form.useForm()
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const locationState = (location.state as StockDetailLocationState | null) ?? null
  const poolNavStocks = useMemo<PoolNavStock[]>(
    () => (embedded ? [] : (Array.isArray(locationState?.stockList) ? locationState.stockList : [])),
    [embedded, locationState?.stockList]
  )
  const poolName = embedded ? undefined : locationState?.poolName
  const currentNavIndex = poolNavStocks.findIndex((s) => s.ts_code === tsCode)

  const jumpToStock = useCallback((idx: number) => {
    if (idx < 0 || idx >= poolNavStocks.length) return
    const target = poolNavStocks[idx]
    navigate(`/stocks/${target.ts_code}`, { state: location.state })
  }, [location.state, navigate, poolNavStocks])

  const fetchDetails = useCallback(() => {
    if (tsCode) getStockDetails(tsCode).then((res) => setDetails(res.data))
  }, [tsCode])

  const openDetailModal = () => {
    detailForm.resetFields()
    setDetailModalOpen(true)
  }

  const openQuickRecordModal = () => {
    quickRecordForm.resetFields()
    setOcrRawText('')
    setQuickRecordModalOpen(true)
  }

  const handleOcrUpload = async (file: File) => {
    setOcrLoading(true)
    setOcrRawText('')
    try {
      const res = await extractTradeFromImage(file)
      if (res.data.error) {
        message.warning(res.data.error + '，请手动填写')
      } else {
        setOcrRawText(res.data.raw_text)
        const p = res.data.parsed || {}
        const values: DetailFormValues = {}
        if (p.trade_date) values.trade_date = dayjs(p.trade_date, 'YYYYMMDD')
        if (p.trade_time) values.trade_time = p.trade_time
        if (p.direction === 'buy' || p.direction === 'sell') values.direction = p.direction
        if (p.price != null) values.price = p.price
        if (p.quantity != null) values.quantity = p.quantity
        quickRecordForm.setFieldsValue(values)
        message.success('识别完成，请校对后提交')
      }
    } catch {
      message.error('识别失败，请手动填写')
    } finally {
      setOcrLoading(false)
    }
    return false
  }

  const handleSkipUpload = () => {
    setOcrRawText('')
    quickRecordForm.resetFields()
  }

  const handleQuickRecordSubmit = async () => {
    if (!tsCode) return
    const values = await quickRecordForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await createStockDetail(tsCode, payload)
    message.success('交易记录已添加')
    setQuickRecordModalOpen(false)
    fetchDetails()
  }

  const handleAddDetail = async () => {
    if (!tsCode) return
    const values = await detailForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await createStockDetail(tsCode, payload)
    message.success('交易明细已添加')
    setDetailModalOpen(false)
    fetchDetails()
  }

  const openEditDetailModal = (d: TradeDetail) => {
    setEditingDetail(d)
    editDetailForm.setFieldsValue({
      trade_date: d.trade_date ? dayjs(d.trade_date, 'YYYYMMDD') : undefined,
      trade_time: d.trade_time,
      direction: d.direction,
      price: d.price,
      quantity: d.quantity,
      commission: d.commission,
      exec_note: d.exec_note,
    })
    setEditDetailModalOpen(true)
  }

  const handleEditDetail = async () => {
    if (!editingDetail) return
    const values = await editDetailForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await updateDetail(editingDetail.id, payload)
    message.success('明细已更新')
    setEditDetailModalOpen(false)
    setEditingDetail(null)
    fetchDetails()
  }

  const handleDeleteDetail = async (id: string) => {
    await deleteDetail(id)
    message.success('已删除')
    fetchDetails()
  }

  useEffect(() => {
    if (!tsCode) return
    getStockChart(tsCode, period).then((res) => setChartData(res.data))
    if (SHOW_STOCK_DETAIL_ALERTS_AND_DETAILS) {
      getStockAlerts(tsCode).then((res) => setAlerts(res.data))
      fetchDetails()
    }
  }, [tsCode, period, fetchDetails])

  useEffect(() => {
    if (!tsCode) {
      setAiAnalysis(null)
      return
    }
    let cancelled = false
    getStockAiAnalysis(tsCode)
      .then((res) => {
        if (cancelled) return
        setAiAnalysis(res.data.analysis ? res.data as StockAiAnalysisRecord : null)
      })
      .catch(() => {
        if (!cancelled) setAiAnalysis(null)
      })
    return () => {
      cancelled = true
    }
  }, [tsCode])

  useEffect(() => {
    if (!tsCode) return
    return subscribeNotifications((items) => {
      const completed = items.find((item) =>
        item.kind === 'stock_ai_analysis' &&
        item.status === 'success' &&
        item.meta?.tsCode === tsCode &&
        item.meta?.result?.analysis
      )
      if (completed?.meta?.result) {
        setAiAnalysis(completed.meta.result)
      }
    })
  }, [tsCode])

  useEffect(() => {
    if (!tsCode) {
      setCoreStarred(false)
      return
    }
    let cancelled = false
    getCoreWatchCodes()
      .then((res) => {
        if (cancelled) return
        const codes = res.data.ts_codes ?? []
        setCoreStarred(codes.includes(tsCode))
      })
      .catch(() => {
        if (!cancelled) setCoreStarred(false)
      })
    return () => {
      cancelled = true
    }
  }, [tsCode])

  const handleCoreStarToggle = async () => {
    if (!tsCode || coreStarLoading) return
    setCoreStarLoading(true)
    try {
      const next = !coreStarred
      await toggleCoreWatch({ ts_code: tsCode, starred: next, source: 'stock_detail' })
      setCoreStarred(next)
      message.success(next ? '已加入核心股票池「核心关注」' : '已从核心股票池移除')
    } catch {
      message.error('操作失败，请稍后重试')
    } finally {
      setCoreStarLoading(false)
    }
  }

  const handleRunAiAnalysis = async (mode: 'fast' | 'deep') => {
    if (!tsCode || aiLoadingMode) return
    setAiLoadingMode(mode)
    try {
      if (mode === 'deep') {
        const running = getNotifications().find((item) =>
          item.kind === 'stock_ai_analysis' &&
          item.status === 'running' &&
          item.meta?.tsCode === tsCode &&
          item.meta?.mode === 'deep'
        )
        if (running) {
          message.info('该股票的深度分析已在队列中，请在顶部消息中心查看进度')
          return
        }
        const res = await runStockAiAnalysisTask(tsCode, {
          mode,
          scope: 'stock_detail',
          force_refresh: true,
        })
        const now = new Date().toISOString()
        upsertNotification({
          id: `stock-ai-analysis:${res.data.task_id}`,
          kind: 'stock_ai_analysis',
          status: 'running',
          title: `${basic?.name || tsCode} 深度分析中`,
          description: res.data.deduped ? '已有同样分析任务正在执行，已复用该任务' : '任务已提交，完成后会在顶部消息中心提醒',
          createdAt: now,
          updatedAt: now,
          read: false,
          taskId: res.data.task_id,
          link: `/stocks/${tsCode}`,
          meta: {
            tsCode,
            stockName: basic?.name || tsCode,
            mode,
          },
        })
        message.success(res.data.deduped ? '已复用正在执行的深度分析任务' : '深度分析已提交')
        return
      }
      const res = await runStockAiAnalysis(tsCode, {
        mode,
        scope: 'stock_detail',
        force_refresh: true,
      })
      setAiAnalysis(res.data)
      message.success(mode === 'fast' ? '快速分析完成' : '深度分析完成')
    } catch (error: unknown) {
      const maybeResponse = (error as { response?: { data?: { message?: string } } }).response
      message.error(maybeResponse?.data?.message || 'AI 分析失败，请检查模型配置或稍后重试')
    } finally {
      setAiLoadingMode(null)
    }
  }

  const renderChart = useCallback(() => {
    if (!chartRef.current || !chartData || chartData.quotes.length === 0) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current)
    }
    const chart = chartInstance.current
    const { quotes, indicators } = chartData
    const dates = quotes.map((q) => q.date)
    const ohlc = quotes.map((q) => [q.open, q.close, q.low, q.high])
    const volumes = quotes.map((q) => ({
      value: q.vol,
      itemStyle: { color: q.close >= q.open ? '#ec0000' : '#00da3c' },
    }))

    const showMacd = subIndicator === 'macd'

    const gridMain = { left: 60, right: 20, top: 30, height: '45%' }
    const gridVol = { left: 60, right: 20, top: '58%', height: '12%' }
    const gridSub = { left: 60, right: 20, top: '74%', height: '18%' }

    const series: Array<Record<string, unknown>> = [
      {
        name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
        itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
      },
      { name: 'MA5', type: 'line', data: indicators.ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      { name: 'MA10', type: 'line', data: indicators.ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      { name: 'MA20', type: 'line', data: indicators.ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, lineStyle: { width: 1 }, symbol: 'none' },
      { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 },
    ]

    if (showMacd) {
      series.push(
        { name: 'DIF', type: 'line', data: indicators.macd.dif, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1 } },
        { name: 'DEA', type: 'line', data: indicators.macd.dea, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1 } },
        {
          name: 'MACD', type: 'bar', data: indicators.macd.histogram.map((v) => ({
            value: v,
            itemStyle: { color: v != null && v >= 0 ? '#ec0000' : '#00da3c' },
          })),
          xAxisIndex: 2, yAxisIndex: 2,
        },
      )
    } else {
      series.push(
        { name: 'RSI', type: 'line', data: indicators.rsi, xAxisIndex: 2, yAxisIndex: 2, symbol: 'none', lineStyle: { width: 1.5, color: '#9b59b6' } },
      )
    }

    const option: echarts.EChartsOption = {
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: makeKlineAxisTooltipFormatter(quotes),
      },
      legend: { data: ['MA5', 'MA10', 'MA20'], top: 0, left: 'center' },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [gridMain, gridVol, gridSub],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, boundaryGap: true },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false }, boundaryGap: true },
        { type: 'category', data: dates, gridIndex: 2, boundaryGap: true },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitNumber: 4 },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false } },
        { scale: true, gridIndex: 2, splitNumber: 3 },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 60, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 5, height: 20, start: 60, end: 100 },
      ],
      series,
    }
    chart.setOption(option, true)
  }, [chartData, subIndicator])

  useEffect(() => { renderChart() }, [renderChart])

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
    if (poolNavStocks.length === 0 || currentNavIndex < 0) return
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea') return
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        jumpToStock(Math.min(currentNavIndex + 1, poolNavStocks.length - 1))
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        jumpToStock(Math.max(currentNavIndex - 1, 0))
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [poolNavStocks.length, currentNavIndex, jumpToStock])

  const basic = chartData?.basic
  const latestQuote = chartData?.quotes?.length ? chartData.quotes[chartData.quotes.length - 1] : null
  const syncMeta = chartData?.sync_meta
  const latestPct = latestQuote?.pct_chg
  const hasLatestPct = latestPct != null && !Number.isNaN(Number(latestPct))
  const latestFloatShare = latestQuote?.float_share ?? basic?.float_share
  const marketCapYi = latestQuote?.close != null && latestFloatShare != null
    ? latestQuote.close * latestFloatShare / 10000
    : null

  const alertColumns = [
    { title: '触发日期', dataIndex: 'trigger_date', key: 'trigger_date' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
    {
      title: '收盘价',
      key: 'close',
      render: (_: unknown, r: StockAlertItem) => {
        const snapshot = r.snapshot as (JsonObject & { close?: number }) | undefined
        return snapshot?.close?.toFixed(2) ?? '-'
      },
    },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
  ]

  const detailColumns = [
    { title: '日期', dataIndex: 'trade_date', key: 'trade_date' },
    { title: '时间', dataIndex: 'trade_time', key: 'trade_time', render: (v: string) => v || '-' },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      render: (d: string) => <Tag color={d === 'buy' ? 'red' : 'green'}>{d === 'buy' ? '买入' : '卖出'}</Tag>,
    },
    { title: '价格', dataIndex: 'price', key: 'price', render: (v: number) => v.toFixed(2) },
    { title: '数量', dataIndex: 'quantity', key: 'quantity' },
    { title: '金额', dataIndex: 'amount', key: 'amount', render: (v: number) => v.toFixed(2) },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: TradeDetail) => (
        <Space>
          <a onClick={() => openEditDetailModal(r)}><EditOutlined /> 编辑</a>
          <Popconfirm title="确定删除？" onConfirm={() => handleDeleteDetail(r.id)}>
            <a style={{ color: 'red' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const ratingColor = (rating?: string) => {
    if (rating === '强关注') return 'red'
    if (rating === '观察') return 'blue'
    if (rating === '谨慎') return 'orange'
    if (rating === '回避') return 'default'
    return 'default'
  }

  const trendColor = (trend?: string) => {
    if (trend === '上涨') return 'green'
    if (trend === '下跌') return 'red'
    return 'default'
  }

  const renderAiSection = (title: string, section?: StockAiAnalysisSection) => (
    <Col xs={24} lg={12}>
      <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12, minHeight: 132 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 6 }}>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{title}</span>
          {section?.score != null && <Tag>{section.score}</Tag>}
        </div>
        <div style={{ color: 'var(--text-primary)', lineHeight: 1.7 }}>{section?.conclusion || '数据不足'}</div>
        {section?.evidence?.length ? (
          <div style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.7 }}>
            {section.evidence.slice(0, 3).map((item, idx) => (
              <div key={idx}>· {item}</div>
            ))}
          </div>
        ) : null}
        {section?.risk && (
          <div style={{ marginTop: 8, color: 'var(--color-down)', fontSize: 12 }}>风险：{section.risk}</div>
        )}
      </div>
    </Col>
  )

  const ai = aiAnalysis?.analysis
  const plan = ai?.watch_plan
  const qualityWarnings = ai?.data_quality?.warnings || []

  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {poolNavStocks.length > 0 && (
        <Card
          title={poolName ? `${poolName}（${poolNavStocks.length}）` : `池内股票（${poolNavStocks.length}）`}
          size="small"
          style={{ width: 300, flexShrink: 0, maxHeight: 'calc(100vh - 130px)', overflow: 'hidden' }}
          extra={<span style={{ fontSize: 12, color: 'var(--text-muted)' }}>↑ ↓ 快速切换</span>}
        >
          <div style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 210px)' }}>
            {poolNavStocks.map((s, idx) => {
              const active = s.ts_code === tsCode
              return (
                <div
                  key={s.ts_code}
                  onClick={() => jumpToStock(idx)}
                  style={{
                    padding: '8px 10px',
                    borderBottom: '1px solid var(--border-subtle)',
                    cursor: 'pointer',
                    background: active ? 'var(--accent-dim)' : 'transparent',
                    borderLeft: active ? '3px solid var(--accent)' : '3px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontWeight: 600 }}>{s.stock_name || s.ts_code}</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>{s.ts_code}</span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                    {s.industry || '-'}
                    {s.latest_price != null && (
                      <span style={{ marginLeft: 8 }}>
                        {s.latest_price.toFixed(2)}
                      </span>
                    )}
                    {s.pct_chg != null && (
                      <span style={{ marginLeft: 8, color: s.pct_chg >= 0 ? 'var(--color-down)' : 'var(--color-up)' }}>
                        {s.pct_chg >= 0 ? '+' : ''}{s.pct_chg.toFixed(2)}%
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
      {syncMeta && (
        <div style={{ marginBottom: 12 }}>
          <Tag color={syncMeta.status === 'sync_failed' ? 'red' : syncMeta.status === 'updated' ? 'green' : 'blue'}>
            {syncMeta.status === 'sync_failed' ? '数据补齐失败' : syncMeta.status === 'updated' ? '数据已自动更新' : '数据已是最新'}
          </Tag>
          <span style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
            {syncMeta.message}
            {syncMeta.latest_trade_date ? `（最新交易日：${syncMeta.latest_trade_date}）` : ''}
          </span>
        </div>
      )}

      {basic && (
        <Card
          title={`${basic.name} ${basic.ts_code}`}
          style={{ marginBottom: 16 }}
          extra={
            <Space>
              <Tooltip title={coreStarred ? '已在核心股票池（与观察池「核心关注」同步），点击取消' : '加星加入核心股票池（核心关注）'}>
                <Button
                  type="text"
                  size="small"
                  loading={coreStarLoading}
                  icon={coreStarred ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                  onClick={handleCoreStarToggle}
                >
                  {coreStarred ? '已加星' : '加星'}
                </Button>
              </Tooltip>
              {SHOW_STOCK_DETAIL_TRADING_ENTRIES && (
                <>
                  <Button size="small" icon={<ThunderboltOutlined />} onClick={openQuickRecordModal}>
                    快速记录
                  </Button>
                  <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openDetailModal}>
                    添加明细
                  </Button>
                </>
              )}
            </Space>
          }
        >
          <Row gutter={24}>
            <Col span={3}><Statistic title="行业" value={basic.industry || '-'} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={3}><Statistic title="地区" value={basic.area || '-'} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={3}><Statistic title="市场" value={basic.market || '-'} valueStyle={{ fontSize: 16 }} /></Col>
            <Col span={3}><Statistic title="上市日期" value={basic.list_date || '-'} valueStyle={{ fontSize: 16 }} /></Col>
            {latestQuote && (
              <>
                <Col span={3}>
                  <Statistic title="最新价" value={latestQuote.close} precision={2} />
                </Col>
                <Col span={3}>
                  {hasLatestPct ? (
                    <Statistic
                      title="涨幅"
                      value={Number(latestPct)}
                      precision={2}
                      suffix="%"
                      valueStyle={{ color: Number(latestPct) >= 0 ? '#cf1322' : '#3f8600' }}
                    />
                  ) : (
                    <Statistic
                      title="涨幅"
                      value="-"
                      valueStyle={{ color: 'var(--text-muted)', fontSize: 16 }}
                    />
                  )}
                </Col>
                <Col span={3}>
                  <Statistic title="成交量" value={latestQuote.vol} valueStyle={{ fontSize: 16 }} />
                </Col>
                <Col span={3}>
                  {marketCapYi != null && Number.isFinite(marketCapYi) ? (
                    <Statistic title="市值(亿)" value={marketCapYi} precision={1} valueStyle={{ fontSize: 16 }} />
                  ) : (
                    <Statistic title="市值(亿)" value="-" valueStyle={{ fontSize: 16 }} />
                  )}
                </Col>
              </>
            )}
          </Row>
          <div style={{ marginTop: 14 }}>
            <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 8 }}>概念题材</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {(basic.concept_tags ?? []).length > 0 ? (
                basic.concept_tags?.map((tag) => (
                  <Tag key={tag} color="blue" style={{ marginInlineEnd: 0 }}>{tag}</Tag>
                ))
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>暂无数据</span>
              )}
            </div>
          </div>
        </Card>
      )}

      <Card
        title="K 线图"
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            <Segmented
              size="small"
              options={[
                { label: '60日', value: 60 },
                { label: '120日', value: 120 },
                { label: '250日', value: 250 },
              ]}
              value={period}
              onChange={(v) => setPeriod(v as number)}
            />
            <Segmented
              size="small"
              options={[
                { label: 'MACD', value: 'macd' },
                { label: 'RSI', value: 'rsi' },
              ]}
              value={subIndicator}
              onChange={(v) => setSubIndicator(v as string)}
            />
          </Space>
        }
      >
        {chartData && chartData.quotes.length === 0 ? (
          <div style={{ height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            K 线数据不足，请先同步该股票历史行情
          </div>
        ) : (
          <div ref={chartRef} style={{ width: '100%', height: embedded ? 440 : 520 }} />
        )}
      </Card>

      {(stockNote !== undefined || onEditNote) && (
        <Card
          title="股票备注"
          style={{ marginBottom: 16 }}
          extra={onEditNote ? (
            <Button size="small" icon={<EditOutlined />} onClick={onEditNote}>
              编辑备注
            </Button>
          ) : null}
        >
          <div
            style={{
              minHeight: 70,
              whiteSpace: 'pre-wrap',
              lineHeight: 1.8,
              color: stockNote?.trim() ? 'var(--text-primary)' : 'var(--text-muted)',
            }}
          >
            {stockNote?.trim() ? stockNote : '暂无备注'}
          </div>
        </Card>
      )}

      <Card
        title="AI 智能分析"
        style={{ marginBottom: 16 }}
        extra={
          <Space>
            {aiAnalysis?.model_name && <Tag>{aiAnalysis.model_name}</Tag>}
            <Button
              size="small"
              icon={<RobotOutlined />}
              loading={aiLoadingMode === 'fast'}
              disabled={!!aiLoadingMode}
              onClick={() => handleRunAiAnalysis('fast')}
            >
              快速分析
            </Button>
            <Button
              type="primary"
              size="small"
              icon={<ReloadOutlined />}
              loading={aiLoadingMode === 'deep'}
              disabled={!!aiLoadingMode}
              onClick={() => handleRunAiAnalysis('deep')}
            >
              深度分析
            </Button>
          </Space>
        }
      >
        {!ai ? (
          <div style={{ color: 'var(--text-muted)', minHeight: 76, display: 'flex', alignItems: 'center' }}>
            点击右上角按钮生成基于系统行情、消息、交易记录的结构化研究摘要。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
              <Progress
                type="dashboard"
                size={76}
                percent={Math.max(0, Math.min(100, Number(ai.score) || 0))}
                format={() => `${ai.score || 0}`}
              />
              <div style={{ flex: 1, minWidth: 260 }}>
                <Space style={{ marginBottom: 8 }} wrap>
                  <Tag color={ratingColor(ai.rating)}>{ai.rating || '观察'}</Tag>
                  <Tag color={trendColor(ai.trend)}>{ai.trend || '震荡'}</Tag>
                  {ai.time_horizon && <Tag>{ai.time_horizon}</Tag>}
                  <Tag>置信度 {ai.confidence ?? '-'}</Tag>
                </Space>
                <div style={{ color: 'var(--text-primary)', fontSize: 15, lineHeight: 1.8 }}>
                  {ai.summary || '暂无摘要'}
                </div>
                <div style={{ marginTop: 4, color: 'var(--text-muted)', fontSize: 12 }}>
                  分析时间：
                  {aiAnalysis?.ai_analyzed_at ? dayjs(aiAnalysis.ai_analyzed_at).format('YYYY-MM-DD HH:mm:ss') : '-'}
                  {aiAnalysis?.data_trade_date ? ` · 数据交易日：${aiAnalysis.data_trade_date}` : ''}
                </div>
              </div>
            </div>

            <Row gutter={[12, 12]}>
              {renderAiSection('技术面', ai.sections?.technical)}
              {renderAiSection('基本面', ai.sections?.fundamental)}
              {renderAiSection('消息面', ai.sections?.news)}
              {renderAiSection('交易观察', ai.sections?.trading)}
            </Row>

            <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 8 }}>观察计划</div>
              <Row gutter={[12, 8]}>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>支撑</div>
                  <div>{plan?.key_levels?.support?.length ? plan.key_levels.support.join(' / ') : '-'}</div>
                </Col>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>压力</div>
                  <div>{plan?.key_levels?.pressure?.length ? plan.key_levels.pressure.join(' / ') : '-'}</div>
                </Col>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>风险线</div>
                  <div>{plan?.key_levels?.risk_line ?? '-'}</div>
                </Col>
              </Row>
              <Row gutter={[12, 8]} style={{ marginTop: 10 }}>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>触发条件</div>
                  <div>{plan?.trigger_conditions?.length ? plan.trigger_conditions.join('；') : '-'}</div>
                </Col>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>失效条件</div>
                  <div>{plan?.invalid_conditions?.length ? plan.invalid_conditions.join('；') : '-'}</div>
                </Col>
                <Col xs={24} md={8}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>复查时机</div>
                  <div>{plan?.next_review || '-'}</div>
                </Col>
              </Row>
            </div>

            {qualityWarnings.length > 0 && (
              <Alert
                type="warning"
                showIcon
                message={`数据质量 ${ai.data_quality?.score ?? '-'}：${qualityWarnings.slice(0, 3).join('；')}`}
              />
            )}
            {ai.disclaimer && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{ai.disclaimer}</div>}
          </div>
        )}
      </Card>

      {SHOW_STOCK_DETAIL_ALERTS_AND_DETAILS && (
        <Card>
          <Tabs
            items={[
              {
                key: 'alerts',
                label: `监控提醒 (${alerts.length})`,
                children: (
                  <Table dataSource={alerts} columns={alertColumns} rowKey="id" size="small" pagination={false} />
                ),
              },
              {
                key: 'details',
                label: `交易明细 (${details.length})`,
                children: (
                  <Table dataSource={details} columns={detailColumns} rowKey="id" size="small" pagination={false} />
                ),
              },
            ]}
          />
        </Card>
      )}

      {/* 快速记录 - 上传截图 OCR */}
      <Modal
        title={`快速记录 - ${basic?.name || tsCode || ''}`}
        open={quickRecordModalOpen}
        onOk={handleQuickRecordSubmit}
        onCancel={() => setQuickRecordModalOpen(false)}
        width={560}
        okText="确认并添加"
      >
        <Upload.Dragger
          accept="image/*"
          showUploadList={false}
          beforeUpload={(file) => { handleOcrUpload(file); return false }}
          disabled={ocrLoading}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined style={{ fontSize: 48, color: ocrLoading ? '#999' : '#1890ff' }} />
          </p>
          <p className="ant-upload-text">
            {ocrLoading ? '识别中...' : '点击或拖拽券商成交截图到此处'}
          </p>
        </Upload.Dragger>
        <div style={{ marginTop: 8, marginBottom: 16 }}>
          <a onClick={handleSkipUpload}>跳过上传，手动填写</a>
        </div>
        {ocrRawText && (
          <div style={{ marginBottom: 16, padding: 8, background: '#f5f5f5', borderRadius: 4, maxHeight: 80, overflow: 'auto', fontSize: 12 }}>
            <div style={{ color: '#666', marginBottom: 4 }}>识别文本（供对照）：</div>
            <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{ocrRawText}</pre>
          </div>
        )}
        <Form form={quickRecordForm} layout="vertical">
          <Form.Item name="trade_date" label="成交日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="trade_time" label="成交时间">
            <Input placeholder="09:35:00（可选）" />
          </Form.Item>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Select options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} />
          </Form.Item>
          <Form.Item name="price" label="成交价格" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="quantity" label="成交数量（股）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="commission" label="佣金">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="exec_note" label="执行备注">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      {/* 添加交易明细 */}
      <Modal title="添加交易明细" open={detailModalOpen} onOk={handleAddDetail} onCancel={() => setDetailModalOpen(false)} width={500}>
        <Form form={detailForm} layout="vertical">
          <Form.Item name="trade_date" label="成交日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="trade_time" label="成交时间">
            <Input placeholder="09:35:00（可选）" />
          </Form.Item>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Select options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} />
          </Form.Item>
          <Form.Item name="price" label="成交价格" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="quantity" label="成交数量（股）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="commission" label="佣金">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="exec_note" label="执行备注">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑交易明细 */}
      <Modal title="编辑交易明细" open={editDetailModalOpen} onOk={handleEditDetail} onCancel={() => { setEditDetailModalOpen(false); setEditingDetail(null) }} width={500}>
        <Form form={editDetailForm} layout="vertical">
          <Form.Item name="trade_date" label="成交日期" rules={[{ required: true }]}>
            <DatePicker style={{ width: '100%' }} format="YYYY-MM-DD" />
          </Form.Item>
          <Form.Item name="trade_time" label="成交时间">
            <Input placeholder="09:35:00（可选）" />
          </Form.Item>
          <Form.Item name="direction" label="方向" rules={[{ required: true }]}>
            <Select options={[{ value: 'buy', label: '买入' }, { value: 'sell', label: '卖出' }]} />
          </Form.Item>
          <Form.Item name="price" label="成交价格" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="quantity" label="成交数量（股）" rules={[{ required: true }]}>
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="commission" label="佣金">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="exec_note" label="执行备注">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>
      </div>
    </div>
  )
}

export default StockDetail
