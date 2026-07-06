import {
  DeleteOutlined,
  PushpinFilled,
  PushpinOutlined,
} from '@ant-design/icons'
import { Button, Empty, Popconfirm, Space, Tooltip } from 'antd'
import type React from 'react'
import type {
  StockChartDataWithMarks,
  WatchStock,
} from '../../types'
import StockDetail from '../Stocks/StockDetail'

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

const PoolStockDetailPanel: React.FC<PoolStockDetailPanelProps> = ({
  onDeleteStock,
  onEditNote,
  onTogglePin,
  selectedStock,
}) => {
  if (!selectedStock) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-muted)' }}>
        <Empty description={<span style={{ color: 'var(--text-muted)' }}>从左侧列表选择一只股票</span>} />
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 2,
          display: 'flex',
          justifyContent: 'flex-end',
          padding: '0 0 8px',
          background: 'var(--bg-card)',
        }}
      >
        <Space size={4}>
          <Tooltip title={selectedStock.pinned ? '取消置顶' : '置顶'}>
            <Button
              type="text"
              size="small"
              icon={selectedStock.pinned ? <PushpinFilled style={{ color: '#faad14' }} /> : <PushpinOutlined />}
              onClick={() => onTogglePin(selectedStock)}
            />
          </Tooltip>
          <Popconfirm title="确定从当前观察池移除？" onConfirm={() => onDeleteStock(selectedStock.id)}>
            <Tooltip title="从本池移除">
              <Button type="text" size="small" danger icon={<DeleteOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      </div>
      <StockDetail
        key={selectedStock.ts_code}
        embedded
        tsCode={selectedStock.ts_code}
        stockNote={selectedStock.note || ''}
        onEditNote={onEditNote}
      />
    </div>
  )
}

export default PoolStockDetailPanel
