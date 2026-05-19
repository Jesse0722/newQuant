import {
  DeleteOutlined,
  EditOutlined,
  PushpinFilled,
  PushpinOutlined,
  RobotOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import { Button, Empty, Progress, Space, Spin, Tag, Tooltip, Segmented } from 'antd'
import dayjs from 'dayjs'
import type React from 'react'
import type { AiAnalysisResult, StockChartDataWithMarks, WatchStock } from '../../types'

interface PoolStockDetailPanelProps {
  aiAnalyzingMode: 'fast' | 'deep' | null
  aiAnalyzingStockId: string | null
  chartData: StockChartDataWithMarks | null
  chartLoading: boolean
  chartPeriod: number
  chartRef: React.RefObject<HTMLDivElement | null>
  coreWatchBusyTsCode: string | null
  coreWatchCodes: Set<string>
  onAnalyzeStock: (mode: 'fast' | 'deep') => void
  onDeleteStock: (stockId: string) => void
  onEditNote: () => void
  onSetChartPeriod: (period: number) => void
  onSetSubIndicator: (value: 'macd' | 'rsi') => void
  onToggleCoreWatch: (stock: WatchStock, starred: boolean) => void
  onTogglePin: (stock: WatchStock) => void
  selectedStock: WatchStock | null
  subIndicator: 'macd' | 'rsi'
}

function parseAiAnalysis(raw?: string): AiAnalysisResult | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as AiAnalysisResult
  } catch {
    return null
  }
}

function trendColor(trend?: string) {
  if (trend === '上涨') return 'green'
  if (trend === '下跌') return 'red'
  return 'default'
}

function ratingColor(rating?: string) {
  if (rating === '强关注') return 'red'
  if (rating === '观察') return 'blue'
  if (rating === '谨慎') return 'orange'
  return 'default'
}

function scorePercent(score?: number) {
  const value = Number(score) || 0
  return Math.max(0, Math.min(100, value <= 10 ? value * 10 : value))
}

type RichAiAnalysisResult = AiAnalysisResult & {
  rating?: string
  confidence?: number
  time_horizon?: string
}

