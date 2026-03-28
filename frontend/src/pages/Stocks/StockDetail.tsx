import React, { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import {
  Card, Tag, Table, Button, Tabs, Space, Statistic, Row, Col, Segmented,
  Modal, Form, Input, InputNumber, Select, DatePicker, message, Upload, Popconfirm,
} from 'antd'
import dayjs from 'dayjs'
import { ArrowLeftOutlined, ThunderboltOutlined, PlusOutlined, InboxOutlined, EditOutlined } from '@ant-design/icons'
import * as echarts from 'echarts'
import { getStockChart, getStockAlerts, getStockDetails, createStockDetail } from '../../api/stocks'
import { updateDetail, deleteDetail } from '../../api/plans'
import { extractTradeFromImage } from '../../api/ocr'
import type { StockChartData, StockAlertItem, TradeDetail } from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'

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

const StockDetail: React.FC = () => {
  const { tsCode } = useParams<{ tsCode: string }>()
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
  const [quickRecordForm] = Form.useForm()
  const [detailForm] = Form.useForm()
  const [editDetailForm] = Form.useForm()
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const poolNavStocks: PoolNavStock[] = Array.isArray((location.state as any)?.stockList)
    ? (location.state as any).stockList
    : []
  const poolName: string | undefined = (location.state as any)?.poolName
  const currentNavIndex = poolNavStocks.findIndex((s) => s.ts_code === tsCode)

  const jumpToStock = (idx: number) => {
    if (idx < 0 || idx >= poolNavStocks.length) return
    const target = poolNavStocks[idx]
    navigate(`/stocks/${target.ts_code}`, { state: location.state })
  }

  const fetchDetails = () => {
    if (tsCode) getStockDetails(tsCode).then((res) => setDetails(res.data))
  }

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
    getStockAlerts(tsCode).then((res) => setAlerts(res.data))
    fetchDetails()
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
  }, [poolNavStocks, currentNavIndex])

  const basic = chartData?.basic
  const latestQuote = chartData?.quotes?.length ? chartData.quotes[chartData.quotes.length - 1] : null
  const syncMeta = chartData?.sync_meta

  const alertColumns = [
    { title: '触发日期', dataIndex: 'trigger_date', key: 'trigger_date' },
    { title: '状态', dataIndex: 'status', key: 'status', render: (s: string) => <Tag color={statusColors[s]}>{s}</Tag> },
    { title: '收盘价', key: 'close', render: (_: any, r: StockAlertItem) => r.snapshot?.close?.toFixed(2) ?? '-' },
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
      render: (_: any, r: TradeDetail) => (
        <Space>
          <a onClick={() => openEditDetailModal(r)}><EditOutlined /> 编辑</a>
          <Popconfirm title="确定删除？" onConfirm={() => handleDeleteDetail(r.id)}>
            <a style={{ color: 'red' }}>删除</a>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      {poolNavStocks.length > 0 && (
        <Card
          title={poolName ? `${poolName}（${poolNavStocks.length}）` : `池内股票（${poolNavStocks.length}）`}
          size="small"
          style={{ width: 300, flexShrink: 0, maxHeight: 'calc(100vh - 130px)', overflow: 'hidden' }}
          extra={<span style={{ fontSize: 12, color: '#999' }}>↑ ↓ 快速切换</span>}
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
                    borderBottom: '1px solid #f0f0f0',
                    cursor: 'pointer',
                    background: active ? '#f0f5ff' : '#fff',
                    borderLeft: active ? '3px solid #1677ff' : '3px solid transparent',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                    <span style={{ fontWeight: 600 }}>{s.stock_name || s.ts_code}</span>
                    <span style={{ color: '#8c8c8c', fontSize: 12 }}>{s.ts_code}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#666' }}>
                    {s.industry || '-'}
                    {s.latest_price != null && (
                      <span style={{ marginLeft: 8 }}>
                        {s.latest_price.toFixed(2)}
                      </span>
                    )}
                    {s.pct_chg != null && (
                      <span style={{ marginLeft: 8, color: s.pct_chg >= 0 ? '#cf1322' : '#3f8600' }}>
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
      <Button icon={<ArrowLeftOutlined />} style={{ marginBottom: 16 }} onClick={() => navigate('/pools')}>
        返回观察池
      </Button>

      {syncMeta && (
        <div style={{ marginBottom: 12 }}>
          <Tag color={syncMeta.status === 'sync_failed' ? 'red' : syncMeta.status === 'updated' ? 'green' : 'blue'}>
            {syncMeta.status === 'sync_failed' ? '数据补齐失败' : syncMeta.status === 'updated' ? '数据已自动更新' : '数据已是最新'}
          </Tag>
          <span style={{ color: '#666', fontSize: 12 }}>
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
              <Button size="small" icon={<ThunderboltOutlined />} onClick={openQuickRecordModal}>
                快速记录
              </Button>
              <Button type="primary" size="small" icon={<PlusOutlined />} onClick={openDetailModal}>
                添加明细
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
              key: 'details',
              label: `交易明细 (${details.length})`,
              children: (
                <Table dataSource={details} columns={detailColumns} rowKey="id" size="small" pagination={false} />
              ),
            },
          ]}
        />
      </Card>

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
