import React, { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Tag, Table, Button, Tabs, Space, Statistic, Row, Col, Segmented, Rate,
  Modal, Form, Input, InputNumber, Select, DatePicker, message, Upload,
} from 'antd'
import dayjs from 'dayjs'
import { ArrowLeftOutlined, FileAddOutlined, ThunderboltOutlined, InboxOutlined } from '@ant-design/icons'
import * as echarts from 'echarts'
import { getStockChart, getStockAlerts, getStockPlans } from '../../api/stocks'
import { createPlan, createDetail } from '../../api/plans'
import { extractTradeFromImage } from '../../api/ocr'
import type { StockChartData, StockAlertItem, StockPlanItem } from '../../types'

const typeMap: Record<string, string> = { trend: '趋势跟踪', short_term: '短线操作', event_driven: '事件驱动' }
const statusColors: Record<string, string> = {
  pending: 'default', active: 'blue', completed: 'green', cancelled: 'red', processed: 'purple',
}

const StockDetail: React.FC = () => {
  const { tsCode } = useParams<{ tsCode: string }>()
  const navigate = useNavigate()
  const [chartData, setChartData] = useState<StockChartData | null>(null)
  const [alerts, setAlerts] = useState<StockAlertItem[]>([])
  const [plans, setPlans] = useState<StockPlanItem[]>([])
  const [period, setPeriod] = useState(120)
  const [subIndicator, setSubIndicator] = useState<string>('macd')
  const [planModalOpen, setPlanModalOpen] = useState(false)
  const [detailModalOpen, setDetailModalOpen] = useState(false)
  const [detailPlanId, setDetailPlanId] = useState<string | null>(null)
  const [quickRecordModalOpen, setQuickRecordModalOpen] = useState(false)
  const [ocrLoading, setOcrLoading] = useState(false)
  const [ocrRawText, setOcrRawText] = useState<string>('')
  const [quickRecordForm] = Form.useForm()
  const [planForm] = Form.useForm()
  const [detailForm] = Form.useForm()
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  const openPlanModal = () => {
    planForm.resetFields()
    planForm.setFieldsValue({ ts_code: tsCode, plan_type: 'trend', risk_level: 3 })
    setPlanModalOpen(true)
  }

  const handleCreatePlan = async () => {
    const values = await planForm.validateFields()
    await createPlan(values)
    message.success('交易计划已创建')
    setPlanModalOpen(false)
    if (tsCode) getStockPlans(tsCode).then((res) => setPlans(res.data))
  }

  const openDetailModal = (planId: string) => {
    setDetailPlanId(planId)
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
        const values: Record<string, any> = {}
        if (p.trade_date) values.trade_date = dayjs(p.trade_date, 'YYYYMMDD')
        if (p.trade_time) values.trade_time = p.trade_time
        if (p.direction) values.direction = p.direction
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
    const planRes = await createPlan({ ts_code: tsCode, plan_type: 'short_term', risk_level: 3 })
    await createDetail(planRes.data.id, payload)
    message.success('交易记录已添加')
    setQuickRecordModalOpen(false)
    getStockPlans(tsCode).then((res) => setPlans(res.data))
  }

  const handleAddDetail = async () => {
    if (!detailPlanId) return
    const values = await detailForm.validateFields()
    const payload = { ...values }
    if (values.trade_date) payload.trade_date = dayjs(values.trade_date).format('YYYYMMDD')
    await createDetail(detailPlanId, payload)
    message.success('交易明细已添加')
    setDetailModalOpen(false)
    setDetailPlanId(null)
    if (tsCode) getStockPlans(tsCode).then((res) => setPlans(res.data))
  }

  useEffect(() => {
    if (!tsCode) return
    getStockChart(tsCode, period).then((res) => setChartData(res.data))
    getStockAlerts(tsCode).then((res) => setAlerts(res.data))
    getStockPlans(tsCode).then((res) => setPlans(res.data))
  }, [tsCode, period])

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
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
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

  const basic = chartData?.basic
  const latestQuote = chartData?.quotes?.length ? chartData.quotes[chartData.quotes.length - 1] : null

  const alertColumns = [
    { title: '触发日期', dataIndex: 'trigger_date', key: 'trigger_date' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
    { title: '收盘价', key: 'close', render: (_: any, r: StockAlertItem) => r.snapshot?.close?.toFixed(2) ?? '-' },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
  ]

  const planColumns = [
    { title: '类型', dataIndex: 'plan_type', key: 'plan_type', render: (t: string) => typeMap[t] || t },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
    { title: '风险等级', dataIndex: 'risk_level', key: 'risk_level', render: (v: number) => <Rate disabled value={v} count={5} style={{ fontSize: 12 }} /> },
    {
      title: '实际盈亏', dataIndex: 'actual_pnl', key: 'actual_pnl',
      render: (v: number) => v != null ? <span style={{ color: v >= 0 ? '#3f8600' : '#cf1322' }}>{v.toFixed(2)}</span> : '-',
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', render: (v: string) => v?.slice(0, 10) },
    {
      title: '操作', key: 'action',
      render: (_: any, r: StockPlanItem) => (
        <Space size={0} split={<span style={{ color: '#d9d9d9', margin: '0 4px' }}>|</span>}>
          <a onClick={() => navigate(`/plans/${r.id}`)}>查看</a>
          <a onClick={() => openDetailModal(r.id)}>添加明细</a>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Button icon={<ArrowLeftOutlined />} style={{ marginBottom: 16 }} onClick={() => navigate('/pools')}>
        返回观察池
      </Button>

      {basic && (
        <Card
          title={`${basic.name} ${basic.ts_code}`}
          style={{ marginBottom: 16 }}
          extra={
            <Space>
              <Button size="small" icon={<ThunderboltOutlined />} onClick={openQuickRecordModal}>
                快速记录
              </Button>
              <Button type="primary" size="small" icon={<FileAddOutlined />} onClick={openPlanModal}>
                创建交易计划
              </Button>
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
                  <Statistic
                    title="涨幅"
                    value={latestQuote.pct_chg}
                    precision={2}
                    suffix="%"
                    valueStyle={{ color: latestQuote.pct_chg >= 0 ? '#cf1322' : '#3f8600' }}
                  />
                </Col>
                <Col span={3}>
                  <Statistic title="成交量" value={latestQuote.vol} valueStyle={{ fontSize: 16 }} />
                </Col>
                <Col span={3}>
                  <Statistic title="行情日期" value={latestQuote.date} valueStyle={{ fontSize: 16 }} />
                </Col>
              </>
            )}
          </Row>
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
        <div ref={chartRef} style={{ width: '100%', height: 520 }} />
      </Card>

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
              key: 'plans',
              label: `交易计划 (${plans.length})`,
              children: (
                <Table dataSource={plans} columns={planColumns} rowKey="id" size="small" pagination={false} />
              ),
            },
          ]}
        />
      </Card>

      {/* 创建交易计划 */}
      <Modal
        title={`创建交易计划 - ${basic?.name || tsCode || ''}`}
        open={planModalOpen}
        onOk={handleCreatePlan}
        onCancel={() => setPlanModalOpen(false)}
        width={600}
      >
        <Form form={planForm} layout="vertical" initialValues={{ risk_level: 3, plan_type: 'trend' }}>
          <Form.Item name="ts_code" hidden><Input /></Form.Item>
          <Form.Item name="plan_type" label="计划类型" rules={[{ required: true }]}>
            <Select options={[
              { value: 'trend', label: '趋势跟踪' },
              { value: 'short_term', label: '短线操作' },
              { value: 'event_driven', label: '事件驱动' },
            ]} />
          </Form.Item>
          <Form.Item name="risk_level" label="风险等级">
            <InputNumber min={1} max={5} />
          </Form.Item>
          <Form.Item name="trigger_strategy" label="触发策略">
            <Input.TextArea placeholder="如：MACD 金叉触发" rows={2} />
          </Form.Item>
          <Form.Item name="event_note" label="热点/事件">
            <Input.TextArea placeholder="宏观背景、事件驱动原因" rows={2} />
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
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

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
      <Modal
        title="添加交易明细"
        open={detailModalOpen}
        onOk={handleAddDetail}
        onCancel={() => { setDetailModalOpen(false); setDetailPlanId(null) }}
        width={500}
      >
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
    </div>
  )
}

export default StockDetail
