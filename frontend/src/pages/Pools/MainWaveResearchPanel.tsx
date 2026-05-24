import {
  BranchesOutlined,
  DeleteOutlined,
  EditOutlined,
  LineChartOutlined,
  PushpinFilled,
  PushpinOutlined,
  ReloadOutlined,
  SyncOutlined,
} from '@ant-design/icons'
import { Button, Checkbox, Empty, InputNumber, Progress, Select, Space, Table, Tag, Tooltip, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import * as echarts from 'echarts'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  analyzeMainWaveStock,
  getMainWaveSectorBackfillStatus,
  getMainWaveSectorBackfillTask,
  startMainWaveSectorBackfill,
  type MainWaveAnalysis,
  type MainWaveSectorBackfillStatus,
  type MainWaveSectorBackfillTask,
} from '../../api/market'
import type { StockChartDataWithMarks, WatchStock } from '../../types'
import { makeKlineAxisTooltipFormatter } from '../../utils/klineChartTooltip'

const { Text } = Typography

interface MainWaveResearchPanelProps {
  onDeleteStock: (stockId: string) => void
  onEditNote: () => void
  onAddStock: () => void
  onImport: () => void
  onExport: () => void
  onSelectStock: (tsCode: string) => void
  onTogglePin: (stock: WatchStock) => void
  selectedStock: WatchStock | null
  stocks: WatchStock[]
  chartData: StockChartDataWithMarks | null
  chartLoading: boolean
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  main_wave_confirmed: { label: '主升确认', color: 'green' },
  breakout_tracking: { label: '突破跟踪', color: 'blue' },
  watching: { label: '趋势观察', color: 'geekblue' },
  accelerating_hot: { label: '加速过热', color: 'orange' },
  divergence_warning: { label: '分歧预警', color: 'gold' },
  exit_signal: { label: '退出信号', color: 'red' },
  invalidated: { label: '结构无效', color: 'default' },
  insufficient_data: { label: '数据不足', color: 'default' },
}

const MA20_META: Record<string, { label: string; color: string }> = {
  above: { label: 'MA20上方', color: 'green' },
  repaired: { label: '快速修复', color: 'cyan' },
  break_warning: { label: '跌破观察', color: 'gold' },
  effective_break: { label: '有效跌破', color: 'red' },
  unknown: { label: '未知', color: 'default' },
}

const SECTOR_SYNC_META: Record<string, { label: string; color: string }> = {
  pending: { label: '等待', color: 'default' },
  partial: { label: '部分', color: 'gold' },
  success: { label: '已完成', color: 'green' },
  cooldown: { label: '冷却中', color: 'orange' },
  running: { label: '同步中', color: 'blue' },
}

function formatPct(v?: number | null, signed = true) {
  if (v == null || Number.isNaN(v)) return '-'
  const prefix = signed && v > 0 ? '+' : ''
  return `${prefix}${v.toFixed(2)}%`
}

function formatScore(v?: number | null) {
  return v == null || Number.isNaN(v) ? '-' : String(Math.round(v))
}

function statusTag(status?: string) {
  const meta = STATUS_META[status || ''] || { label: status || '-', color: 'default' }
  return <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
}

function ma20Tag(state?: string) {
  const meta = MA20_META[state || ''] || { label: state || '-', color: 'default' }
  return <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>{meta.label}</Tag>
}

