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
  return (
    <div
      key={stock.id}
      ref={selectedItemRef}
      onClick={() => onSelect(stock.ts_code)}
      tabIndex={0}
      style={{
        padding: '10px 14px',
        cursor: 'pointer',
        borderLeft: `3px solid ${isSelected ? 'var(--accent)' : 'transparent'}`,
        background: isSelected ? 'rgba(0,212,255,0.08)' : 'transparent',
        borderBottom: '1px solid var(--border-subtle)',
        transition: 'background 0.15s',
      }}
      onMouseEnter={(event) => {
        if (!isSelected) event.currentTarget.style.background = 'var(--bg-card-hover)'
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
                color: isStarred ? 'var(--color-warn)' : 'var(--border-strong)',
                cursor: isStarBusy ? 'wait' : 'pointer',
                opacity: isStarBusy ? 0.5 : 1,
              }}
            >
              {isStarred ? <StarFilled /> : <StarOutlined />}
            </span>
          </Tooltip>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{stock.stock_name || '-'}</span>
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {stock.pinned && <PushpinFilled style={{ color: '#faad14', fontSize: 12 }} />}
        </span>
      </div>

      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
        {stock.ts_code} {stock.industry ? `· ${stock.industry}` : ''}
        {stock.limit_up_date && <span style={{ marginLeft: 6 }}>涨停 {formatLimitDate(stock.limit_up_date)}</span>}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
        <span className="mono" style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
          {stock.latest_price != null ? stock.latest_price.toFixed(2) : '-'}
        </span>
        {stock.pct_chg != null && (
          <span
            className="mono"
            style={{
              fontWeight: 700,
              fontSize: 12,
              color: stock.pct_chg > 0 ? 'var(--color-up)' : stock.pct_chg < 0 ? 'var(--color-down)' : 'var(--text-muted)',
              padding: '1px 6px',
              borderRadius: 4,
              background: stock.pct_chg > 0 ? 'var(--color-up-dim)' : stock.pct_chg < 0 ? 'var(--color-down-dim)' : 'rgba(255,255,255,0.04)',
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
