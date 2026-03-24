import React, { useEffect, useRef, useCallback, useState } from 'react'
import { Card, Tag, Descriptions, Segmented, Space, Row, Col, Statistic, Empty, Button } from 'antd'
import { CheckCircleFilled, CloseCircleFilled, ArrowRightOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as echarts from 'echarts'
import { getStockChartWithMarks } from '../../api/strategy'
import type { BuySignal, StockChartDataWithMarks, SignalMark } from '../../types'

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  triggered: { text: '已触发买点', color: '#f5222d' },
  approaching: { text: '接近买点', color: '#fa8c16' },
  tracking: { text: '跟踪中', color: '#1890ff' },
  invalidated: { text: '已失效', color: '#bfbfbf' },
}

interface Props {
  signal: BuySignal | null
}

const SignalDetail: React.FC<Props> = ({ signal }) => {
  const navigate = useNavigate()
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)
  const [chartData, setChartData] = useState<StockChartDataWithMarks | null>(null)
  const [period, setPeriod] = useState(120)
  const [subIndicator, setSubIndicator] = useState<string>('macd')

  useEffect(() => {
    if (!signal) return
    getStockChartWithMarks(signal.ts_code, period, signal.life_line_date || undefined).then((res) =>
      setChartData(res.data)
    )
  }, [signal?.ts_code, period])

  const renderChart = useCallback(() => {
    if (!chartRef.current || !chartData || chartData.quotes.length === 0) return

    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current)
    }
    const chart = chartInstance.current
    const { quotes, indicators, signal_marks } = chartData
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

    // K线标注
    const markPoints: any[] = []
    const markLines: any[] = []

    if (signal_marks) {
      for (const mark of signal_marks) {
        const dateIdx = dates.indexOf(mark.date)
        if (mark.type === 'life_line' && mark.value != null) {
          markLines.push({
            name: mark.label,
            yAxis: mark.value,
            lineStyle: { color: '#722ed1', type: 'dashed', width: 1.5 },
            label: { formatter: `{b|${mark.label}} {c|${mark.value.toFixed(2)}}`, rich: { b: { color: '#722ed1', fontSize: 11 }, c: { color: '#722ed1', fontSize: 11 } } },
          })
        }
        if (mark.type === 'phase2_high' && dateIdx >= 0) {
          markPoints.push({
            name: mark.label,
            coord: [mark.date, mark.value],
            symbol: 'triangle',
            symbolSize: 10,
            symbolRotate: 180,
            itemStyle: { color: '#faad14' },
            label: { show: true, formatter: mark.label, position: 'top', fontSize: 10, color: '#faad14' },
          })
        }
        if (mark.type === 'buy_signal' && dateIdx >= 0) {
          markPoints.push({
            name: mark.label,
            coord: [mark.date, mark.value],
            symbol: 'triangle',
            symbolSize: 12,
            itemStyle: { color: '#f5222d' },
            label: { show: true, formatter: mark.label, position: 'bottom', fontSize: 10, color: '#f5222d', fontWeight: 'bold' },
          })
        }
      }
    }

    const candleSeries: any = {
      name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
      itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
    }
    if (markPoints.length > 0) candleSeries.markPoint = { data: markPoints }
    if (markLines.length > 0) candleSeries.markLine = { data: markLines, silent: true, symbol: 'none' }

    const series: any[] = [
      candleSeries,
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
        { type: 'inside', xAxisIndex: [0, 1, 2], start: 50, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 5, height: 20, start: 50, end: 100 },
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

  // signal 变化时重建 chart 实例
  useEffect(() => {
    if (chartInstance.current) {
      chartInstance.current.dispose()
      chartInstance.current = null
    }
  }, [signal?.ts_code])

  if (!signal) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#bfbfbf' }}>
        <Empty description="从左侧列表选择一只股票查看" />
      </div>
    )
  }

  const statusCfg = STATUS_LABELS[signal.signal_status] || STATUS_LABELS.tracking

  return (
    <div style={{ overflowY: 'auto', height: '100%', padding: '0 0 16px 0' }}>
      {/* 顶部信息栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: 700, marginRight: 8 }}>{signal.name}</span>
          <span style={{ fontSize: 14, color: '#8c8c8c', marginRight: 12 }}>{signal.ts_code}</span>
          {signal.industry && <Tag>{signal.industry}</Tag>}
          <Tag color={statusCfg.color}>{statusCfg.text}</Tag>
        </div>
        <Button size="small" onClick={() => navigate(`/stocks/${signal.ts_code}`)}>
          完整详情 <ArrowRightOutlined />
        </Button>
      </div>

      {/* 关键指标行 */}
      <Row gutter={16} style={{ marginBottom: 12 }}>
        <Col span={4}>
          <Statistic title="最新价" value={signal.latest_close ?? '-'} precision={2} valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={4}>
          <Statistic
            title="今涨幅"
            value={signal.latest_pct_chg ?? 0}
            precision={2}
            suffix="%"
            valueStyle={{ fontSize: 16, color: (signal.latest_pct_chg ?? 0) >= 0 ? '#cf1322' : '#3f8600' }}
          />
        </Col>
        <Col span={4}>
          <Statistic title="信号评分" value={signal.signal_score} suffix="/ 100" valueStyle={{ fontSize: 16, color: signal.signal_score >= 70 ? '#f5222d' : '#595959' }} />
        </Col>
        <Col span={4}>
          <Statistic title="回调幅度" value={signal.pullback_pct ?? '-'} precision={1} suffix="%" valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={4}>
          <Statistic title="距生命线" value={signal.days_since_life_line ?? '-'} suffix="天" valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={4}>
          <Statistic title="RSI" value={signal.rsi ?? '-'} precision={1} valueStyle={{ fontSize: 16 }} />
        </Col>
      </Row>

      {/* K 线图 */}
      <Card
        size="small"
        style={{ marginBottom: 12 }}
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
        <div ref={chartRef} style={{ width: '100%', height: 440 }} />
      </Card>

      {/* 信号条件明细 */}
      <Card size="small" title="买点条件检查">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {signal.met_conditions.map((c) => (
            <Tag key={c} color="success" icon={<CheckCircleFilled />}>{c}</Tag>
          ))}
          {signal.unmet_conditions.map((c) => (
            <Tag key={c} color="default" icon={<CloseCircleFilled />}>{c}</Tag>
          ))}
        </div>

        {signal.life_line_date && (
          <Descriptions size="small" column={3} style={{ marginTop: 12 }} bordered>
            <Descriptions.Item label="生命线日期">
              {signal.life_line_date.slice(0, 4)}-{signal.life_line_date.slice(4, 6)}-{signal.life_line_date.slice(6)}
            </Descriptions.Item>
            <Descriptions.Item label="生命线价格">{signal.life_line_price?.toFixed(2) ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="阶段高点">{signal.phase2_high?.toFixed(2) ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="量比">{signal.volume_ratio?.toFixed(2) ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="MACD柱">{signal.macd_hist?.toFixed(4) ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="RSI">{signal.rsi?.toFixed(1) ?? '-'}</Descriptions.Item>
          </Descriptions>
        )}
      </Card>
    </div>
  )
}

export default SignalDetail