const PoolStockDetailPanel: React.FC<PoolStockDetailPanelProps> = ({
  aiAnalyzingMode,
  aiAnalyzingStockId,
  chartData,
  chartLoading,
  chartPeriod,
  chartRef,
  coreWatchBusyTsCode,
  coreWatchCodes,
  onAnalyzeStock,
  onDeleteStock,
  onEditNote,
  onSetChartPeriod,
  onSetSubIndicator,
  onToggleCoreWatch,
  onTogglePin,
  selectedStock,
  subIndicator,
}) => {
  if (!selectedStock) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)' }}>
        <Empty description={<span style={{ color: 'var(--text-muted)' }}>从左侧列表选择一只股票</span>} />
      </div>
    )
  }

  const ai = parseAiAnalysis(selectedStock.ai_analysis) as RichAiAnalysisResult | null
  const isCoreWatch = coreWatchCodes.has(selectedStock.ts_code)
  const isAnalyzingCurrentStock = aiAnalyzingStockId === selectedStock.id

  return (
    <div style={{ overflowY: 'auto', height: '100%', padding: '0 0 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Tooltip title={isCoreWatch ? '取消特别关注' : '加入核心关注'}>
            <Button
              type="text"
              size="large"
              loading={coreWatchBusyTsCode === selectedStock.ts_code}
              icon={
                isCoreWatch ? (
                  <StarFilled style={{ color: '#faad14', fontSize: 22 }} />
                ) : (
                  <StarOutlined style={{ fontSize: 22, color: '#bfbfbf' }} />
                )
              }
              onClick={() =>
                coreWatchBusyTsCode !== selectedStock.ts_code &&
                onToggleCoreWatch(selectedStock, !isCoreWatch)
              }
              style={{ padding: '4px 8px' }}
            />
          </Tooltip>
          <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>{selectedStock.stock_name || selectedStock.ts_code}</span>
          <span style={{ fontSize: 13, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{selectedStock.ts_code}</span>
          {selectedStock.industry && <Tag>{selectedStock.industry}</Tag>}
        </div>
        <Space size={4}>
          <Tooltip title={selectedStock.pinned ? '取消置顶' : '置顶'}>
            <Button
              type="text"
              size="small"
              icon={selectedStock.pinned ? <PushpinFilled style={{ color: '#faad14' }} /> : <PushpinOutlined />}
              onClick={() => onTogglePin(selectedStock)}
            />
          </Tooltip>
          <Tooltip title="从本池移除">
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => onDeleteStock(selectedStock.id)}
            />
          </Tooltip>
        </Space>
      </div>

      {/* ── K线图卡片 ── */}
      <div style={{ marginBottom: 12, background: 'var(--bg-surface)', border: '1px solid var(--border-default)', borderRadius: 10, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>K 线图</span>
          <Space>
            <Segmented
              size="small"
              options={[
                { label: '60日', value: 60 },
                { label: '120日', value: 120 },
                { label: '250日', value: 250 },
              ]}
              value={chartPeriod}
              onChange={(value) => onSetChartPeriod(value as number)}
            />
            <Segmented
              size="small"
              options={[
                { label: 'MACD', value: 'macd' },
                { label: 'RSI', value: 'rsi' },
              ]}
              value={subIndicator}
              onChange={(value) => onSetSubIndicator(value as 'macd' | 'rsi')}
            />
          </Space>
        </div>
        {chartLoading && !chartData ? (
          <div style={{ height: 440, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-surface)' }}>
            <Spin />
          </div>
        ) : (
          <div ref={chartRef} style={{ width: '100%', height: 440, opacity: chartLoading ? 0.4 : 1, transition: 'opacity 0.2s', background: 'var(--bg-surface)' }} />
        )}
      </div>

      {/* ── 股票备注卡片 ── */}
      <div
        style={{
          marginTop: 12,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 10,
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>股票备注</span>
          <Tooltip title="编辑备注">
            <Button type="text" size="small" icon={<EditOutlined />} onClick={onEditNote} style={{ color: 'var(--text-secondary)' }} />
          </Tooltip>
        </div>
        <div
          style={{
            padding: '12px 16px',
            minHeight: 80,
            whiteSpace: 'pre-wrap',
            lineHeight: 1.8,
            fontSize: 14,
            color: selectedStock.note?.trim() ? 'var(--text-primary)' : 'var(--text-muted)',
          }}
        >
          {selectedStock.note?.trim() ? selectedStock.note : '暂无备注'}
        </div>
      </div>

      {/* ── AI 智能分析卡片 ── */}
      <div
        style={{
          marginTop: 12,
          background: 'var(--bg-surface)',
          border: '1px solid var(--border-default)',
          borderRadius: 10,
          overflow: 'hidden',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)' }}>
          <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)' }}>AI 智能分析</span>
          <Space size={4}>
            <Tooltip title="使用 deepseek-v4-flash，适合快速刷新观察结论">
              <Button
                type="text"
                size="small"
                icon={<RobotOutlined />}
                loading={isAnalyzingCurrentStock && aiAnalyzingMode === 'fast'}
                disabled={isAnalyzingCurrentStock && aiAnalyzingMode !== 'fast'}
                onClick={() => onAnalyzeStock('fast')}
                style={{ color: 'var(--accent)' }}
              >
                快速
              </Button>
            </Tooltip>
            <Tooltip title="使用 deepseek-v4-pro，适合结合基本面、消息面和观察池上下文做深度分析">
              <Button
                type="text"
                size="small"
                loading={isAnalyzingCurrentStock && aiAnalyzingMode === 'deep'}
                disabled={isAnalyzingCurrentStock && aiAnalyzingMode !== 'deep'}
                onClick={() => onAnalyzeStock('deep')}
                style={{ color: 'var(--accent)' }}
              >
                深度
              </Button>
            </Tooltip>
          </Space>
        </div>
        <div style={{ padding: '12px 16px' }}>
          {!ai ? (
            <div style={{ color: 'var(--text-muted)', minHeight: 80, lineHeight: 1.8, fontSize: 13 }}>
              使用快速或深度分析生成研究摘要，结果将独立保存，不覆盖手动备注。
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Progress
                  type="dashboard"
                  size={72}
                  percent={scorePercent(ai.score)}
                  format={() => `${scorePercent(ai.score)}`}
                />
                <div>
                  <div style={{ marginBottom: 4, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {ai.rating && <Tag color={ratingColor(ai.rating)}>{ai.rating}</Tag>}
                    <Tag color={trendColor(ai.trend)}>{ai.trend || '震荡'}</Tag>
                    {ai.time_horizon && <Tag>{ai.time_horizon}</Tag>}
                    {ai.confidence != null && <Tag>置信度 {ai.confidence}</Tag>}
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                    分析时间：
                    {selectedStock.ai_analyzed_at
                      ? dayjs(selectedStock.ai_analyzed_at).format('YYYY-MM-DD HH:mm:ss')
                      : '-'}
                  </div>
                </div>
              </div>
              <div style={{ lineHeight: 1.8, fontSize: 13 }}>
                <div><span style={{ color: 'var(--text-muted)' }}>技术面：</span><span style={{ color: 'var(--text-primary)' }}>{ai.技术面 || '-'}</span></div>
                <div><span style={{ color: 'var(--text-muted)' }}>基本面：</span><span style={{ color: 'var(--text-primary)' }}>{ai.基本面 || '-'}</span></div>
                <div><span style={{ color: 'var(--text-muted)' }}>量能：</span><span style={{ color: 'var(--text-primary)' }}>{ai.量能 || '-'}</span></div>
                <div><span style={{ color: 'var(--color-down)' }}>风险提示：</span><span style={{ color: 'var(--text-secondary)' }}>{ai.风险提示 || '-'}</span></div>
                <div><span style={{ color: 'var(--color-up)' }}>操作建议：</span><span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{ai.操作建议 || '-'}</span></div>
              </div>
              <div style={{ fontWeight: 600, color: 'var(--accent)', fontSize: 13, padding: '8px 12px', background: 'var(--accent-glow)', borderRadius: 6, border: '1px solid var(--accent-border)' }}>
                总结：{ai.summary || '-'}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default PoolStockDetailPanel
