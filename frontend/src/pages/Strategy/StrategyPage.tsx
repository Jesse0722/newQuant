import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, Space, Checkbox, message, Progress, DatePicker, Tag, Switch,
} from 'antd'
import { FilterOutlined, RobotOutlined, PlusOutlined, ThunderboltOutlined, ExperimentOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  getScreenTemplates, getLimitUpTemplates, runIndicatorScreen, runAiScreen, runLimitUpBuyPointScreen, runBacktest, getScreenResult, runMainWaveScreen,
  type ScreenTemplate, type ScreenCondition, type ScreenResult, type BacktestResult, type MainWaveScreenParams, type MainWaveScreenResultItem,
} from '../../api/strategy'
import { listSectors, type SectorBasicItem } from '../../api/market'
import { listPools, batchAddStocks, quickCreatePool } from '../../api/pools'
import type { JsonObject, JsonValue, Pool } from '../../types'
import { upsertNotification } from '../../services/notificationCenter'

const MAX_CONDITIONS = 10
const AI_DESC_MAX = 200
type StrategyTabKey = 'indicator' | 'main_wave' | 'ai' | 'limit_up' | 'backtest'
type ConditionField = 'template_id' | 'params'

const MAIN_WAVE_STATUS_OPTIONS = [
  { value: 'main_wave_confirmed', label: '主升确认' },
  { value: 'breakout_tracking', label: '突破跟踪' },
  { value: 'watching', label: '观察中' },
  { value: 'divergence_warning', label: '分歧预警' },
  { value: 'exit_signal', label: '退出信号' },
]

const STRATEGY_TAB_OPTIONS: Array<{ key: StrategyTabKey; label: string }> = [
  { key: 'indicator', label: '指标组合选股' },
  { key: 'main_wave', label: '主升浪趋势' },
  { key: 'limit_up', label: '涨停回调买点' },
  { key: 'backtest', label: '策略回测' },
  { key: 'ai', label: 'AI 智能选股' },
]

const isStrategyTabKey = (value: string | null): value is StrategyTabKey =>
  STRATEGY_TAB_OPTIONS.some((item) => item.key === value)

const MAIN_WAVE_STATUS_LABEL: Record<string, { label: string; color: string }> = {
  main_wave_confirmed: { label: '主升确认', color: 'green' },
  breakout_tracking: { label: '突破跟踪', color: 'blue' },
  watching: { label: '观察中', color: 'cyan' },
  divergence_warning: { label: '分歧预警', color: 'orange' },
  exit_signal: { label: '退出信号', color: 'red' },
  invalidated: { label: '结构失效', color: 'default' },
}

const DEFAULT_MAIN_WAVE_PARAMS: MainWaveScreenParams = {
  scope: 'full',
  sector_codes: [],
  sector_logic: 'any',
  min_score: 70,
  statuses: ['main_wave_confirmed', 'breakout_tracking', 'watching', 'divergence_warning'],
  require_sector_resonance: true,
  exclude_effective_break: true,
  exclude_st: true,
  min_data_days: 120,
  min_price: 5,
  max_price: null,
  min_float_market_cap_yi: 30,
  min_avg_amount_20d_yi: 2,
  max_return_60d: 150,
  max_ma20_distance_pct: 25,
  min_sector_return_20d: 5,
  min_relative_strength_20d: 0,
}

interface ApiErrorLike {
  response?: {
    data?: {
      message?: string
    }
  }
}

const toConditionParams = (
  params: JsonObject | undefined,
  patch: Record<string, JsonValue>
): JsonObject => ({ ...(params ?? {}), ...patch })

const updateConditionList = (
  list: ScreenCondition[],
  templates: ScreenTemplate[],
  index: number,
  field: ConditionField,
  value: string | JsonObject
): ScreenCondition[] => {
  return list.map((item, itemIndex) => {
    if (itemIndex !== index) return item
    if (field === 'template_id') {
      const template = templates.find((entry) => entry.id === value)
      return {
        template_id: String(value),
        params: template?.default_params ?? {},
      }
    }
    return {
      ...item,
      params: value as JsonObject,
    }
  })
}

