import React, { useEffect, useState } from 'react'
import { Card, Table, Tabs, Button, Modal, Form, Input, InputNumber, Select, AutoComplete, Tag, Space, Popconfirm, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { useSearchParams } from 'react-router-dom'
import { listPlans, createPlan, deletePlan } from '../../api/plans'
import PlanDetailRow from './PlanDetailRow'
import { getAllStocks } from '../../api/pools'
import type { TradePlan } from '../../types'

const TRIGGER_OPTIONS = ['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合']

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
  const [allStocks, setAllStocks] = useState<Array<{ ts_code: string; stock_name?: string }>>([])
  const [form] = Form.useForm()
  const [searchParams] = useSearchParams()
  const expandId = searchParams.get('expand')
  const [expandedRowKeys, setExpandedRowKeys] = useState<string[]>([])

  const toggleExpand = (id: string) => {
    setExpandedRowKeys((prev) =>
      prev.includes(id) ? prev.filter((k) => k !== id) : [...prev, id]
    )
  }

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

  const planIds = plans.map((p) => p.id).join(',')
  useEffect(() => {
    if (plans.length === 0) return
    const targetId = expandId && plans.some((p) => p.id === expandId) ? expandId : plans[0].id
    setExpandedRowKeys([targetId])
  }, [planIds, expandId])

  useEffect(() => {
    if (modalOpen) {
      getAllStocks().then((res) => setAllStocks(res.data || []))
    }
  }, [modalOpen])

  const handleCreate = async () => {
    const values = await form.validateFields()
    const stocks = values.stocks.map((s: any) => ({
      ts_code: s.ts_code,
      risk_level: s.risk_level ?? 2,
      trigger_strategy: s.trigger_strategy,
      planned_buy_price: s.planned_buy_price,
      target_price: s.target_price,
      stop_loss_price: s.stop_loss_price,
      position_plan: s.position_plan,
      note: s.note,
    }))
    await createPlan({
      title: values.title,
      stocks,
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

  const stockOptions = allStocks.map((s) => ({
    value: s.ts_code,
    label: `${s.stock_name || s.ts_code} (${s.ts_code})`,
  }))

  const columns = [
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (t: string, r: TradePlan) => (
        <a onClick={() => toggleExpand(r.id)}>{t || '-'}</a>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
    {
      title: '操作',
      key: 'action',
      render: (_: any, r: TradePlan) => (
        <Space>
          <a onClick={() => toggleExpand(r.id)}>详情</a>
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
        expandable={{
          expandedRowKeys,
          onExpandedRowsChange: (keys) => setExpandedRowKeys(keys as string[]),
          expandedRowRender: (r) => <PlanDetailRow planId={r.id} onRefresh={fetchPlans} />,
        }}
      />

      <Modal title="新建交易计划" open={modalOpen} onOk={handleCreate} onCancel={() => setModalOpen(false)} width={900}>
        <Form form={form} layout="vertical" initialValues={{ stocks: [{ risk_level: 2 }] }}>
          <Form.Item name="title" label="标题" rules={[{ required: true, message: '请输入标题' }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
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
                    scroll={{ x: 1100 }}
                    columns={[
                      {
                        title: '股票',
                        key: 'ts_code',
                        width: 180,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true, message: '请选择' }]}>
                            <Select
                              showSearch
                              placeholder="选择或搜索"
                              size="small"
                              style={{ width: 160 }}
                              options={stockOptions}
                              filterOption={(input, opt) =>
                                (opt?.label ?? '').toLowerCase().includes(input.toLowerCase())
                              }
                            />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '触发策略',
                        key: 'trigger_strategy',
                        width: 130,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle>
                            <AutoComplete options={TRIGGER_OPTIONS.map((o) => ({ value: o }))} placeholder="输入或选择" size="small" style={{ width: 120 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '买入价',
                        key: 'planned_buy_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '目标价',
                        key: 'target_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'target_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '止损价',
                        key: 'stop_loss_price',
                        width: 85,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle>
                            <InputNumber size="small" style={{ width: 70 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '仓位(%)',
                        key: 'position_plan',
                        width: 90,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'position_plan']} noStyle>
                            <InputNumber size="small" min={0} max={100} addonAfter="%" style={{ width: 80 }} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '风险',
                        key: 'risk_level',
                        width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'risk_level']} noStyle>
                            <Select size="small" style={{ width: 90 }} options={[
                              { value: 1, label: '低风险' },
                              { value: 2, label: '中风险' },
                              { value: 3, label: '高风险' },
                            ]} />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '备注',
                        key: 'note',
                        width: 100,
                        render: (_, __, i) => (
                          <Form.Item name={[fields[i].name, 'note']} noStyle>
                            <Input placeholder="备注" size="small" />
                          </Form.Item>
                        ),
                      },
                      {
                        title: '',
                        key: 'action',
                        width: 40,
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
    </Card>
  )
}

export default PlanList
