import { HolderOutlined, LineChartOutlined, ReloadOutlined, SyncOutlined } from '@ant-design/icons'
import { Button, Space } from 'antd'
import type React from 'react'
import type { Pool } from '../../types'

interface PoolToolbarProps {
  activePool: Pool | undefined
  activePoolId: string
  dragOverIndex: number | null
  onAddPool: () => void
  onCreateMainWavePool: () => void
  onDeletePool: (poolId: string) => void
  onDragEnd: () => void
  onDragLeave: () => void
  onDragOver: (event: React.DragEvent, index: number) => void
  onDragStart: (event: React.DragEvent, index: number) => void
  onDrop: (event: React.DragEvent, index: number) => void
  onEditPool: () => void
  onReload: () => void
  onSelectPool: (poolId: string) => void
  onSync: () => void
  pools: Pool[]
  syncing: boolean
}

const PoolToolbar: React.FC<PoolToolbarProps> = ({
  activePool,
  activePoolId,
  dragOverIndex,
  onAddPool,
  onCreateMainWavePool,
  onDeletePool,
  onDragEnd,
  onDragLeave,
  onDragOver,
  onDragStart,
  onDrop,
  onEditPool,
  onReload,
  onSelectPool,
  onSync,
  pools,
  syncing,
}) => {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexShrink: 0 }}>
      <div
        style={{ display: 'flex', gap: 4, flexWrap: 'wrap', flex: 1, minWidth: 0 }}
        onDragEnd={onDragEnd}
        onDragLeave={onDragLeave}
      >
        {pools.map((pool, index) => (
          <div
            key={pool.id}
            draggable
            onDragStart={(event) => onDragStart(event, index)}
            onDragOver={(event) => onDragOver(event, index)}
            onDrop={(event) => onDrop(event, index)}
            onClick={() => onSelectPool(pool.id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '4px 10px',
              fontSize: 13,
              cursor: 'pointer',
              userSelect: 'none',
              borderRadius: 6,
              background: activePoolId === pool.id
                ? 'rgba(0,212,255,0.15)'
                : dragOverIndex === index
                ? 'rgba(0,212,255,0.06)'
                : 'rgba(255,255,255,0.04)',
              color: activePoolId === pool.id ? 'var(--accent)' : 'var(--text-secondary)',
              fontWeight: activePoolId === pool.id ? 600 : 400,
              border: activePoolId === pool.id
                ? '1px solid var(--accent-border)'
                : '1px solid var(--border-subtle)',
              transition: 'all 0.15s',
            }}
          >
            <HolderOutlined style={{ fontSize: 10, opacity: 0.4, cursor: 'grab' }} />
            <span>{pool.name}</span>
            <span style={{ opacity: 0.6, fontSize: 12 }}>({pool.stock_count})</span>
            <span
              onClick={(event) => {
                event.stopPropagation()
                onDeletePool(pool.id)
              }}
              style={{ marginLeft: 2, cursor: 'pointer', opacity: 0.4, fontSize: 11, lineHeight: 1 }}
            >
              ×
            </span>
          </div>
        ))}
        <div
          onClick={onAddPool}
          style={{ padding: '4px 10px', fontSize: 13, cursor: 'pointer', borderRadius: 6, border: '1px dashed var(--border-strong)', color: 'var(--text-muted)' }}
        >
          + 新建
        </div>
        {!pools.some(pool => `${pool.name} ${pool.description || ''}`.includes('主升浪')) && (
          <div
            onClick={onCreateMainWavePool}
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '4px 10px', fontSize: 13, cursor: 'pointer', borderRadius: 6, border: '1px dashed var(--accent-border)', color: 'var(--accent)' }}
          >
            <LineChartOutlined style={{ fontSize: 12 }} />
            主升浪样本库
          </div>
        )}
      </div>
      {activePool && (
        <Space size="small" style={{ flexShrink: 0, marginLeft: 8 }}>
          <Button size="small" icon={<SyncOutlined spin={syncing} />} loading={syncing} onClick={onSync}>同步</Button>
          <Button size="small" onClick={onEditPool}>重命名/设置</Button>
          <Button size="small" icon={<ReloadOutlined />} onClick={onReload} />
        </Space>
      )}
    </div>
  )
}

export default PoolToolbar
