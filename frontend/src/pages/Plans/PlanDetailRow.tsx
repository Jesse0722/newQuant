import React, { useCallback, useEffect, useState } from 'react'
import {
  Card, Descriptions, Tag, Table, Button, Modal, Form,
  Input, InputNumber, Select, AutoComplete, Space, Statistic, Row, Col, message, Popconfirm, DatePicker,
} from 'antd'
import dayjs from 'dayjs'
import { PlusOutlined, EditOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getPlan, updatePlan, submitReview, updateDetail, deleteDetail, type PlanStockInput, type DetailUpdateInput } from '../../api/plans'
import { createStockDetail } from '../../api/stocks'
import { getAllStocks } from '../../api/pools'
import type { TradePlan, TradeDetail, TradePlanStock } from '../../types'

const TRIGGER_OPTIONS = ['短线', '龙头战法', 'MACD金叉', '突破', '回调', '趋势跟踪', '事件驱动', '均线支撑', '量价配合']

const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待触发', color: 'default' },
  active: { label: '执行中', color: 'blue' },
  completed: { label: '已完结', color: 'green' },
  cancelled: { label: '已取消', color: 'red' },
}

const riskMap: Record<number, { label: string; color: string }> = {
  1: { label: '低风险', color: 'green' },
  2: { label: '中风险', color: 'orange' },
  3: { label: '高风险', color: 'red' },
}

interface PlanDetailRowProps {
  planId: string
  onRefresh: () => void
}

interface EditPlanFormValues {
  title: string
  note?: string
  stocks: PlanStockInput[]
}

interface DetailFormValues extends DetailUpdateInput {
  trade_date?: dayjs.Dayjs
}

interface ApiErrorLike {
  response?: { data?: { message?: string } }
  message?: string
}

