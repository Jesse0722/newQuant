import React, { useEffect, useState } from 'react'
import { Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, Rate, Tag, Space, Popconfirm, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listPlans, createPlan, updatePlan, deletePlan } from '../../api/plans'
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
    await createPlan(values)
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

  const columns = [
    {
      title: '股票',
      key: 'stock',
      render: (_: any, r: TradePlan) => (
        <a onClick={() => navigate(`/plans/${r.id}`)}>{r.stock_name || r.ts_code}</a>
      ),
    },
    { title: '类型', dataIndex: 'plan_type', key: 'plan_type', render: (t: string) => typeMap[t] || t },
    {
      title: '风险等级',
      dataIndex: 'risk_level',
      key: 'risk_level',
      render: (v: number) => <Rate disabled value={v} count={5} style={{ fontSize: 14 }} />,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    { title: '盈亏比', dataIndex: 'risk_reward_ratio', key: 'rr', render: (v: number) => v?.toFixed(2) || '-' },
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

      <Modal title="新建交易计划" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} width={600}>
        <Form form={form} layout="vertical" initialValues={{ risk_level: 3, plan_type: 'trend' }}>
          <Form.Item name="ts_code" label="股票代码" rules={[{ required: true }]}>
            <Input placeholder="输入6位代码，如 000001" />
          </Form.Item>
          <Form.Item name="plan_type" label="计划类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'trend', label: '趋势跟踪' },
              { value: 'short_term', label: '短线操作' },
              { value: 'event_driven', label: '事件驱动' },
            ]} />
          </Form.Item>
          <Form.Item name="risk_level" label="风险等级">
            <Rate count={5} />
          </Form.Item>
          <Form.Item name="trigger_strategy" label="触发策略">
            <Input.TextArea placeholder="如：MACD 金叉触发" />
          </Form.Item>
          <Form.Item name="event_note" label="热点/事件">
            <Input.TextArea placeholder="宏观背景、事件驱动原因" />
          </Form.Item>
          <Space>
            <Form.Item name="planned_buy_price" label="计划买入价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
            <Form.Item name="target_price" label="目标价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
            <Form.Item name="stop_loss_price" label="止损价">
              <InputNumber style={{ width: 150 }} />
            </Form.Item>
          </Space>
          <Form.Item name="position_plan" label="仓位计划">
            <Input placeholder="如：30%" />
          </Form.Item>
          <Form.Item name="action_suggestion" label="操作建议">
            <Select allowClear options={[
              { value: 'buy', label: '买入' },
              { value: 'add_position', label: '加仓' },
              { value: 'watch', label: '观望' },
            ]} />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  )
}

export default PlanList
