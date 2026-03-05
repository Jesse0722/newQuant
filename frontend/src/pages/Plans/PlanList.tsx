import React, { useEffect, useState } from 'react'
import { Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, Rate, Tag, Space, Popconfirm, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listPlans, createPlan, deletePlan } from '../../api/plans'
import type { TradePlan } from '../../types'

const typeMap: Record<string, string> = { trend: '趋势跟踪', short_term: '短线操作', event_driven: '事件驱动' }
const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待触发', color: 'default' },
  active: { label: '执行中', color: 'blue' },
  completed: { label: '已完结', color: 'green' },
  cancelled: { label: '已取消', color: 'red' },
}

const PlanList: React.FC = () => {
  const [plans, setPlans] = useState<TradePlan[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<string>('')
  const [page, setPage] = useState(1)
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const navigate = useNavigate()

  const fetchPlans = (status?: string, p?: number) => {
    setLoading(true)
    listPlans({ status: status || tab || undefined, page: p || page, size: 20 })
      .then((res) => {
        setPlans(res.data.items)
        setTotal(res.data.total)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchPlans(tab, 1); setPage(1) }, [tab])

  const handleCreate = async () => {
    const values = await form.validateFields()
    const stocks = values.stocks.map((s: any) => ({
      ts_code: s.ts_code,
      risk_level: s.risk_level ?? 3,
      trigger_strategy: s.trigger_strategy,
      event_note: s.event_note,
      action_suggestion: s.action_suggestion,
      planned_buy_price: s.planned_buy_price,
      target_price: s.target_price,
      stop_loss_price: s.stop_loss_price,
      position_plan: s.position_plan,
      note: s.note,
    }))
    await createPlan({
      stocks,
      plan_type: values.plan_type,
      note: values.note,
    })
    message.success('创建成功')
    setModalOpen(false)
    form.resetFields()
    fetchPlans()
  }

  const handleDelete = async (id: string) => {
    await deletePlan(id)
    message.success('已删除')
    fetchPlans()
  }

  const stockDisplay = (r: TradePlan) => {
    if (!r.stocks?.length) return '-'
    if (r.stocks.length === 1) return r.stocks[0].stock_name || r.stocks[0].ts_code
    return `${r.stocks[0].stock_name || r.stocks[0].ts_code} 等${r.stocks.length}只`
  }

  const rrDisplay = (r: TradePlan) => {
    const first = r.stocks?.[0]
    return first?.risk_reward_ratio?.toFixed(2) ?? '-'
  }

  const columns = [
    {
      title: '股票',
      key: 'stock',
      render: (_: any, r: TradePlan) => (
        <a onClick={() => navigate(`/plans/${r.id}`)}>{stockDisplay(r)}</a>
      ),
    },
    { title: '类型', dataIndex: 'plan_type', key: 'plan_type', render: (t: string) => typeMap[t] || t },
    {
      title: '风险等级',
      key: 'risk_level',
      render: (_: any, r: TradePlan) => <Rate disabled value={r.stocks?.[0]?.risk_level ?? 3} count={5} style={{ fontSize: 14 }} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    { title: '盈亏比', key: 'rr', render: (_: any, r: TradePlan) => rrDisplay(r) },
    {
      title: '实际盈亏',
      dataIndex: 'actual_pnl',
      key: 'pnl',
      render: (v: number) =>
        v != null ? <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}</span> : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
    {
      title: '操作',
      key: 'action',
      render: (_: any, r: TradePlan) => (
        <Space>
          <a onClick={() => navigate(`/plans/${r.id}`)}>详情</a>
          <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
            <a style={{ color: 'red' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card
      title="交易计划"
      extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>新建计划</Button>}
    >
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: '', label: '全部' },
          { key: 'pending', label: '待触发' },
          { key: 'active', label: '执行中' },
          { key: 'completed', label: '已完结' },
          { key: 'cancelled', label: '已取消' },
        ]}
      />
      <Table
        dataSource={plans}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ current: page, total, pageSize: 20, onChange: (p) => { setPage(p); fetchPlans(tab, p) } }}
      />

      <Modal title="新建交易计划" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} width={900}>
        <Form form={form} layout="vertical" initialValues={{ plan_type: 'trend', stocks: [{ risk_level: 3 }] }}>
          <Form.Item name="plan_type" label="计划类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'trend', label: '趋势跟踪' },
              { value: 'short_term', label: '短线操作' },
              { value: 'event_driven', label: '事件驱动' },
            ]} />
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea />
          </Form.Item>
          <Form.Item label="股票列表">
            <Form.List name="stocks" rules={[{ validator: (_, v) => (v?.length ? Promise.resolve() : Promise.reject('至少添加一只股票')) }]}>
              {(fields, { add, remove }) => (
                <>
                  <Table
                    dataSource={fields}
                    rowKey={(f) => String(f.key)}
                    pagination={false}
                    size="small"
                    scroll={{ x: 1200 }}
                    columns={[
                      { title: '股票代码', key: 'ts_code', width: 100, render: (_, __, i) => <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true }]}><Input placeholder="6位" size="small" /></Form.Item> },
                      { title: '风险', key: 'risk_level', width: 90, render: (_, __, i) => <Form.Item name={[fields[i].name, 'risk_level']} noStyle><Rate count={5} style={{ fontSize: 14 }} /></Form.Item> },
                      { title: '触发策略', key: 'trigger_strategy', width: 120, render: (_, __, i) => <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle><Input placeholder="策略" size="small" /></Form.Item> },
                      { title: '热点/事件', key: 'event_note', width: 120, render: (_, __, i) => <Form.Item name={[fields[i].name, 'event_note']} noStyle><Input placeholder="事件" size="small" /></Form.Item> },
                      { title: '操作建议', key: 'action_suggestion', width: 90, render: (_, __, i) => <Form.Item name={[fields[i].name, 'action_suggestion']} noStyle><Select placeholder="建议" size="small" allowClear options={[{ value: 'buy', label: '买入' }, { value: 'add_position', label: '加仓' }, { value: 'reduce', label: '减仓' }, { value: 'sell', label: '卖出' }, { value: 'watch', label: '观望' }]} style={{ width: 80 }} /></Form.Item> },
                      { title: '买入价', key: 'planned_buy_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '目标价', key: 'target_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'target_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '止损价', key: 'stop_loss_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '仓位', key: 'position_plan', width: 80, render: (_, __, i) => <Form.Item name={[fields[i].name, 'position_plan']} noStyle><Input placeholder="30%" size="small" style={{ width: 60 }} /></Form.Item> },
                      { title: '备注', key: 'note', width: 100, render: (_, __, i) => <Form.Item name={[fields[i].name, 'note']} noStyle><Input placeholder="备注" size="small" /></Form.Item> },
                      { title: '', key: 'action', width: 40, render: (_, __, i) => fields.length > 1 ? <a onClick={() => remove(fields[i].name)} style={{ color: '#ff4d4f' }}>删</a> : null },
                    ]}
                  />
                  <Button type="dashed" onClick={() => add({ risk_level: 3 })} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加股票</Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default PlanList