const StrategyPage: React.FC = () => {
  const [templates, setTemplates] = useState<ScreenTemplate[]>([])
  const [limitUpTemplates, setLimitUpTemplates] = useState<ScreenTemplate[]>([])
  const [pools, setPools] = useState<Pool[]>([])
  const [sectors, setSectors] = useState<SectorBasicItem[]>([])
  const [activeTab, setActiveTab] = useState<StrategyTabKey>(() => {
    const tab = new URLSearchParams(window.location.search).get('tab')
    return isStrategyTabKey(tab) ? tab : 'indicator'
  })
  const [scope, setScope] = useState<string>('full')
  const [mainWaveParams, setMainWaveParams] = useState<MainWaveScreenParams>(DEFAULT_MAIN_WAVE_PARAMS)
  const [conditions, setConditions] = useState<ScreenCondition[]>([])
  const [logic, setLogic] = useState<string>('and')
  const [limitUpConditions, setLimitUpConditions] = useState<ScreenCondition[]>([])
  const [limitUpLogic, setLimitUpLogic] = useState<string>('and')
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
  const [backtestDateRange, setBacktestDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
  const [backtestConditions, setBacktestConditions] = useState<ScreenCondition[]>([])
  const [backtestLogic, setBacktestLogic] = useState<string>('and')
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null)
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [aiDesc, setAiDesc] = useState('')
  const [taskId, setTaskId] = useState<string | null>(null)
  const [result, setResult] = useState<ScreenResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [quickCreateOpen, setQuickCreateOpen] = useState(false)
  const [selectedPoolId, setSelectedPoolId] = useState<string>('')
  const [selectedRows, setSelectedRows] = useState<string[]>([])
  const [quickForm] = Form.useForm()
  const navigate = useNavigate()

  useEffect(() => {
    getScreenTemplates().then((r) => setTemplates(r.data))
    getLimitUpTemplates().then((r) => setLimitUpTemplates(r.data))
    listPools().then((r) => setPools(r.data))
    listSectors({ sector_type: 'concept', limit: 500 }).then((r) => setSectors(r.data))
  }, [])

  const updateMainWaveParams = (patch: Partial<MainWaveScreenParams>) => {
    setMainWaveParams((prev) => ({ ...prev, ...patch }))
  }

  const switchStrategyTab = (key: StrategyTabKey) => {
    setActiveTab(key)
    const url = new URL(window.location.href)
    url.searchParams.set('tab', key)
    window.history.replaceState(null, '', `${url.pathname}${url.search}${url.hash}`)
  }

  const handleStrategyTabClick = (event: React.MouseEvent) => {
    const target = event.target as HTMLElement
    const text = target.closest?.('.ant-tabs-tab')?.textContent?.trim() || target.textContent?.trim()
    const tab = STRATEGY_TAB_OPTIONS.find((item) => item.label === text)
    if (tab) switchStrategyTab(tab.key)
  }

  const addCondition = () => {
    if (conditions.length >= MAX_CONDITIONS) {
      message.warning(`最多 ${MAX_CONDITIONS} 个条件`)
      return
    }
    const t = templates[0]
    setConditions([...conditions, { template_id: t?.id || 'ma_above', params: t?.default_params || { n: 20 } }])
  }

  const removeCondition = (i: number) => {
    setConditions(conditions.filter((_, idx) => idx !== i))
  }

  const updateCondition = (i: number, field: ConditionField, value: string | JsonObject) => {
    setConditions((prev) => updateConditionList(prev, templates, i, field, value))
  }

  const runIndicator = async () => {
    if (conditions.length === 0) {
      message.warning('请至少添加一个条件')
      return
    }
    if (!scope) {
      message.warning('请选择选股范围')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const res = await runIndicatorScreen({ scope, conditions, logic })
      setTaskId(res.data.task_id)
    } catch {
      setLoading(false)
    }
  }

  const addLimitUpCondition = () => {
    if (limitUpConditions.length >= MAX_CONDITIONS) {
      message.warning(`最多 ${MAX_CONDITIONS} 个条件`)
      return
    }
    const t = limitUpTemplates[0]
    setLimitUpConditions([...limitUpConditions, { template_id: t?.id || 'ma_support', params: t?.default_params || {} }])
  }

  const removeLimitUpCondition = (i: number) => {
    setLimitUpConditions(limitUpConditions.filter((_, idx) => idx !== i))
  }

  const updateLimitUpCondition = (i: number, field: ConditionField, value: string | JsonObject) => {
    setLimitUpConditions((prev) => updateConditionList(prev, limitUpTemplates, i, field, value))
  }

  const runLimitUp = async () => {
    if (limitUpConditions.length === 0) {
      message.warning('请至少添加一个买点条件')
      return
    }
    if (!dateRange || dateRange.length !== 2) {
      message.warning('请选择日期范围')
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const res = await runLimitUpBuyPointScreen({
        trade_date_from: dateRange[0].format('YYYYMMDD'),
        trade_date_to: dateRange[1].format('YYYYMMDD'),
        conditions: limitUpConditions,
        logic: limitUpLogic,
      })
      setTaskId(res.data.task_id)
    } catch {
      setLoading(false)
    }
  }

  const runMainWave = async () => {
    setLoading(true)
    setResult(null)
    setSelectedRows([])
    try {
      const payload: MainWaveScreenParams = {
        ...mainWaveParams,
        scope: mainWaveParams.scope || 'full',
        sector_codes: mainWaveParams.sector_codes || [],
      }
      const res = await runMainWaveScreen(payload)
      setTaskId(res.data.task_id)
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      message.error(apiError.response?.data?.message || '主升浪选股提交失败')
      setLoading(false)
    }
  }

  const addBacktestCondition = () => {
    if (backtestConditions.length >= MAX_CONDITIONS) {
      message.warning(`最多 ${MAX_CONDITIONS} 个条件`)
      return
    }
    const t = limitUpTemplates[0]
    setBacktestConditions([...backtestConditions, { template_id: t?.id || 'ma_support', params: t?.default_params || {} }])
  }

  const removeBacktestCondition = (i: number) => {
    setBacktestConditions(backtestConditions.filter((_, idx) => idx !== i))
  }

  const updateBacktestCondition = (i: number, field: ConditionField, value: string | JsonObject) => {
    setBacktestConditions((prev) => updateConditionList(prev, limitUpTemplates, i, field, value))
  }

  const runBacktestFn = async () => {
    if (backtestConditions.length === 0) {
      message.warning('请至少添加一个买点条件')
      return
    }
    if (!backtestDateRange || backtestDateRange.length !== 2) {
      message.warning('请选择日期范围')
      return
    }
    setBacktestLoading(true)
    setBacktestResult(null)
    try {
      const res = await runBacktest({
        trade_date_from: backtestDateRange[0].format('YYYYMMDD'),
        trade_date_to: backtestDateRange[1].format('YYYYMMDD'),
        conditions: backtestConditions,
        logic: backtestLogic,
      })
      setBacktestResult(res.data)
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      message.error(apiError.response?.data?.message || '回测失败')
    } finally {
      setBacktestLoading(false)
    }
  }

  const runAi = async () => {
    const desc = aiDesc.trim()
    if (!desc) {
      message.warning('请输入选股描述')
      return
    }
    if (desc.length > AI_DESC_MAX) {
      message.warning(`描述不超过 ${AI_DESC_MAX} 字`)
      return
    }
    setLoading(true)
    setResult(null)
    try {
      const res = await runAiScreen({ description: desc, scope: scope || 'full' })
      setTaskId(res.data.task_id)
      const now = new Date().toISOString()
      upsertNotification({
        id: `ai-screen:${res.data.task_id}`,
        kind: 'ai_screen',
        status: 'running',
        title: 'AI 智能选股中',
        description: '任务已提交，完成后会在顶部消息中心提醒',
        createdAt: now,
        updatedAt: now,
        read: false,
        taskId: res.data.task_id,
        link: '/strategy',
        meta: {
          mode: 'deep',
        },
      })
    } catch {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!taskId) return
    const poll = setInterval(async () => {
      try {
        const r = await getScreenResult(taskId)
        setResult(r.data)
        if (r.data.status === 'completed' || r.data.status === 'failed') {
          clearInterval(poll)
          setLoading(false)
          setTaskId(null)
          if (r.data.status === 'failed') message.error(r.data.message)
        }
      } catch {
        clearInterval(poll)
        setLoading(false)
      }
    }, 1500)
    return () => clearInterval(poll)
  }, [taskId])

  const resultItems = result?.items?.length
    ? result.items
    : (result?.ts_codes?.map((c) => ({
      ts_code: c,
      stock_name: result.stock_names?.[c] || '',
    })) || [])

  const handleBatchAdd = async (poolId: string) => {
    const codes = selectedRows.length > 0 ? selectedRows : resultItems.map((x) => x.ts_code)
    if (codes.length === 0) {
      message.warning('没有可添加的股票')
      return
    }
    try {
      const res = await batchAddStocks(poolId, { ts_codes: codes })
      message.success(`已添加 ${res.data.added} 只，跳过 ${res.data.skipped} 只`)
      setAddModalOpen(false)
      setSelectedRows([])
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      message.error(apiError.response?.data?.message || '添加失败')
    }
  }

  const handleQuickCreate = async () => {
    const values = await quickForm.validateFields()
    const codes = selectedRows.length > 0 ? selectedRows : resultItems.map((x) => x.ts_code)
    if (codes.length === 0) {
      message.warning('没有可添加的股票')
      return
    }
    try {
      const res = await quickCreatePool({ name: values.name, ts_codes: codes, description: values.description })
      message.success(`已创建观察池「${res.data.name}」并添加 ${codes.length} 只股票`)
      setQuickCreateOpen(false)
      setSelectedRows([])
      listPools().then((r) => setPools(r.data))
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      message.error(apiError.response?.data?.message || '创建失败')
    }
  }

  const filteredResultCount = useMemo(
    () => resultItems.length,
    [resultItems.length]
  )

  const resultColumns = [
    {
      title: (
        <Checkbox
          checked={selectedRows.length === resultItems.length && resultItems.length > 0}
          indeterminate={selectedRows.length > 0 && selectedRows.length < resultItems.length}
          onChange={(e) => setSelectedRows(e.target.checked ? resultItems.map((x) => x.ts_code) : [])}
        />
      ),
      width: 40,
      render: (_: unknown, r: { ts_code: string }) => (
        <Checkbox
          checked={selectedRows.includes(r.ts_code)}
          onChange={(e) => {
            if (e.target.checked) setSelectedRows([...selectedRows, r.ts_code])
            else setSelectedRows(selectedRows.filter((c) => c !== r.ts_code))
          }}
        />
      ),
    },
    {
      title: '股票代码',
      dataIndex: 'ts_code',
      render: (v: string) => <a onClick={() => navigate(`/stocks/${v}`)}>{v}</a>,
    },
    { title: '股票名称', dataIndex: 'stock_name', render: (v: string, r: { ts_code: string }) => <a onClick={() => navigate(`/stocks/${r.ts_code}`)}>{v || '-'}</a> },
    ...(activeTab === 'main_wave' ? [
      {
        title: '状态',
        dataIndex: 'status',
        render: (v: string) => {
          const meta = MAIN_WAVE_STATUS_LABEL[v] || { label: v || '-', color: 'default' }
          return <Tag color={meta.color}>{meta.label}</Tag>
        },
      },
      { title: '总分', dataIndex: 'total_score', sorter: (a: MainWaveScreenResultItem, b: MainWaveScreenResultItem) => Number(a.total_score || 0) - Number(b.total_score || 0) },
      {
        title: '评分拆解',
        render: (_: unknown, r: MainWaveScreenResultItem) => (
          <span>{r.trend_score ?? 0}/{r.structure_score ?? 0}/{r.pullback_repair_score ?? 0}/{r.sector_resonance_score ?? 0}</span>
        ),
      },
      {
        title: '共振板块',
        render: (_: unknown, r: MainWaveScreenResultItem) => r.best_sector?.sector_name || '-',
      },
      {
        title: '20日/60日',
        render: (_: unknown, r: MainWaveScreenResultItem) => `${r.return_20d ?? '-'}% / ${r.return_60d ?? '-'}%`,
      },
      {
        title: '相对板块',
        dataIndex: 'relative_strength_20d',
        render: (v: number | null) => v == null ? '-' : `${v}%`,
      },
    ] : []),
  ]

  return (
    <div>
      <Card
        title="策略选股"
        extra={<FilterOutlined style={{ fontSize: 20 }} />}
        onClickCapture={handleStrategyTabClick}
        onPointerDownCapture={handleStrategyTabClick}
      >
        <Tabs
          activeKey={activeTab}
          onChange={(k) => switchStrategyTab(k as StrategyTabKey)}
          onTabClick={(k) => switchStrategyTab(k as StrategyTabKey)}
          items={STRATEGY_TAB_OPTIONS.map((item) => ({ key: item.key, label: item.label }))}
        />

        {activeTab === 'indicator' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>选股范围：</span>
                <Select
                  value={scope}
                  onChange={setScope}
                  style={{ width: 200 }}
                  placeholder="选择观察池或全市场"
                  options={[
                    { value: 'full', label: '全市场 A 股' },
                    ...pools.map((p) => ({ value: p.id, label: `${p.name} (${p.stock_count})` })),
                  ]}
                />
                <span>条件逻辑：</span>
                <Select value={logic} onChange={setLogic} style={{ width: 80 }} options={[
                  { value: 'and', label: '且' },
                  { value: 'or', label: '或' },
                ]} />
              </Space>
            </div>
            <div style={{ marginBottom: 16 }}>
              {conditions.map((c, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Select
                    value={c.template_id}
                    onChange={(v) => updateCondition(i, 'template_id', v)}
                    style={{ width: 140 }}
                    options={templates.map((t) => ({ value: t.id, label: t.name }))}
                  />
                  {c.template_id === 'ma_cross' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.n1)} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { n1: v }))} placeholder="N1" style={{ width: 60 }} />
                      <InputNumber size="small" value={Number(c.params?.n2)} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { n2: v }))} placeholder="N2" style={{ width: 60 }} />
                    </>
                  )}
                  {(c.template_id === 'ma_above' || c.template_id === 'ma_below' || c.template_id === 'breakout_high') && (
                    <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 80 }} />
                  )}
                  {c.template_id === 'rsi_oversold' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.threshold)} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { threshold: v }))} placeholder="阈值" style={{ width: 70 }} />
                    </>
                  )}
                  {c.template_id === 'price_vs_ma' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 60 }} />
                      <Select value={typeof c.params?.op === 'string' ? c.params.op : undefined} onChange={(v) => updateCondition(i, 'params', toConditionParams(c.params, { op: v }))} style={{ width: 60 }} options={[
                        { value: '>', label: '>' },
                        { value: '<', label: '<' },
                        { value: '>=', label: '>=' },
                        { value: '<=', label: '<=' },
                      ]} />
                    </>
                  )}
                  <Button size="small" type="link" danger onClick={() => removeCondition(i)}>删除</Button>
                </div>
              ))}
              <Button size="small" icon={<PlusOutlined />} onClick={addCondition} disabled={conditions.length >= MAX_CONDITIONS}>
                添加条件 ({conditions.length}/{MAX_CONDITIONS})
              </Button>
            </div>
            <Button type="primary" loading={loading} onClick={runIndicator}>
              执行选股
            </Button>
          </>
        )}

        {activeTab === 'main_wave' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>扫描范围：</span>
                <Select
                  value={mainWaveParams.scope}
                  onChange={(v) => updateMainWaveParams({ scope: v })}
                  style={{ width: 220 }}
                  options={[
                    { value: 'full', label: '全市场 A 股' },
                    ...pools.map((p) => ({ value: p.id, label: `${p.name} (${p.stock_count})` })),
                  ]}
                />
                <span>概念板块：</span>
                <Select
                  mode="multiple"
                  allowClear
                  showSearch
                  maxTagCount="responsive"
                  value={mainWaveParams.sector_codes}
                  onChange={(v) => updateMainWaveParams({ sector_codes: v })}
                  placeholder="可选，指定后只扫这些概念成分"
                  style={{ width: 360 }}
                  optionFilterProp="label"
                  options={sectors.map((s) => ({
                    value: s.sector_code,
                    label: `${s.sector_name} ${s.sector_code}`,
                  }))}
                />
                <Select
                  value={mainWaveParams.sector_logic}
                  onChange={(v) => updateMainWaveParams({ sector_logic: v })}
                  style={{ width: 110 }}
                  options={[
                    { value: 'any', label: '任一命中' },
                    { value: 'all', label: '同时命中' },
                  ]}
                />
              </Space>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>最低总分</span>
                <InputNumber value={mainWaveParams.min_score} min={0} max={100} onChange={(v) => updateMainWaveParams({ min_score: Number(v ?? 70) })} style={{ width: 90 }} />
                <span>状态</span>
                <Select
                  mode="multiple"
                  value={mainWaveParams.statuses}
                  onChange={(v) => updateMainWaveParams({ statuses: v })}
                  style={{ width: 360 }}
                  maxTagCount="responsive"
                  options={MAIN_WAVE_STATUS_OPTIONS}
                />
                <span>最低数据日</span>
                <InputNumber value={mainWaveParams.min_data_days} min={60} max={500} onChange={(v) => updateMainWaveParams({ min_data_days: Number(v ?? 120) })} style={{ width: 90 }} />
              </Space>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>价格</span>
                <InputNumber value={mainWaveParams.min_price ?? undefined} min={0} step={0.5} placeholder="最低" onChange={(v) => updateMainWaveParams({ min_price: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <InputNumber value={mainWaveParams.max_price ?? undefined} min={0} step={0.5} placeholder="最高" onChange={(v) => updateMainWaveParams({ max_price: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>流通市值(亿)</span>
                <InputNumber value={mainWaveParams.min_float_market_cap_yi ?? undefined} min={0} onChange={(v) => updateMainWaveParams({ min_float_market_cap_yi: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>20日成交额(亿)</span>
                <InputNumber value={mainWaveParams.min_avg_amount_20d_yi ?? undefined} min={0} step={0.5} onChange={(v) => updateMainWaveParams({ min_avg_amount_20d_yi: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>60日涨幅上限</span>
                <InputNumber value={mainWaveParams.max_return_60d ?? undefined} min={0} onChange={(v) => updateMainWaveParams({ max_return_60d: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>MA20乖离上限</span>
                <InputNumber value={mainWaveParams.max_ma20_distance_pct ?? undefined} min={0} onChange={(v) => updateMainWaveParams({ max_ma20_distance_pct: v == null ? null : Number(v) })} style={{ width: 90 }} />
              </Space>
            </div>

            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>板块20日涨幅</span>
                <InputNumber value={mainWaveParams.min_sector_return_20d ?? undefined} onChange={(v) => updateMainWaveParams({ min_sector_return_20d: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>相对板块强弱</span>
                <InputNumber value={mainWaveParams.min_relative_strength_20d ?? undefined} onChange={(v) => updateMainWaveParams({ min_relative_strength_20d: v == null ? null : Number(v) })} style={{ width: 90 }} />
                <span>必须板块共振</span>
                <Switch checked={mainWaveParams.require_sector_resonance} onChange={(v) => updateMainWaveParams({ require_sector_resonance: v })} />
                <span>排除有效跌破MA20</span>
                <Switch checked={mainWaveParams.exclude_effective_break} onChange={(v) => updateMainWaveParams({ exclude_effective_break: v })} />
                <span>剔除ST</span>
                <Switch checked={mainWaveParams.exclude_st} onChange={(v) => updateMainWaveParams({ exclude_st: v })} />
              </Space>
            </div>

            <Button type="primary" loading={loading} onClick={runMainWave}>
              执行主升浪选股
            </Button>
          </>
        )}

        {activeTab === 'limit_up' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>日期范围：</span>
                <DatePicker.RangePicker
                  value={dateRange}
                  onChange={(v) => {
                    if (v?.[0] && v[1]) setDateRange([v[0], v[1]])
                    else setDateRange(null)
                  }}
                  format="YYYY-MM-DD"
                  style={{ width: 260 }}
                />
                <span>条件逻辑：</span>
                <Select value={limitUpLogic} onChange={setLimitUpLogic} style={{ width: 80 }} options={[
                  { value: 'and', label: '且' },
                  { value: 'or', label: '或' },
                ]} />
              </Space>
            </div>
            <div style={{ marginBottom: 16 }}>
              {limitUpConditions.map((c, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Select
                    value={c.template_id}
                    onChange={(v) => updateLimitUpCondition(i, 'template_id', v)}
                    style={{ width: 160 }}
                    options={limitUpTemplates.map((t) => ({ value: t.id, label: t.name }))}
                  />
                  {c.template_id === 'ma_support' && (
                    <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 80 }} />
                  )}
                  {c.template_id === 'limit_up_price_support' && (
                    <InputNumber size="small" value={Number(c.params?.tolerance)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { tolerance: v }))} placeholder="tolerance" style={{ width: 90 }} step={0.01} />
                  )}
                  {c.template_id === 'days_since_limit_up' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.min_days)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { min_days: v }))} placeholder="最小" style={{ width: 70 }} />
                      <InputNumber size="small" value={Number(c.params?.max_days)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { max_days: v }))} placeholder="最大" style={{ width: 70 }} />
                    </>
                  )}
                  {c.template_id === 'fibonacci_retrace' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.level)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { level: v }))} placeholder="level" style={{ width: 80 }} step={0.01} />
                      <InputNumber size="small" value={Number(c.params?.tolerance)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { tolerance: v }))} placeholder="tolerance" style={{ width: 90 }} step={0.01} />
                    </>
                  )}
                  {c.template_id === 'volume_shrink' && (
                    <InputNumber size="small" value={Number(c.params?.ratio)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { ratio: v }))} placeholder="ratio" style={{ width: 80 }} step={0.1} />
                  )}
                  {c.template_id === 'price_threshold' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.ratio)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { ratio: v }))} placeholder="ratio" style={{ width: 80 }} step={0.01} />
                    </>
                  )}
                  {c.template_id === 'rsi_oversold' && (
                    <InputNumber size="small" value={Number(c.params?.threshold)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { threshold: v }))} placeholder="阈值" style={{ width: 70 }} />
                  )}
                  {c.template_id === 'breakout_high' && (
                    <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateLimitUpCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 80 }} />
                  )}
                  <Button size="small" type="link" danger onClick={() => removeLimitUpCondition(i)}>删除</Button>
                </div>
              ))}
              <Button size="small" icon={<PlusOutlined />} onClick={addLimitUpCondition} disabled={limitUpConditions.length >= MAX_CONDITIONS}>
                添加条件 ({limitUpConditions.length}/{MAX_CONDITIONS})
              </Button>
            </div>
            <Button type="primary" icon={<ThunderboltOutlined />} loading={loading} onClick={runLimitUp}>
              执行选股
            </Button>
          </>
        )}

        {activeTab === 'backtest' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space wrap>
                <span>日期范围：</span>
                <DatePicker.RangePicker
                  value={backtestDateRange}
                  onChange={(v) => {
                    if (v?.[0] && v[1]) setBacktestDateRange([v[0], v[1]])
                    else setBacktestDateRange(null)
                  }}
                  format="YYYY-MM-DD"
                  style={{ width: 260 }}
                />
                <span>条件逻辑：</span>
                <Select value={backtestLogic} onChange={setBacktestLogic} style={{ width: 80 }} options={[
                  { value: 'and', label: '且' },
                  { value: 'or', label: '或' },
                ]} />
              </Space>
            </div>
            <div style={{ marginBottom: 16 }}>
              {backtestConditions.map((c, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                  <Select
                    value={c.template_id}
                    onChange={(v) => updateBacktestCondition(i, 'template_id', v)}
                    style={{ width: 160 }}
                    options={limitUpTemplates.map((t) => ({ value: t.id, label: t.name }))}
                  />
                  {c.template_id === 'ma_support' && (
                    <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 80 }} />
                  )}
                  {c.template_id === 'limit_up_price_support' && (
                    <InputNumber size="small" value={Number(c.params?.tolerance)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { tolerance: v }))} placeholder="tolerance" style={{ width: 90 }} step={0.01} />
                  )}
                  {c.template_id === 'days_since_limit_up' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.min_days)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { min_days: v }))} placeholder="最小" style={{ width: 70 }} />
                      <InputNumber size="small" value={Number(c.params?.max_days)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { max_days: v }))} placeholder="最大" style={{ width: 70 }} />
                    </>
                  )}
                  {c.template_id === 'fibonacci_retrace' && (
                    <>
                      <InputNumber size="small" value={Number(c.params?.level)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { level: v }))} placeholder="level" style={{ width: 80 }} step={0.01} />
                      <InputNumber size="small" value={Number(c.params?.tolerance)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { tolerance: v }))} placeholder="tolerance" style={{ width: 90 }} step={0.01} />
                    </>
                  )}
                  {c.template_id === 'volume_shrink' && (
                    <InputNumber size="small" value={Number(c.params?.ratio)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { ratio: v }))} placeholder="ratio" style={{ width: 80 }} step={0.1} />
                  )}
                  {c.template_id === 'price_threshold' && (
                    <InputNumber size="small" value={Number(c.params?.ratio)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { ratio: v }))} placeholder="ratio" style={{ width: 80 }} step={0.01} />
                  )}
                  {c.template_id === 'rsi_oversold' && (
                    <InputNumber size="small" value={Number(c.params?.threshold)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { threshold: v }))} placeholder="阈值" style={{ width: 70 }} />
                  )}
                  {c.template_id === 'breakout_high' && (
                    <InputNumber size="small" value={Number(c.params?.n)} onChange={(v) => updateBacktestCondition(i, 'params', toConditionParams(c.params, { n: v }))} placeholder="N" style={{ width: 80 }} />
                  )}
                  <Button size="small" type="link" danger onClick={() => removeBacktestCondition(i)}>删除</Button>
                </div>
              ))}
              <Button size="small" icon={<PlusOutlined />} onClick={addBacktestCondition} disabled={backtestConditions.length >= MAX_CONDITIONS}>
                添加条件 ({backtestConditions.length}/{MAX_CONDITIONS})
              </Button>
            </div>
            <Button type="primary" icon={<ExperimentOutlined />} loading={backtestLoading} onClick={runBacktestFn}>
              执行回测
            </Button>

            {backtestResult && (
              <div style={{ marginTop: 24 }}>
                <h4>回测结果</h4>
                <div style={{ marginBottom: 16, display: 'flex', gap: 24 }}>
                  <span>平均次日收益：<strong style={{ color: backtestResult.avg_pct >= 0 ? '#52c41a' : '#ff4d4f' }}>{backtestResult.avg_pct}%</strong></span>
                  <span>胜率：<strong>{backtestResult.win_rate}%</strong></span>
                  <span>信号数：<strong>{backtestResult.total_signals}</strong></span>
                </div>
                {backtestResult.signals.length > 0 && (
                  <Table
                    dataSource={backtestResult.signals}
                    columns={[
                      { title: '触发日期', dataIndex: 'trigger_date', width: 110 },
                      { title: '股票代码', dataIndex: 'ts_code', render: (v: string) => <a onClick={() => navigate(`/stocks/${v}`)}>{v}</a> },
                      { title: '次日涨跌幅(%)', dataIndex: 'next_day_pct', render: (v: number) => <span style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>{v}%</span> },
                    ]}
                    rowKey={(r) => `${r.trigger_date}-${r.ts_code}`}
                    size="small"
                    pagination={{ pageSize: 20 }}
                  />
                )}
              </div>
            )}
          </>
        )}

        {activeTab === 'ai' && (
          <>
            <div style={{ marginBottom: 16 }}>
              <p style={{ color: '#666', marginBottom: 8 }}>用一句话描述选股条件，如「找出 RSI 超卖且 MACD 即将金叉的银行股」</p>
              <Input.TextArea
                value={aiDesc}
                onChange={(e) => setAiDesc(e.target.value)}
                placeholder="输入选股描述，不超过 200 字"
                rows={4}
                maxLength={AI_DESC_MAX}
                showCount
              />
              <div style={{ marginTop: 8 }}>
                <span>可选范围：</span>
                <Select
                  value={scope || 'full'}
                  onChange={(v) => setScope(v === 'full' ? '' : v)}
                  style={{ width: 200, marginLeft: 8 }}
                  options={[
                    { value: 'full', label: '全市场' },
                    ...pools.map((p) => ({ value: p.id, label: p.name })),
                  ]}
                />
              </div>
            </div>
            <Button type="primary" icon={<RobotOutlined />} loading={loading} onClick={runAi}>
              AI 选股
            </Button>
          </>
        )}

        {loading && result && (
          <div style={{ marginTop: 24 }}>
            <Progress percent={Math.round(result.progress * 100)} status="active" />
            <p style={{ color: '#666' }}>{result.message}</p>
          </div>
        )}

        {result && result.status === 'completed' && (
          <div style={{ marginTop: 24 }}>
            <h4>选股结果（共 {filteredResultCount} 只）</h4>
            <div style={{ marginBottom: 8 }}>
              <Button type="primary" size="small" onClick={() => setAddModalOpen(true)}>
                添加到观察池
              </Button>
              <Button size="small" style={{ marginLeft: 8 }} onClick={() => setQuickCreateOpen(true)}>
                快捷创建新池
              </Button>
            </div>
            <Table
              dataSource={resultItems}
              columns={resultColumns}
              rowKey="ts_code"
              size="small"
              pagination={{ pageSize: 20 }}
            />
          </div>
        )}
      </Card>

      <Modal
        title="添加到观察池"
        open={addModalOpen}
        onCancel={() => { setAddModalOpen(false); setSelectedPoolId('') }}
        onOk={() => selectedPoolId && handleBatchAdd(selectedPoolId)}
        okText="确认添加"
      >
        <p>选择已有观察池，将选中的 {selectedRows.length > 0 ? selectedRows.length : resultItems.length} 只股票添加进去</p>
        <Select
          style={{ width: '100%' }}
          placeholder="选择观察池"
          value={selectedPoolId || undefined}
          onChange={setSelectedPoolId}
          options={pools.map((p) => ({ value: p.id, label: `${p.name} (${p.stock_count})` }))}
        />
      </Modal>

      <Modal
        title="快捷创建观察池"
        open={quickCreateOpen}
        onOk={handleQuickCreate}
        onCancel={() => setQuickCreateOpen(false)}
      >
        <Form form={quickForm} layout="vertical">
          <Form.Item name="name" label="池名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：策略选股-202603" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="可选" />
          </Form.Item>
        </Form>
        <p style={{ color: '#999', fontSize: 12 }}>
          将选中的 {selectedRows.length > 0 ? selectedRows.length : resultItems.length} 只股票添加到新池
        </p>
      </Modal>
    </div>
  )
}

export default StrategyPage
