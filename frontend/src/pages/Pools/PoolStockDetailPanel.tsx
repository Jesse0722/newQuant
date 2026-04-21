import {
  DeleteOutlined,
  EditOutlined,
  PushpinFilled,
  PushpinOutlined,
  RobotOutlined,
  StarFilled,
  StarOutlined,
} from '@ant-design/icons'
import { Button, Card, Empty, Popconfirm, Progress, Space, Spin, Tag, Tooltip, Segmented } from 'antd'
import dayjs from 'dayjs'
import type React from 'react'
import type { AiAnalysisResult, StockChartDataWithMarks, WatchStock } from '../../types'

interface PoolStockDetailPanelProps {
  aiAnalyzingStockId: string | null
  chartData: StockChartDataWithMarks | null
  chartLoading: boolean
  chartPeriod: number
  chartRef: React.RefObject<HTMLDivElement | null>
  coreWatchBusyTsCode: string | null
  coreWatchCodes: Set<string>
  onAnalyzeStock: () => void
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

const PoolStockDetailPanel: React.FC<PoolStockDetailPanelProps> = ({
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
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#bfbfbf' }}>
        <Empty description="从左侧列表选择一只股票" />
      </div>
    )
  }

  const ai = parseAiAnalysis(selectedStock.ai_analysis)
  const isCoreWatch = coreWatchCodes.has(selectedStock.ts_code)

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
          <span style={{ fontSize: 18, fontWeight: 700 }}>{selectedStock.stock_name || selectedStock.ts_code}</span>
          <span style={{ fontSize: 14, color: '#8c8c8c' }}>{selectedStock.ts_code}</span>
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
            <Popconfirm title="确定从本池移除该股票？" onConfirm={() => onDeleteStock(selectedStock.id)}>
              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Tooltip>
        </Space>
      </div>

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
        }
      >
        {chartLoading && !chartData ? (
          <div style={{ height: 440, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Spin />
          </div>
        ) : (
          <div ref={chartRef} style={{ width: '100%', height: 440, opacity: chartLoading ? 0.4 : 1, transition: 'opacity 0.2s' }} />
        )}
      </Card>

      <Card
        size="small"
        title={<span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>股票备注</span>}
        extra={
          <Tooltip title="编辑备注">
            <Button type="text" size="small" icon={<EditOutlined />} onClick={onEditNote} />
          </Tooltip>
        }
        style={{
          marginTop: 12,
          background: '#fff',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          boxShadow: 'none',
        }}
        styles={{ body: { paddingTop: 12 } }}
      >
        <div
          style={{
            minHeight: 80,
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6,
            fontSize: 14,
            color: selectedStock.note?.trim() ? '#262626' : '#bfbfbf',
          }}
        >
          {selectedStock.note?.trim() ? selectedStock.note : '暂无备注'}
        </div>
      </Card>

      <Card
        size="small"
        title={<span style={{ fontWeight: 600, fontSize: 14, color: '#262626' }}>AI 智能分析</span>}
        extra={
          <Tooltip title="分析当前股票">
            <Button
              type="text"
              size="small"
              icon={<RobotOutlined />}
              loading={aiAnalyzingStockId === selectedStock.id}
              onClick={onAnalyzeStock}
            />
          </Tooltip>
        }
        style={{
          marginTop: 12,
          background: '#fff',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          boxShadow: 'none',
        }}
        styles={{ body: { paddingTop: 12 } }}
      >
        {!ai ? (
          <div style={{ color: '#8c8c8c', minHeight: 80, lineHeight: 1.8 }}>
            点击右上角按钮进行 AI 分析，结果将独立保存，不覆盖手动备注。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Progress
                type="dashboard"
                size={72}
                percent={Math.max(0, Math.min(100, (Number(ai.score) || 0) * 10))}
                format={() => `${ai.score || 0}/10`}
              />
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Tag color={trendColor(ai.trend)}>{ai.trend || '震荡'}</Tag>
                </div>
                <div style={{ color: '#8c8c8c', fontSize: 12 }}>
                  分析时间：
                  {selectedStock.ai_analyzed_at
                    ? dayjs(selectedStock.ai_analyzed_at).format('YYYY-MM-DD HH:mm:ss')
                    : '-'}
                </div>
              </div>
            </div>
            <div style={{ lineHeight: 1.8, fontSize: 14 }}>
              <div><span style={{ color: '#8c8c8c' }}>技术面：</span>{ai.技术面 || '-'}</div>
              <div><span style={{ color: '#8c8c8c' }}>基本面：</span>{ai.基本面 || '-'}</div>
              <div><span style={{ color: '#8c8c8c' }}>量能：</span>{ai.量能 || '-'}</div>
              <div><span style={{ color: '#8c8c8c' }}>风险提示：</span>{ai.风险提示 || '-'}</div>
              <div><span style={{ color: '#8c8c8c' }}>操作建议：</span>{ai.操作建议 || '-'}</div>
            </div>
            <div style={{ fontWeight: 600, color: '#262626' }}>
              总结：{ai.summary || '-'}
            </div>
          </div>
        )}
      </Card>
    </div>
  )
}

export default PoolStockDetailPanel