const PlanDetailRow: React.FC<PlanDetailRowProps> = ({ planId, onRefresh }) => {
  const navigate = useNavigate()
  const [plan, setPlan] = useState<TradePlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [detailStockTsCode, setDetailStockTsCode] = useState<string | null>(null)
  const [reviewModalOpen, setReviewModalOpen] = useState(false)
  const [editPlanModalOpen, setEditPlanModalOpen] = useState(false)
  const [editDetailModalOpen, setEditDetailModalOpen] = useState(false)
  const [editingDetail, setEditingDetail] = useState<TradeDetail | null>(null)
  const [allStocks, setAllStocks] = useState<Array<{ ts_code: string; stock_name?: string }>>([])
  const [detailForm] = Form.useForm()
  const [reviewForm] = Form.useForm()
  const [planForm] = Form.useForm()
  const [editDetailForm] = Form.useForm()

  const fetchPlan = useCallback(() => {
    getPlan(planId).then((res) => setPlan(res.data)).finally(() => setLoading(false))
  }, [planId])

  useEffect(() => {
    fetchPlan()
  }, [fetchPlan])

  const openAddDetailModal = () => {
    if (!plan?.stocks?.length) {
      message.warning('计划暂无股票')
      return
    }
    setDetailStockTsCode(plan.stocks[0].ts_code)
    detailForm.resetFields()
    setDetailModalOpen(true)
  }

  const handleAddDetail = async () => {
    if (!detailStockTsCode) return
    const values = await detailForm.validateFields() as DetailFormValues
    const payload: DetailUpdateInput = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await createStockDetail(detailStockTsCode, payload)
    message.success('添加成功')
    setDetailModalOpen(false)
    fetchPlan()
    onRefresh()
  }

  const handleDeleteDetail = async (detailId: string) => {
    await deleteDetail(detailId)
    message.success('已删除')
    fetchPlan()
    onRefresh()
  }

  const handleStatusChange = async (status: string) => {
    await updatePlan(planId, { status })
    message.success('状态已更新')
    fetchPlan()
    onRefresh()
  }

  const handleReview = async () => {
    const values = await reviewForm.validateFields()
    await submitReview(planId, values)
    message.success('复盘已提交')
    setReviewModalOpen(false)
    reviewForm.resetFields()
    fetchPlan()
    onRefresh()
  }

  const openEditPlanModal = () => {
    if (!plan) return
    getAllStocks().then((res) => setAllStocks(res.data || []))
    planForm.setFieldsValue({
      title: plan.title,
      note: plan.note,
      stocks: plan.stocks?.map((s) => ({
        ts_code: s.ts_code,
        risk_level: s.risk_level ?? 2,
        trigger_strategy: s.trigger_strategy,
        planned_buy_price: s.planned_buy_price,
        target_price: s.target_price,
        stop_loss_price: s.stop_loss_price,
        position_plan: s.position_plan != null ? (typeof s.position_plan === 'string' ? parseFloat(s.position_plan) || undefined : s.position_plan) : undefined,
        note: s.note,
      })) || [],
    })
    setEditPlanModalOpen(true)
  }

  const handleEditPlan = async () => {
    try {
      const values = await planForm.validateFields() as EditPlanFormValues
      const stocks = values.stocks.map((stock) => ({
        ts_code: stock.ts_code,
        risk_level: stock.risk_level ?? 2,
        trigger_strategy: stock.trigger_strategy,
        planned_buy_price: stock.planned_buy_price,
        target_price: stock.target_price,
        stop_loss_price: stock.stop_loss_price,
        position_plan: stock.position_plan,
        note: stock.note,
      }))
      await updatePlan(planId, { title: values.title, note: values.note, stocks })
      message.success('计划已更新')
      setEditPlanModalOpen(false)
      fetchPlan()
      onRefresh()
    } catch (error: unknown) {
      const err = error as ApiErrorLike
      const msg = err.response?.data?.message || err.message || '更新失败'
      message.error(msg)
    }
  }

  const openEditDetailModal = (detail: TradeDetail) => {
    setEditingDetail(detail)
    editDetailForm.setFieldsValue({
      trade_date: detail.trade_date ? dayjs(detail.trade_date, 'YYYYMMDD') : undefined,
      trade_time: detail.trade_time,
      direction: detail.direction,
      price: detail.price,
      quantity: detail.quantity,
      commission: detail.commission,
      exec_note: detail.exec_note,
    })
    setEditDetailModalOpen(true)
  }

  const handleEditDetail = async () => {
    if (!editingDetail) return
    const values = await editDetailForm.validateFields() as DetailFormValues
    const payload: DetailUpdateInput = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await updateDetail(editingDetail.id, payload)
    message.success('明细已更新')
    setEditDetailModalOpen(false)
    setEditingDetail(null)
    fetchPlan()
    onRefresh()
  }

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
    { title: '佣金', dataIndex: 'commission', key: 'commission', render: (v: number) => v.toFixed(2) },
    { title: '印花税', dataIndex: 'stamp_tax', key: 'stamp_tax', render: (v: number) => v.toFixed(2) },
    { title: '备注', dataIndex: 'exec_note', key: 'exec_note', render: (v: string) => v || '-' },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, r: TradeDetail) => (
        <Space>
          <a onClick={() => openEditDetailModal(r)}>编辑</a>
          <Popconfirm title="确定删除？" onConfirm={() => handleDeleteDetail(r.id)}>
            <a style={{ color: 'red' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const pnl = plan?.pnl_summary
  const stockOptions = allStocks.map((s) => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` }))

  if (loading || !plan) return <div style={{ padding: 24, textAlign: 'center', color: '#999' }}>加载中...</div>

  return (
    <div style={{ padding: '0 24px 16px', background: '#fafafa' }}>
      <Card
        title={plan.title || '交易计划'}
        size="small"
        extra={
          <Space>
            <Button size="small" icon={<EditOutlined />} onClick={openEditPlanModal}>编辑计划</Button>
            <Select value={plan.status} size="small" style={{ width: 120 }} onChange={handleStatusChange}>
              <Select.Option value="pending">待触发</Select.Option>
              <Select.Option value="active">执行中</Select.Option>
              <Select.Option value="completed">已完结</Select.Option>
              <Select.Option value="cancelled">已取消</Select.Option>
            </Select>
            <Button size="small" onClick={() => { reviewForm.setFieldsValue({ review_summary: plan.review_summary, lessons_learned: plan.lessons_learned }); setReviewModalOpen(true) }}>
              复盘
            </Button>
          </Space>
        }
      >
        <Descriptions column={3} bordered size="small">
          <Descriptions.Item label="股票">
            {plan.stocks?.map((s) => s.stock_name || s.ts_code).join('、') || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={statusMap[plan.status]?.color}>{statusMap[plan.status]?.label}</Tag></Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{plan.note || '-'}</Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="股票列表" size="small" style={{ marginTop: 12 }}>
        <Table
          dataSource={plan.stocks || []}
          rowKey="id"
          pagination={false}
          size="small"
          expandable={{
            expandedRowRender: (ps: TradePlanStock) => (
              <Table
                dataSource={ps.details || []}
                columns={detailColumns}
                rowKey="id"
                pagination={false}
                size="small"
              />
            ),
            rowExpandable: () => true,
          }}
          columns={[
            { title: '股票', key: 'stock', render: (_: unknown, ps: TradePlanStock) => <a onClick={() => navigate(`/stocks/${ps.ts_code}`)}>{ps.stock_name || ps.ts_code} ({ps.ts_code})</a> },
            { title: '风险', dataIndex: 'risk_level', key: 'risk_level', width: 90, render: (v: number) => { const m = riskMap[v ?? 2] || riskMap[2]; return <Tag color={m.color}>{m.label}</Tag> } },
            { title: '触发策略', dataIndex: 'trigger_strategy', key: 'trigger_strategy', ellipsis: true, render: (v: string) => v || '-' },
            { title: '计划买入价', dataIndex: 'planned_buy_price', key: 'planned_buy_price', width: 100, render: (v: number) => v != null ? v.toFixed(2) : '-' },
            { title: '目标价', dataIndex: 'target_price', key: 'target_price', width: 90, render: (v: number) => v != null ? v.toFixed(2) : '-' },
            { title: '止损价', dataIndex: 'stop_loss_price', key: 'stop_loss_price', width: 90, render: (v: number) => v != null ? v.toFixed(2) : '-' },
            { title: '盈亏比', dataIndex: 'risk_reward_ratio', key: 'rr', width: 80, render: (v: number) => v != null ? v.toFixed(2) : '-' },
            { title: '仓位', dataIndex: 'position_plan', key: 'position_plan', width: 80, render: (v: string | number) => v != null ? `${v}%` : '-' },
            { title: '备注', dataIndex: 'note', key: 'note', ellipsis: true, render: (v: string) => v || '-' },
          ]}
        />
      </Card>

      <Card title="交易明细汇总" size="small" style={{ marginTop: 12 }} extra={<Button type="primary" size="small" icon={<PlusOutlined />} onClick={openAddDetailModal}>添加明细</Button>}>
        {pnl && (
          <Row gutter={24}>
            <Col span={4}><Statistic title="买入总额" value={pnl.total_buy_amount} precision={2} /></Col>
            <Col span={4}><Statistic title="卖出总额" value={pnl.total_sell_amount} precision={2} /></Col>
            <Col span={4}><Statistic title="佣金" value={pnl.total_commission} precision={2} /></Col>
            <Col span={4}><Statistic title="印花税" value={pnl.total_stamp_tax} precision={2} /></Col>
            <Col span={4}>
              <Statistic
                title="净盈亏"
                value={pnl.net_pnl}
                precision={2}
                valueStyle={{ color: pnl.net_pnl >= 0 ? '#3f8600' : '#cf1322' }}
              />
            </Col>
            <Col span={4}><Statistic title="持仓数量" value={pnl.holding_quantity} suffix="股" /></Col>
          </Row>
        )}
      </Card>

      {(plan.review_summary || plan.lessons_learned) && (
        <Card title="复盘" size="small" style={{ marginTop: 12 }}>
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="复盘总结">{plan.review_summary || '-'}</Descriptions.Item>
            <Descriptions.Item label="经验教训">{plan.lessons_learned || '-'}</Descriptions.Item>
            <Descriptions.Item label="实际盈亏">
              <span style={{ color: (plan.actual_pnl ?? 0) >= 0 ? '#3f8600' : '#cf1322', fontWeight: 'bold' }}>
                {plan.actual_pnl?.toFixed(2) ?? '-'}
              </span>
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      <Modal title="编辑交易计划" open={editPlanModalOpen} onOk={handleEditPlan} onCancel={() => setEditPlanModalOpen(false)} width={900}>
        <Form form={planForm} layout="vertical">
          <Form.Item name="title" label="标题" rules={[{ required: true }]}>
            <Input placeholder="计划标题" />
          </Form.Item>
          <Form.Item name="note" label="计划备注">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item label="股票列表">
            <Form.List name="stocks">
              {(fields, { add, remove }) => (
                <>
                  <Table
                    dataSource={fields}
                    rowKey={(f) => String(f.key)}
                    pagination={false}
                    size="small"
                    scroll={{ x: 1100 }}
                    columns={[
                      { title: '股票', key: 'ts_code', width: 180, render: (_, __, i) => <Form.Item name={[fields[i].name, 'ts_code']} noStyle rules={[{ required: true }]}><Select showSearch placeholder="选择" size="small" style={{ width: 160 }} options={stockOptions} filterOption={(input, opt) => (opt?.label ?? '').toString().toLowerCase().includes(input.toLowerCase())} /></Form.Item> },
                      { title: '触发策略', key: 'trigger_strategy', width: 130, render: (_, __, i) => <Form.Item name={[fields[i].name, 'trigger_strategy']} noStyle><AutoComplete options={TRIGGER_OPTIONS.map((o) => ({ value: o }))} placeholder="输入或选择" size="small" style={{ width: 120 }} /></Form.Item> },
                      { title: '买入价', key: 'planned_buy_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'planned_buy_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '目标价', key: 'target_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'target_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '止损价', key: 'stop_loss_price', width: 85, render: (_, __, i) => <Form.Item name={[fields[i].name, 'stop_loss_price']} noStyle><InputNumber size="small" style={{ width: 70 }} /></Form.Item> },
                      { title: '仓位(%)', key: 'position_plan', width: 90, render: (_, __, i) => <Form.Item name={[fields[i].name, 'position_plan']} noStyle><InputNumber size="small" min={0} max={100} addonAfter="%" style={{ width: 80 }} /></Form.Item> },
                      { title: '风险', key: 'risk_level', width: 100, render: (_, __, i) => <Form.Item name={[fields[i].name, 'risk_level']} noStyle><Select size="small" style={{ width: 90 }} options={[{ value: 1, label: '低风险' }, { value: 2, label: '中风险' }, { value: 3, label: '高风险' }]} /></Form.Item> },
                      { title: '备注', key: 'note', width: 100, render: (_, __, i) => <Form.Item name={[fields[i].name, 'note']} noStyle><Input placeholder="备注" size="small" /></Form.Item> },
                      { title: '', key: 'action', width: 40, render: (_, __, i) => fields.length > 1 ? <a onClick={() => remove(fields[i].name)} style={{ color: '#ff4d4f' }}>删</a> : null },
                    ]}
                  />
                  <Button type="dashed" onClick={() => add()} block icon={<PlusOutlined />} style={{ marginTop: 8 }}>添加股票</Button>
                </>
              )}
            </Form.List>
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="添加交易明细" open={detailModalOpen} onOk={handleAddDetail} onCancel={() => setDetailModalOpen(false)} width={500}>
        <Form form={detailForm} layout="vertical">
          <Form.Item label="股票">
            <Select
              value={detailStockTsCode}
              onChange={setDetailStockTsCode}
              options={plan?.stocks?.map((s) => ({ value: s.ts_code, label: `${s.stock_name || s.ts_code} (${s.ts_code})` })) || []}
            />
          </Form.Item>
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

      <Modal title="复盘" open={reviewModalOpen} onOk={handleReview} onCancel={() => setReviewModalOpen(false)}>
        <Form form={reviewForm} layout="vertical">
          <Form.Item name="review_summary" label="复盘总结" rules={[{ required: true }]}>
            <Input.TextArea rows={4} placeholder="整体执行评价，结果是否符合预期" />
          </Form.Item>
          <Form.Item name="lessons_learned" label="经验教训">
            <Input.TextArea rows={4} placeholder="下次该改进什么" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default PlanDetailRow