const MainWaveResearchPanel: React.FC<MainWaveResearchPanelProps> = ({
  onDeleteStock,
  onEditNote,
  onAddStock,
  onImport,
  onExport,
  onSelectStock,
  onTogglePin,
  selectedStock,
  stocks,
  chartData,
  chartLoading,
}) => {
  const [analysisMap, setAnalysisMap] = useState<Record<string, MainWaveAnalysis>>({})
  const [loading, setLoading] = useState(false)
  const [sectorStatus, setSectorStatus] = useState<MainWaveSectorBackfillStatus | null>(null)
  const [sectorTask, setSectorTask] = useState<MainWaveSectorBackfillTask | null>(null)
  const [syncingSectors, setSyncingSectors] = useState(false)
  const [statusFilter, setStatusFilter] = useState<string[]>([])
  const [ma20Filter, setMa20Filter] = useState<string[]>([])
  const [minScore, setMinScore] = useState<number | null>(null)
  const [resonanceOnly, setResonanceOnly] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  const loadAnalyses = useCallback(async () => {
    if (!stocks.length) {
      setAnalysisMap({})
      return
    }
    setLoading(true)
    try {
      const pairs = await Promise.all(
        stocks.map(async (stock) => {
          try {
            const res = await analyzeMainWaveStock(stock.ts_code)
            return [stock.ts_code, res.data] as const
          } catch {
            return [stock.ts_code, {
              ts_code: stock.ts_code,
              name: stock.stock_name || stock.ts_code,
              status: 'insufficient_data',
              total_score: 0,
              message: '主升浪评分失败',
            }] as const
          }
        })
      )
      setAnalysisMap(Object.fromEntries(pairs))
    } finally {
      setLoading(false)
    }
  }, [stocks])

  useEffect(() => {
    loadAnalyses()
  }, [loadAnalyses])

  const loadSectorStatus = useCallback(async () => {
    try {
      const res = await getMainWaveSectorBackfillStatus({ days: 250 })
      setSectorStatus(res.data)
    } catch {
      setSectorStatus(null)
    }
  }, [])

  useEffect(() => {
    loadSectorStatus()
  }, [loadSectorStatus, stocks.length])

  useEffect(() => {
    if (!sectorTask?.task_id || !['running', 'pending'].includes(sectorTask.status)) return
    const timer = window.setInterval(async () => {
      try {
        const res = await getMainWaveSectorBackfillTask(sectorTask.task_id)
        setSectorTask(res.data)
        if (res.data.status !== 'running') {
          window.clearInterval(timer)
          loadSectorStatus()
          loadAnalyses()
        }
      } catch {
        window.clearInterval(timer)
      }
    }, 1800)
    return () => window.clearInterval(timer)
  }, [loadAnalyses, loadSectorStatus, sectorTask?.status, sectorTask?.task_id])

  const handleBackfillSectors = async (mode: 'backfill' | 'incremental', force = false) => {
    setSyncingSectors(true)
    try {
      const res = await startMainWaveSectorBackfill({ days: 250, mode, force })
      message.success(mode === 'incremental' ? '已开始同步增量K线' : force ? '已开始重试失败项' : '已开始补齐板块K线')
      const taskRes = await getMainWaveSectorBackfillTask(res.data.task_id)
      setSectorTask(taskRes.data)
    } catch (error: unknown) {
      const err = error as { response?: { status?: number; data?: { message?: string; detail?: unknown } } }
      if (err.response?.status === 404) {
        message.error('后端服务尚未加载板块补齐接口，请重启后端服务')
      } else {
        message.error(err.response?.data?.message || '板块K线补齐启动失败')
      }
    } finally {
      setSyncingSectors(false)
    }
  }

  const rows = useMemo(() => {
    return stocks.map((stock) => ({
      key: stock.ts_code,
      stock,
      analysis: analysisMap[stock.ts_code],
    })).filter((row) => {
      const analysis = row.analysis
      if (!analysis) return true
      if (statusFilter.length && !statusFilter.includes(analysis.status)) return false
      const ma20 = analysis.ma20_state?.state || 'unknown'
      if (ma20Filter.length && !ma20Filter.includes(ma20)) return false
      if (minScore != null && analysis.total_score < minScore) return false
      if (resonanceOnly && !(analysis.scores?.sector_resonance && analysis.scores.sector_resonance > 0)) return false
      return true
    })
  }, [analysisMap, ma20Filter, minScore, resonanceOnly, statusFilter, stocks])

  const selectedAnalysis = selectedStock ? analysisMap[selectedStock.ts_code] : null

  useEffect(() => {
    if (!chartRef.current || !chartData?.quotes?.length) return
    if (!chartInstance.current) chartInstance.current = echarts.init(chartRef.current)
    const chart = chartInstance.current
    const { quotes, indicators } = chartData
    const dates = quotes.map(q => q.date)
    const ohlc = quotes.map(q => [q.open, q.close, q.low, q.high])
    const volumes = quotes.map(q => ({
      value: q.vol,
      itemStyle: { color: q.close >= q.open ? '#ec0000' : '#00da3c' },
    }))
    const markPoints: Record<string, unknown>[] = []
    const breakoutDate = selectedAnalysis?.metrics?.breakout_date
    if (breakoutDate && dates.includes(breakoutDate)) {
      const q = quotes.find(item => item.date === breakoutDate)
      if (q) {
        markPoints.push({
          name: '突破',
          coord: [breakoutDate, q.high],
          symbol: 'triangle',
          symbolSize: 13,
          itemStyle: { color: '#1677ff' },
          label: { show: true, formatter: '突破', position: 'top', color: '#1677ff', fontSize: 10 },
        })
      }
    }

    let lastBreakDate = ''
    let repairedDate = ''
    const ma20 = indicators.ma20 || []
    for (let i = 0; i < quotes.length; i += 1) {
      const m = ma20[i]
      if (m != null && quotes[i].close < m) lastBreakDate = quotes[i].date
      if (lastBreakDate && !repairedDate && m != null && quotes[i].date > lastBreakDate && quotes[i].close >= m) {
        repairedDate = quotes[i].date
      }
    }
    if (lastBreakDate) {
      const q = quotes.find(item => item.date === lastBreakDate)
      if (q) {
        markPoints.push({
          name: '破MA20',
          coord: [lastBreakDate, q.low],
          symbol: 'pin',
          symbolSize: 30,
          itemStyle: { color: '#faad14' },
          label: { show: true, formatter: '破20', color: '#8c5a00', fontSize: 10 },
        })
      }
    }
    if (selectedAnalysis?.ma20_state?.state === 'repaired' && repairedDate) {
      const q = quotes.find(item => item.date === repairedDate)
      if (q) {
        markPoints.push({
          name: '修复',
          coord: [repairedDate, q.high],
          symbol: 'circle',
          symbolSize: 12,
          itemStyle: { color: '#13c2c2' },
          label: { show: true, formatter: '修复', position: 'top', color: '#13c2c2', fontSize: 10 },
        })
      }
    }

    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' }, formatter: makeKlineAxisTooltipFormatter(quotes) },
      legend: { data: ['MA5', 'MA10', 'MA20'], top: 0, left: 'center', textStyle: { fontSize: 11 } },
      grid: [
        { left: 48, right: 16, top: 28, height: '58%' },
        { left: 48, right: 16, top: '74%', height: '16%' },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, boundaryGap: true },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { fontSize: 10 }, boundaryGap: true },
      ],
      yAxis: [
        { scale: true, gridIndex: 0, splitNumber: 4 },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false } },
      ],
      dataZoom: [{ type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 }],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0,
          yAxisIndex: 0,
          itemStyle: { color: '#ec0000', color0: '#00da3c', borderColor: '#ec0000', borderColor0: '#00da3c' },
          markPoint: markPoints.length ? { data: markPoints } : undefined,
        },
        { name: 'MA5', type: 'line', data: indicators.ma5, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
        { name: 'MA10', type: 'line', data: indicators.ma10, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { width: 1 } },
        { name: 'MA20', type: 'line', data: indicators.ma20, xAxisIndex: 0, yAxisIndex: 0, smooth: true, symbol: 'none', lineStyle: { width: 1.5 } },
        { name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1 },
      ],
    }, true)
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [chartData, selectedAnalysis])

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose()
      chartInstance.current = null
    }
  }, [])
  const summary = useMemo(() => {
    const items = Object.values(analysisMap)
    return {
      total: stocks.length,
      confirmed: items.filter(x => x.status === 'main_wave_confirmed').length,
      tracking: items.filter(x => x.status === 'breakout_tracking').length,
      warning: items.filter(x => x.status === 'divergence_warning' || x.status === 'exit_signal').length,
      repaired: items.filter(x => x.ma20_state?.state === 'repaired').length,
    }
  }, [analysisMap, stocks.length])

  const columns: ColumnsType<{ key: string; stock: WatchStock; analysis?: MainWaveAnalysis }> = [
    {
      title: '股票',
      dataIndex: 'stock',
      width: 150,
      render: (stock: WatchStock) => (
        <div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 12 }} />}
            <Text strong>{stock.stock_name || stock.ts_code}</Text>
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>{stock.ts_code}</Text>
        </div>
      ),
    },
    {
      title: '阶段',
      dataIndex: 'analysis',
      width: 100,
      render: (analysis?: MainWaveAnalysis) => statusTag(analysis?.status),
    },
    {
      title: '总分',
      dataIndex: 'analysis',
      width: 90,
      sorter: (a, b) => (a.analysis?.total_score || 0) - (b.analysis?.total_score || 0),
      render: (analysis?: MainWaveAnalysis) => (
        <Progress
          percent={analysis?.total_score || 0}
          size="small"
          showInfo
          strokeColor={(analysis?.total_score || 0) >= 75 ? '#52c41a' : '#1677ff'}
        />
      ),
    },
    {
      title: '分项',
      dataIndex: 'analysis',
      width: 150,
      render: (analysis?: MainWaveAnalysis) => (
        <Space size={4} wrap>
          <Tag>趋 {formatScore(analysis?.scores?.trend)}</Tag>
          <Tag>构 {formatScore(analysis?.scores?.structure)}</Tag>
          <Tag>修 {formatScore(analysis?.scores?.pullback_repair)}</Tag>
          <Tag>振 {formatScore(analysis?.scores?.sector_resonance)}</Tag>
        </Space>
      ),
    },
    {
      title: 'MA20',
      dataIndex: 'analysis',
      width: 110,
      render: (analysis?: MainWaveAnalysis) => (
        <Space direction="vertical" size={2}>
          {ma20Tag(analysis?.ma20_state?.state)}
          <Text type="secondary" style={{ fontSize: 12 }}>{formatPct(analysis?.ma20_state?.distance_pct)}</Text>
        </Space>
      ),
    },
    {
      title: '共振板块',
      dataIndex: 'analysis',
      width: 140,
      render: (analysis?: MainWaveAnalysis) => (
        <div>
          <Text>{analysis?.metrics?.best_sector?.sector_name || '-'}</Text>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            相对 {formatPct(analysis?.metrics?.best_sector?.relative_strength_20d)}
          </div>
        </div>
      ),
    },
    {
      title: '回撤',
      dataIndex: 'analysis',
      width: 90,
      render: (analysis?: MainWaveAnalysis) => formatPct(analysis?.metrics?.max_drawdown_10d, false),
    },
  ]

  if (!stocks.length) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="主升浪样本库暂无股票" />
      </div>
    )
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0, overflowY: 'auto', paddingRight: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <LineChartOutlined style={{ color: 'var(--accent)' }} />
            <Text strong style={{ fontSize: 16 }}>主升浪研究视图</Text>
          </div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            聚焦趋势阶段、MA20修复和板块共振
          </Text>
        </div>
        <Space wrap>
          <Button size="small" onClick={onAddStock}>添加股票</Button>
          <Button size="small" onClick={onImport}>导入</Button>
          <Button size="small" onClick={onExport}>导出</Button>
          <Button size="small" icon={<SyncOutlined spin={syncingSectors || sectorTask?.status === 'running'} />} loading={syncingSectors} onClick={() => handleBackfillSectors('backfill')}>补齐K线</Button>
          <Button size="small" onClick={() => handleBackfillSectors('backfill', true)}>重试失败</Button>
          <Button size="small" onClick={() => handleBackfillSectors('incremental')}>同步增量</Button>
          <Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={loadAnalyses}>刷新评分</Button>
        </Space>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(96px, 1fr))', gap: 8 }}>
        {[
          ['样本', summary.total],
          ['主升确认', summary.confirmed],
          ['突破跟踪', summary.tracking],
          ['风险预警', summary.warning],
          ['MA20修复', summary.repaired],
        ].map(([label, value]) => (
          <div key={label} style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '8px 10px', background: 'rgba(255,255,255,0.03)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.2 }}>{value}</div>
          </div>
        ))}
      </div>

      <SectorBackfillStatusPanel status={sectorStatus} task={sectorTask} onRefresh={loadSectorStatus} />

      <Space size={8} wrap>
        <Select
          mode="multiple"
          allowClear
          placeholder="阶段"
          style={{ minWidth: 180 }}
          value={statusFilter}
          onChange={setStatusFilter}
          options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))}
          maxTagCount="responsive"
        />
        <Select
          mode="multiple"
          allowClear
          placeholder="MA20状态"
          style={{ minWidth: 160 }}
          value={ma20Filter}
          onChange={setMa20Filter}
          options={Object.entries(MA20_META).map(([value, meta]) => ({ value, label: meta.label }))}
          maxTagCount="responsive"
        />
        <InputNumber min={0} max={100} placeholder="最低分" value={minScore} onChange={setMinScore} style={{ width: 96 }} />
        <Checkbox checked={resonanceOnly} onChange={(event) => setResonanceOnly(event.target.checked)}>仅看板块共振</Checkbox>
      </Space>

      <div style={{ flex: '0 0 auto', minHeight: 0, overflow: 'hidden', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
        <Table
          columns={columns}
          dataSource={rows}
          loading={loading}
          pagination={false}
          rowKey="key"
          size="small"
          scroll={{ x: 900, y: 220 }}
          rowClassName={(record) => record.stock.ts_code === selectedStock?.ts_code ? 'ant-table-row-selected' : ''}
          onRow={(record) => ({
            onClick: () => onSelectStock(record.stock.ts_code),
            style: { cursor: 'pointer' },
          })}
        />
      </div>

      <div style={{ flex: '0 0 auto', borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}>
        {selectedStock && selectedAnalysis ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <div>
                  <Text strong>{selectedStock.stock_name || selectedStock.ts_code}</Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>{selectedStock.ts_code}</Text>
                </div>
                <Space size={4}>
                  <Tooltip title={selectedStock.pinned ? '取消置顶' : '置顶'}>
                    <Button size="small" type="text" icon={selectedStock.pinned ? <PushpinFilled style={{ color: '#faad14' }} /> : <PushpinOutlined />} onClick={() => onTogglePin(selectedStock)} />
                  </Tooltip>
                  <Tooltip title="编辑复盘备注">
                    <Button size="small" type="text" icon={<EditOutlined />} onClick={onEditNote} />
                  </Tooltip>
                  <Tooltip title="移出样本库">
                    <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => onDeleteStock(selectedStock.id)} />
                  </Tooltip>
                </Space>
              </div>
              <Space size={6} wrap style={{ marginBottom: 10 }}>
                {statusTag(selectedAnalysis.status)}
                {ma20Tag(selectedAnalysis.ma20_state?.state)}
                <Tag color="blue">总分 {selectedAnalysis.total_score}</Tag>
              </Space>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(110px, 1fr))', gap: 8 }}>
                <Metric label="20日涨幅" value={formatPct(selectedAnalysis.metrics?.return_20d)} />
                <Metric label="60日涨幅" value={formatPct(selectedAnalysis.metrics?.return_60d)} />
                <Metric label="10日回撤" value={formatPct(selectedAnalysis.metrics?.max_drawdown_10d, false)} />
                <Metric label="突破日" value={selectedAnalysis.metrics?.breakout_date || '-'} />
              </div>
              <div style={{ marginTop: 10, border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <Text strong>结构K线</Text>
                  {chartLoading && <Text type="secondary">加载中...</Text>}
                </div>
                {chartData?.quotes?.length ? (
                  <div ref={chartRef} style={{ width: '100%', height: 260 }} />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无K线数据" />
                )}
              </div>
            </div>

            <div style={{ minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <BranchesOutlined style={{ color: 'var(--accent)' }} />
                <Text strong>板块共振与评分原因</Text>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(72px, 1fr))', gap: 8, marginBottom: 10 }}>
                <Metric label="趋势" value={formatScore(selectedAnalysis.scores?.trend)} />
                <Metric label="结构" value={formatScore(selectedAnalysis.scores?.structure)} />
                <Metric label="修复" value={formatScore(selectedAnalysis.scores?.pullback_repair)} />
                <Metric label="共振" value={formatScore(selectedAnalysis.scores?.sector_resonance)} />
              </div>
              <Text type="secondary" style={{ display: 'block', marginBottom: 6 }}>
                最佳板块：{selectedAnalysis.metrics?.best_sector?.sector_name || '暂无板块日线数据'}
                {selectedAnalysis.metrics?.best_sector?.relative_strength_20d != null
                  ? `，相对强度 ${formatPct(selectedAnalysis.metrics.best_sector.relative_strength_20d)}`
                  : ''}
              </Text>
              {selectedAnalysis.metrics?.best_sector && selectedAnalysis.metrics.best_sector.relative_strength_20d == null && (
                <Text type="secondary" style={{ display: 'block', marginBottom: 6 }}>
                  板块K线缺失，暂无法计算共振强度
                </Text>
              )}
              <ReasonList analysis={selectedAnalysis} />
            </div>
          </div>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一只样本查看主升浪拆解" />
        )}
      </div>
    </div>
  )
}

const Metric: React.FC<{ label: string; value: string | number }> = ({ label, value }) => (
  <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 6, padding: '6px 8px', minWidth: 0 }}>
    <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
  </div>
)

