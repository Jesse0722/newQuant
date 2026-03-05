import React, { useEffect, useState } from 'react'
import {
  Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, Space, Checkbox, message, Progress,
} from 'antd'
import { FilterOutlined, RobotOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  getScreenTemplates, runIndicatorScreen, runAiScreen, getScreenResult,
  type ScreenTemplate, type ScreenCondition, type ScreenResult,
} from '../../api/strategy'
import { listPools, batchAddStocks, quickCreatePool } from '../../api/pools'
import type { Pool } from '../../types'

const MAX_CONDITIONS = 10
const AI_DESC_MAX = 200

const StrategyPage: React.FC = () => {
  const [templates, setTemplates] = useState<ScreenTemplate[]>([])
  const [pools, setPools] = useState<Pool[]>([])
  const [activeTab, setActiveTab] = useState<'indicator' | 'ai'>('indicator')
  const [scope, setScope] = useState<string>('full')
  const [conditions, setConditions] = useState<ScreenCondition[]>([])
  const [logic, setLogic] = useState<string>('and')
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

  const updateCondition = (i: number, field: string, value: any) => {
    const next = [...conditions]
    if (field === 'template_id') {
      const t = templates.find((x) => x.id === value)
      next[i] = { template_id: value, params: t?.default_params || {} }
    } else {
      (next[i] as any)[field] = value
    }
    setConditions(next)
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
    } catch (e: any) {
      message.error(e.response?.data?.message || '添加失败')
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
    } catch (e: any) {
      message.error(e.response?.data?.message || '创建失败')
    }
  }

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
      render: (_: any, r: { ts_code: string }) => (
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
    { title: '股票名称', dataIndex: 'stock_name', render: (v: string) => v || '-' },
  ]

  return (
    <div>
      <Card title="策略选股" extra={<FilterOutlined style={{ fontSize: 20 }} />}>
        <Tabs activeKey={activeTab} onChange={(k) => setActiveTab(k as any)}>
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
                      <InputNumber size="small" value={c.params?.n1} onChange={(v) => updateCondition(i, 'params', { ...c.params, n1: v })} placeholder="N1" style={{ width: 60 }} />
                      <InputNumber size="small" value={c.params?.n2} onChange={(v) => updateCondition(i, 'params', { ...c.params, n2: v })} placeholder="N2" style={{ width: 60 }} />
                    </>
                  )}
                  {(c.template_id === 'ma_above' || c.template_id === 'ma_below' || c.template_id === 'breakout_high') && (
                    <InputNumber size="small" value={c.params?.n} onChange={(v) => updateCondition(i, 'params', { ...c.params, n: v })} placeholder="N" style={{ width: 80 }} />
                  )}
                  {c.template_id === 'rsi_oversold' && (
                    <>
                      <InputNumber size="small" value={c.params?.threshold} onChange={(v) => updateCondition(i, 'params', { ...c.params, threshold: v })} placeholder="阈值" style={{ width: 70 }} />
                    </>
                  )}
                  {c.template_id === 'price_vs_ma' && (
                    <>
                      <InputNumber size="small" value={c.params?.n} onChange={(v) => updateCondition(i, 'params', { ...c.params, n: v })} placeholder="N" style={{ width: 60 }} />
                      <Select value={c.params?.op} onChange={(v) => updateCondition(i, 'params', { ...c.params, op: v })} style={{ width: 60 }} options={[
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
            <h4>选股结果（共 {result.total} 只）</h4>
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
