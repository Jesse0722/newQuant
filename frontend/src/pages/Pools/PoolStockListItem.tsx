import { PushpinFilled, StarFilled, StarOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'
import type React from 'react'
import type { WatchStock } from '../../types'

interface PoolStockListItemProps {
  stock: WatchStock
  isSelected: boolean
  isStarred: boolean
  isStarBusy: boolean
  onSelect: (tsCode: string) => void
  onToggleCoreWatch: (stock: WatchStock, starred: boolean) => void
  selectedItemRef?: React.Ref<HTMLDivElement>
}

function formatLimitDate(date?: string) {
  return date ? `${date.slice(4, 6)}-${date.slice(6)}` : ''
}

const PoolStockListItem: React.FC<PoolStockListItemProps> = ({
  stock,
  isSelected,
  isStarred,
  isStarBusy,
  onSelect,
  onToggleCoreWatch,
  selectedItemRef,
}) => {
  const borderColor = isSelected ? '#1677ff' : 'transparent'

  return (
    <div
      key={stock.id}
      ref={selectedItemRef}
      onClick={() => onSelect(stock.ts_code)}
      tabIndex={0}
      style={{
        padding: '10px 14px',
        cursor: 'pointer',
        borderLeft: `3px solid ${borderColor}`,
        background: isSelected ? '#f0f5ff' : 'transparent',
        borderBottom: '1px solid #f0f0f0',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!isSelected) event.currentTarget.style.background = '#fafafa'
      }}
      onMouseLeave={(event) => {
        if (!isSelected) event.currentTarget.style.background = 'transparent'
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 14 }}>
          <Tooltip title={isStarred ? '取消特别关注（从核心关注移除）' : '加入核心关注'}>
            <span
              role="button"
              tabIndex={0}
              onClick={(event) => {
                event.stopPropagation()
                if (!isStarBusy) onToggleCoreWatch(stock, !isStarred)
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  event.stopPropagation()
                  if (!isStarBusy) onToggleCoreWatch(stock, !isStarred)
                }
              }}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                color: isStarred ? '#faad14' : '#d9d9d9',
                cursor: isStarBusy ? 'wait' : 'pointer',
                opacity: isStarBusy ? 0.5 : 1,
              }}
            >
              {isStarred ? <StarFilled /> : <StarOutlined />}
            </span>
          </Tooltip>
          {stock.stock_name || '-'}
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 12 }} />}
        </span>
      </div>

      <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>
        {stock.ts_code} {stock.industry ? `· ${stock.industry}` : ''}
        {stock.limit_up_date && <span style={{ marginLeft: 6 }}>涨停 {formatLimitDate(stock.limit_up_date)}</span>}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
        <span style={{ fontFamily: "'Menlo', monospace", fontWeight: 600 }}>
          {stock.latest_price != null ? stock.latest_price.toFixed(2) : '-'}
        </span>
        {stock.pct_chg != null && (
          <span
            style={{
              fontWeight: 600,
              color: stock.pct_chg > 0 ? '#cf1322' : stock.pct_chg < 0 ? '#3f8600' : '#666',
            }}
          >
            {stock.pct_chg > 0 ? '+' : ''}
            {stock.pct_chg.toFixed(2)}%
          </span>
        )}
      </div>
    </div>
  )
}

export default PoolStockListItem