const SectorBackfillStatusPanel: React.FC<{
  status: MainWaveSectorBackfillStatus | null
  task: MainWaveSectorBackfillTask | null
  onRefresh: () => void
}> = ({ status, task, onRefresh }) => {
  const items = status?.items || []
  const progress = status?.concept_count ? Math.round((status.completed_count / status.concept_count) * 100) : 0
  return (
    <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 10, background: 'rgba(255,255,255,0.03)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', marginBottom: 8 }}>
        <Space size={8} wrap>
          <Text strong>板块K线数据底座</Text>
          <Tag color="blue">概念 {status?.concept_count ?? '-'}</Tag>
          <Tag color="green">完成 {status?.completed_count ?? '-'}</Tag>
          <Tag color="orange">冷却 {status?.cooldown_count ?? '-'}</Tag>
          <Tag>股票映射 {status?.stock_count ?? '-'}</Tag>
        </Space>
        <Button size="small" type="text" icon={<ReloadOutlined />} onClick={onRefresh}>刷新</Button>
      </div>
      <Progress percent={progress} size="small" showInfo />
      {task && (
        <div style={{ marginTop: 6 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            任务：{task.message || task.status}，进度 {Math.round((task.progress || 0) * 100)}%
          </Text>
        </div>
      )}
      <Space size={6} wrap style={{ marginTop: 8 }}>
        {items.slice(0, 10).map((item) => {
          const meta = SECTOR_SYNC_META[item.status] || { label: item.status || '-', color: 'default' }
          return (
            <Tooltip
              key={item.sector_code}
              title={`已有 ${item.quote_count}/${item.target_days || '-'}；最新 ${item.last_trade_date || '-'}；${item.last_error || ''}`}
            >
              <Tag color={meta.color} style={{ marginInlineEnd: 0 }}>
                {item.sector_name} {item.quote_count}/{item.target_days || '-'} {meta.label}
              </Tag>
            </Tooltip>
          )
        })}
      </Space>
    </div>
  )
}

const ReasonList: React.FC<{ analysis: MainWaveAnalysis }> = ({ analysis }) => {
  const reasons = [
    ...(analysis.reasons?.trend || []),
    ...(analysis.reasons?.structure || []),
    ...(analysis.reasons?.pullback_repair || []),
    ...(analysis.reasons?.sector_resonance || []),
  ].slice(0, 8)
  if (!reasons.length) {
    return <Text type="secondary">{analysis.message || '暂无满足的主升浪条件'}</Text>
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {reasons.map((reason) => <Tag key={reason}>{reason}</Tag>)}
    </div>
  )
}

export default MainWaveResearchPanel
