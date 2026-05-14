import React, { useEffect, useMemo, useState } from 'react'
import {
  Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, Space, Checkbox, message, Progress, DatePicker,
} from 'antd'
import { FilterOutlined, RobotOutlined, PlusOutlined, ThunderboltOutlined, ExperimentOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useNavigate } from 'react-router-dom'
import {
  getScreenTemplates, getLimitUpTemplates, runIndicatorScreen, runAiScreen, runLimitUpBuyPointScreen, runBacktest, getScreenResult,
  type ScreenTemplate, type ScreenCondition, type ScreenResult, type BacktestResult,
} from '../../api/strategy'
import { listPools, batchAddStocks, quickCreatePool } from '../../api/pools'
import type { JsonObject, Pool } from '../../types'

const MAX_CONDITIONS = 10
const AI_DESC_MAX = 200
type StrategyTabKey = 'indicator' | 'ai' | 'limit_up' | 'backtest'
type ConditionField = 'template_id' | 'params'

interface ApiErrorLike {
  response?: {
    data?: {
      message?: string
    }
  }
}

const toConditionParams = (
  params: JsonObject | undefined,
  patch: Record<string, unknown>
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
  const [activeTab, setActiveTab] = useState<StrategyTabKey>('indicator')
  const [scope, setScope] = useState<string>('full')
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
  }, [])

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

  const resultItems = result?.ts_codes?.map((c) => ({
    ts_code: c,
    stock_name: result.stock_names?.[c] || '',
  })) || []

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
  ]

  return (
    <div>
      <Card title="策略选股" extra={<FilterOutlined style={{ fontSize: 20 }} />}>
        <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as StrategyTabKey)}>
          <Tabs.TabPane tab="指标组合选股" key="indicator">
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
          </Tabs.TabPane>

          <Tabs.TabPane tab="涨停回调买点" key="limit_up">
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
          </Tabs.TabPane>

          <Tabs.TabPane tab="策略回测" key="backtest">
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
          </Tabs.TabPane>

          <Tabs.TabPane tab="AI 智能选股" key="ai">
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
          </Tabs.TabPane>
        </Tabs>

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
