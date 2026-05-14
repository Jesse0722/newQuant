import { DownOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { Button, DatePicker, Dropdown, Empty, InputNumber, Select, Space, Spin, Switch, Tooltip } from 'antd'
import type { Dayjs } from 'dayjs'
import type React from 'react'
import type { Pool, WatchStock } from '../../types'

interface PoolSidebarProps {
  activePool: Pool | undefined
  circMvMax: number | null
  circMvMin: number | null
  hasMore: boolean
  limitUpCountMax: number | null
  limitUpCountMin: number | null
  limitUpDateFrom: Dayjs | null
  limitUpDateTo: Dayjs | null
  limitUpStatsFrom: Dayjs | null
  limitUpStatsTo: Dayjs | null
  listRef: React.RefObject<HTMLDivElement | null>
  loading: boolean
  loadingMore: boolean
  onAddStock: () => void
  onExport: () => void
  onImport: () => void
  onListScroll: () => void
  onLoadMore: () => void
  onRenderStockItem: (stock: WatchStock) => React.ReactNode
  onSetCircMvMax: (value: number | null) => void
  onSetCircMvMin: (value: number | null) => void
  onSetLimitUpCountMax: (value: number | null) => void
  onSetLimitUpCountMin: (value: number | null) => void
  onSetLimitUpDateFrom: (value: Dayjs | null) => void
  onSetLimitUpDateTo: (value: Dayjs | null) => void
  onSetLimitUpStatsFrom: (value: Dayjs | null) => void
  onSetLimitUpStatsTo: (value: Dayjs | null) => void
  onSetPriceMax: (value: number | null) => void
  onSetPriceMin: (value: number | null) => void
  onSetRisingTrendOnly: (value: boolean) => void
  onSetSort: (value: 'created_at' | 'limit_up_date', order: 'asc' | 'desc') => void
  priceMax: number | null
  priceMin: number | null
  risingTrendOnly: boolean
  sortBy: 'created_at' | 'limit_up_date'
  sortOrder: 'asc' | 'desc'
  stocks: WatchStock[]
  total: number
}

const PoolSidebar: React.FC<PoolSidebarProps> = ({
  activePool,
  circMvMax,
  circMvMin,
  hasMore,
  limitUpCountMax,
  limitUpCountMin,
  limitUpDateFrom,
  limitUpDateTo,
  limitUpStatsFrom,
  limitUpStatsTo,
  listRef,
  loading,
  loadingMore,
  onAddStock,
  onExport,
  onImport,
  onListScroll,
  onLoadMore,
  onRenderStockItem,
  onSetCircMvMax,
  onSetCircMvMin,
  onSetLimitUpCountMax,
  onSetLimitUpCountMin,
  onSetLimitUpDateFrom,
  onSetLimitUpDateTo,
  onSetLimitUpStatsFrom,
  onSetLimitUpStatsTo,
  onSetPriceMax,
  onSetPriceMin,
  onSetRisingTrendOnly,
  onSetSort,
  priceMax,
  priceMin,
  risingTrendOnly,
  sortBy,
  sortOrder,
  stocks,
  total,
}) => {
  return (
    <div style={{ width: 340, minWidth: 280, maxWidth: 380, flexShrink: 0, borderRight: '1px solid var(--border-subtle)', display: 'flex', flexDirection: 'column' }}>
      <div
        style={{
          flexShrink: 0,
          padding: '10px 12px 12px',
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border-subtle)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>股票筛选</span>
          <Dropdown
            trigger={['click']}
            menu={{
              items: [
                { key: 'add', label: '添加股票', icon: <PlusOutlined />, onClick: onAddStock },
                { key: 'import', label: 'CSV 批量导入', icon: <UploadOutlined />, onClick: onImport },
                { key: 'export', label: '导出 CSV', onClick: onExport },
              ],
            }}
          >
            <Button size="small">
              操作 <DownOutlined style={{ fontSize: 10 }} />
            </Button>
          </Dropdown>
        </div>
        <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {(activePool?.name?.includes('涨停') ?? false) && (
            <DatePicker.RangePicker
              size="small"
              style={{ width: '100%' }}
              placeholder={['涨停起始日', '涨停截止日']}
              value={limitUpDateFrom && limitUpDateTo ? [limitUpDateFrom, limitUpDateTo] : null}
              onChange={(dates) => {
                onSetLimitUpDateFrom(dates?.[0] ?? null)
                onSetLimitUpDateTo(dates?.[1] ?? null)
              }}
              allowClear
            />
          )}
          <Select
            size="small"
            value={`${sortBy}-${sortOrder}`}
            onChange={(value) => {
              const [sort, order] = value.split('-') as ['created_at' | 'limit_up_date', 'asc' | 'desc']
              onSetSort(sort, order)
            }}
            style={{ width: '100%' }}
            options={[
              { value: 'limit_up_date-desc', label: '排序：涨停日 新→旧' },
              { value: 'limit_up_date-asc', label: '排序：涨停日 旧→新' },
              { value: 'created_at-desc', label: '排序：加入时间 新→旧' },
              { value: 'created_at-asc', label: '排序：加入时间 旧→新' },
            ]}
          />
          <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>股价</span>
            <InputNumber size="small" placeholder="最低" min={0} value={priceMin ?? undefined} onChange={(value) => onSetPriceMin(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
            <InputNumber size="small" placeholder="最高" min={0} value={priceMax ?? undefined} onChange={(value) => onSetPriceMax(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
            <Tooltip title="按最新收盘价×流通股本（万股）估算流通市值，单位亿元；需已同步日线/daily_basic 数据">
              <span style={{ fontSize: 12, color: 'var(--text-secondary)', cursor: 'help' }}>市值(亿)</span>
            </Tooltip>
            <InputNumber size="small" placeholder="最低" min={0} value={circMvMin ?? undefined} onChange={(value) => onSetCircMvMin(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
            <InputNumber size="small" placeholder="最高" min={0} value={circMvMax ?? undefined} onChange={(value) => onSetCircMvMax(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '2px 2px 0' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>上升趋势</span>
              <Tooltip title="口径：latest_close > MA5 > MA10 > MA20，且 MA5(今日) >= MA5(昨日)。">
                <span style={{ fontSize: 12, color: 'var(--text-muted)', cursor: 'help', border: '1px solid var(--border-subtle)', borderRadius: '50%', width: 16, height: 16, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1 }}>?</span>
              </Tooltip>
            </div>
            <Switch
              size="small"
              checked={risingTrendOnly}
              onChange={onSetRisingTrendOnly}
              checkedChildren="开"
              unCheckedChildren="关"
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>涨停次数（选日期区间后可填次数上下限）</span>
            <DatePicker.RangePicker
              size="small"
              style={{ width: '100%' }}
              placeholder={['统计起始日', '统计截止日']}
              value={limitUpStatsFrom && limitUpStatsTo ? [limitUpStatsFrom, limitUpStatsTo] : null}
              onChange={(dates) => {
                onSetLimitUpStatsFrom(dates?.[0] ?? null)
                onSetLimitUpStatsTo(dates?.[1] ?? null)
              }}
              allowClear
            />
            <div style={{ display: 'grid', gridTemplateColumns: '56px 1fr 1fr', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>次数</span>
              <InputNumber size="small" placeholder="最少" min={0} value={limitUpCountMin ?? undefined} onChange={(value) => onSetLimitUpCountMin(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
              <InputNumber size="small" placeholder="最多" min={0} value={limitUpCountMax ?? undefined} onChange={(value) => onSetLimitUpCountMax(typeof value === 'number' ? value : null)} style={{ width: '100%' }} />
            </div>
          </div>
        </Space>
      </div>

      <div style={{ padding: '8px 14px', borderBottom: '1px solid var(--border-subtle)', fontSize: 13, color: 'var(--text-secondary)', flexShrink: 0, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span><span className="mono" style={{ color: 'var(--accent)' }}>{stocks.length}</span> 只股票</span>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>↑↓ 切换</span>
      </div>

      <div ref={listRef} onScroll={onListScroll} style={{ flex: 1, overflowY: 'auto' }}>
        {loading ? (
          <div style={{ padding: 48, textAlign: 'center' }}><Spin /></div>
        ) : stocks.length === 0 ? (
          <Empty description={activePool ? '暂无匹配股票' : '请选择或创建观察池'} style={{ padding: 48 }} />
        ) : (
          <>
            {stocks.map((stock) => onRenderStockItem(stock))}
            {hasMore && (
              <div style={{ textAlign: 'center', padding: 10 }}>
                {loadingMore ? <Spin size="small" /> : <Button size="small" onClick={onLoadMore} style={{ color: 'var(--accent)', background: 'var(--accent-dim)', border: 'none', borderRadius: 4, fontSize: 12 }}>加载更多 ({stocks.length}/{total})</Button>}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

export default PoolSidebar
