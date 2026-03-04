import React, { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Descriptions, Tag, Rate, Table, Button, Modal, Form,
  Input, InputNumber, Select, Space, Statistic, Row, Col, Divider, message, Popconfirm, DatePicker,
} from 'antd'
import dayjs from 'dayjs'
import { ArrowLeftOutlined, PlusOutlined, EditOutlined } from '@ant-design/icons'
import { getPlan, updatePlan, submitReview, createDetail, updateDetail, deleteDetail } from '../../api/plans'
import type { TradePlan, TradeDetail } from '../../types'

const typeMap: Record<string, string> = { trend: '趋势跟踪', short_term: '短线操作', event_driven: '事件驱动' }
const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待触发', color: 'default' },
  active: { label: '执行中', color: 'blue' },
  completed: { label: '已完结', color: 'green' },
  cancelled: { label: '已取消', color: 'red' },
}

const PlanDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [plan, setPlan] = useState<TradePlan | null>(null)
  const [, setLoading] = useState(true)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [reviewModalOpen, setReviewModalOpen] = useState(false)
  const [editPlanModalOpen, setEditPlanModalOpen] = useState(false)
  const [editDetailModalOpen, setEditDetailModalOpen] = useState(false)
  const [editingDetail, setEditingDetail] = useState<TradeDetail | null>(null)
  const [detailForm] = Form.useForm()
  const [reviewForm] = Form.useForm()
  const [planForm] = Form.useForm()
  const [editDetailForm] = Form.useForm()

  const fetchPlan = () => {
    if (!id) return
    setLoading(true)
    getPlan(id).then((res) => setPlan(res.data)).finally(() => setLoading(false))
  }

  useEffect(() => { fetchPlan() }, [id])

  const handleAddDetail = async () => {
    const values = await detailForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await createDetail(id!, payload)
    message.success('添加成功')
    setDetailModalOpen(false)
    detailForm.resetFields()
    fetchPlan()
  }

  const handleDeleteDetail = async (detailId: string) => {
    await deleteDetail(detailId)
    message.success('已删除')
    fetchPlan()
  }

  const handleStatusChange = async (status: string) => {
    await updatePlan(id!, { status })
    message.success('状态已更新')
    fetchPlan()
  }

  const handleReview = async () => {
    const values = await reviewForm.validateFields()
    await submitReview(id!, values)
    message.success('复盘已提交')
    setReviewModalOpen(false)
    reviewForm.resetFields()
    fetchPlan()
  }

  const openEditPlanModal = () => {
    if (!plan) return
    planForm.setFieldsValue({
      plan_type: plan.plan_type,
      risk_level: plan.risk_level,
      trigger_strategy: plan.trigger_strategy,
      event_note: plan.event_note,
      planned_buy_price: plan.planned_buy_price,
      target_price: plan.target_price,
      stop_loss_price: plan.stop_loss_price,
      position_plan: plan.position_plan,
      action_suggestion: plan.action_suggestion,
      note: plan.note,
    })
    setEditPlanModalOpen(true)
  }

  const handleEditPlan = async () => {
    const values = await planForm.validateFields()
    await updatePlan(id!, values)
    message.success('计划已更新')
    setEditPlanModalOpen(false)
    fetchPlan()
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
    const values = await editDetailForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await updateDetail(editingDetail.id, payload)
    message.success('明细已更新')
    setEditDetailModalOpen(false)
    setEditingDetail(null)
    fetchPlan()
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
      render: (_: any, r: TradeDetail) => (
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

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} style={{ marginBottom: 16 }} onClick={() => navigate('/plans')}>
        返回列表
      </Button>

      {plan && (
        <>
          <Card
            title={`${plan.stock_name || plan.ts_code} — ${typeMap[plan.plan_type] || plan.plan_type}`}
            extra={
              <Space>
                <Button icon={<EditOutlined />} onClick={openEditPlanModal}>编辑计划</Button>
                <Select value={plan.status} style={{ width: 120 }} onChange={handleStatusChange}>
                  <Select.Option value="pending">待触发</Select.Option>
                  <Select.Option value="active">执行中</Select.Option>
                  <Select.Option value="completed">已完结</Select.Option>
                  <Select.Option value="cancelled">已取消</Select.Option>
                </Select>
                <Button onClick={() => { reviewForm.setFieldsValue({ review_summary: plan.review_summary, lessons_learned: plan.lessons_learned }); setReviewModalOpen(true) }}>
                  复盘
                </Button>
              </Space>
            }
          >
            <Descriptions column={3} bordered size="small">
              <Descriptions.Item label="股票代码">{plan.ts_code}</Descriptions.Item>
              <Descriptions.Item label="风险等级"><Rate disabled value={plan.risk_level} count={5} style={{ fontSize: 14 }} /></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={statusMap[plan.status]?.color}>{statusMap[plan.status]?.label}</Tag></Descriptions.Item>
              <Descriptions.Item label="触发策略" span={3}>{plan.trigger_strategy || '-'}</Descriptions.Item>
              <Descriptions.Item label="热点/事件" span={3}>{plan.event_note || '-'}</Descriptions.Item>
              <Descriptions.Item label="操作建议">{plan.action_suggestion || '-'}</Descriptions.Item>
              <Descriptions.Item label="仓位计划">{plan.position_plan || '-'}</Descriptions.Item>
              <Descriptions.Item label="备注">{plan.note || '-'}</Descriptions.Item>
            </Descriptions>
          </Card>

          <Card title="价格目标" style={{ marginTop: 16 }}>
            <Row gutter={24}>
              <Col span={6}><Statistic title="计划买入价" value={plan.planned_buy_price ?? '-'} precision={2} /></Col>
              <Col span={6}><Statistic title="目标价" value={plan.target_price ?? '-'} precision={2} /></Col>
              <Col span={6}><Statistic title="止损价" value={plan.stop_loss_price ?? '-'} precision={2} /></Col>
              <Col span={6}><Statistic title="盈亏比" value={plan.risk_reward_ratio ?? '-'} precision={2} /></Col>
            </Row>
          </Card>

          <Card
            title="交易明细"
            style={{ marginTop: 16 }}
            extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setDetailModalOpen(true)}>添加明细</Button>}
          >
            <Table dataSource={plan.details || []} columns={detailColumns} rowKey="id" pagination={false} />
            {pnl && (
              <>
                <Divider />
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
              </>
            )}
          </Card>

          {(plan.review_summary || plan.lessons_learned) && (
            <Card title="复盘" style={{ marginTop: 16 }}>
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
        </>
      )}

      {/* 编辑交易计划 */}
      <Modal title="编辑交易计划" open={editPlanModalOpen} onOk={handleEditPlan} onCancel={() => setEditPlanModalOpen(false)} width={600}>
        <Form form={planForm} layout="vertical">
          <Form.Item name="plan_type" label="计划类型">
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
          <Space style={{ width: '100%' }}>
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
              { value: 'reduce', label: '减仓' },
              { value: 'sell', label: '卖出' },
              { value: 'watch', label: '观望' },
            ]} />
          </Form.Item>
          <Form.Item name="note" label="备注">
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

      {/* 复盘 */}
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

export default PlanDetail
