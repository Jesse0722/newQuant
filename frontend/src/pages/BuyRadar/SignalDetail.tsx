import React, { useEffect, useRef, useCallback, useState } from 'react'
import { Card, Tag, Descriptions, Segmented, Space, Row, Col, Statistic, Empty, Button, Tooltip } from 'antd'
import { CheckCircleFilled, CloseCircleFilled, ArrowRightOutlined, StarFilled, StarOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import * as echarts from 'echarts'
import { getStockChartWithMarks } from '../../api/strategy'
import type { BuySignal, StockChartDataWithMarks } from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'

const STATUS_LABELS: Record<string, { text: string; color: string }> = {
  triggered: { text: '已触发买点', color: '#f5222d' },
  confirmed_triggered: { text: '收盘确证', color: '#cf1322' },
  provisional_triggered: { text: '盘中候选', color: '#722ed1' },
  approaching: { text: '接近买点', color: '#fa8c16' },
  tracking: { text: '跟踪中', color: '#1890ff' },
  invalidated: { text: '已失效', color: '#bfbfbf' },
}

type ChartMark = Record<string, unknown>
type ChartSeries = Record<string, unknown>

interface Props {
  signal: BuySignal | null
  coreWatchCodes: Set<string>
  onToggleCoreWatch: (signal: BuySignal, starred: boolean) => void
  coreWatchBusyTsCode?: string | null
}

const SignalDetail: React.FC<Props> = ({
  signal,
  coreWatchCodes,
  onToggleCoreWatch,
  coreWatchBusyTsCode,
}) => {
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
  }, [signal, period])

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
    const markPoints: ChartMark[] = []
    const markLines: ChartMark[] = []

    if (signal_marks) {
      for (const mark of signal_marks) {
        const dateIdx = dates.indexOf(mark.date)
        const value = mark.value
        if (mark.type === 'life_line' && typeof value === 'number') {
          markLines.push({
            name: mark.label,
            yAxis: value,
            lineStyle: { color: '#722ed1', type: 'dashed', width: 1.5 },
            label: { formatter: `{b|${mark.label}} {c|${value.toFixed(2)}}`, rich: { b: { color: '#722ed1', fontSize: 11 }, c: { color: '#722ed1', fontSize: 11 } } },
          })
        }
        if (mark.type === 'phase2_high' && dateIdx >= 0 && typeof value === 'number' && Number.isFinite(value) && value > 0) {
          markPoints.push({
            name: mark.label,
            coord: [mark.date, value],
            symbol: 'triangle',
            symbolSize: 10,
            symbolRotate: 180,
            itemStyle: { color: '#faad14' },
            label: { show: true, formatter: mark.label, position: 'top', fontSize: 10, color: '#faad14' },
          })
        }
        if (mark.type === 'buy_signal' && dateIdx >= 0 && typeof value === 'number' && Number.isFinite(value) && value > 0) {
          markPoints.push({
            name: mark.label,
            coord: [mark.date, value],
            symbol: 'triangle',
            symbolSize: 12,
            itemStyle: { color: '#f5222d' },
            label: { show: true, formatter: mark.label, position: 'bottom', fontSize: 10, color: '#f5222d', fontWeight: 'bold' },
          })
        }
      }
    }

    const candleSeries: ChartSeries = {
      name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
      itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
    }
    if (markPoints.length > 0) candleSeries.markPoint = { data: markPoints }
    if (markLines.length > 0) candleSeries.markLine = { data: markLines, silent: true, symbol: 'none' }

    const series: ChartSeries[] = [
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
  const starred = coreWatchCodes.has(signal.ts_code)
  const starBusy = coreWatchBusyTsCode === signal.ts_code

  return (
    <div style={{ overflowY: 'auto', height: '100%', padding: '0 0 16px 0' }}>
      {/* 顶部信息栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <Tooltip title={starred ? '取消特别关注' : '加入核心关注'}>
            <Button
              type="text"
              size="large"
              loading={starBusy}
              icon={starred ? <StarFilled style={{ color: '#faad14', fontSize: 22 }} /> : <StarOutlined style={{ fontSize: 22, color: '#bfbfbf' }} />}
              onClick={() => !starBusy && onToggleCoreWatch(signal, !starred)}
              style={{ padding: '4px 8px' }}
            />
          </Tooltip>
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
        <Col span={3}>
          <Statistic title="最新价" value={signal.latest_close ?? '-'} precision={2} valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={3}>
          <Statistic
            title="今涨幅"
            value={signal.latest_pct_chg ?? 0}
            precision={2}
            suffix="%"
            valueStyle={{ fontSize: 16, color: (signal.latest_pct_chg ?? 0) >= 0 ? '#cf1322' : '#3f8600' }}
          />
        </Col>
        <Col span={3}>
          <Statistic title="信号评分" value={signal.signal_score} suffix="/ 100" valueStyle={{ fontSize: 16, color: signal.signal_score >= 70 ? '#f5222d' : '#595959' }} />
        </Col>
        <Col span={3}>
          <Statistic title="回调幅度" value={signal.pullback_pct ?? '-'} precision={1} suffix="%" valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={3}>
          <Statistic title="距生命线" value={signal.days_since_life_line ?? '-'} suffix="天" valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={3}>
          <Statistic title="RSI" value={signal.rsi ?? '-'} precision={1} valueStyle={{ fontSize: 16 }} />
        </Col>
        <Col span={3}>
          <Statistic title="信号持续" value={signal.signal_persist_days ?? 0} suffix="天" valueStyle={{ fontSize: 16, color: (signal.signal_persist_days || 0) >= 2 ? '#722ed1' : '#595959' }} />
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

      <Card size="small" title="风险管理建议" style={{ marginTop: 12 }}>
        <Row gutter={16}>
          <Col span={8}>
            <Statistic
              title="建议止损价"
              value={signal.stop_loss_price ?? '-'}
              precision={2}
              valueStyle={{ color: '#cf1322', fontSize: 16 }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              风险空间: {signal.stop_loss_pct != null ? `${signal.stop_loss_pct.toFixed(2)}%` : '-'}
            </div>
          </Col>
          <Col span={8}>
            <Statistic
              title="第一目标价"
              value={signal.target_price ?? '-'}
              precision={2}
              valueStyle={{ color: '#3f8600', fontSize: 16 }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              目标收益: {signal.target_return_pct != null ? `${signal.target_return_pct.toFixed(2)}%` : '-'}
            </div>
          </Col>
          <Col span={8}>
            <Statistic
              title="盈亏比"
              value={signal.risk_reward_ratio ?? '-'}
              precision={2}
              suffix={signal.risk_reward_ratio != null ? ':1' : ''}
              valueStyle={{
                color:
                  signal.risk_reward_ratio == null
                    ? '#595959'
                    : signal.risk_reward_ratio >= 1.5
                      ? '#3f8600'
                      : '#fa8c16',
                fontSize: 16,
              }}
            />
            <div style={{ marginTop: 4, fontSize: 12, color: '#8c8c8c' }}>
              {signal.risk_reward_ratio != null && signal.risk_reward_ratio < 1.5 ? '提示: 盈亏比偏低，注意仓位' : '建议结合盘中量价再确认'}
            </div>
          </Col>
        </Row>
      </Card>
    </div>
  )
}

export default SignalDetail
