import React from 'react'
import { Tag, Empty, Tooltip } from 'antd'
import { StarFilled, StarOutlined } from '@ant-design/icons'
import type { BuySignal, BuySignalStatus } from '../../types'

const STATUS_CONFIG: Record<BuySignalStatus, { color: string; label: string }> = {
  triggered: { color: '#f5222d', label: '已触发' },
  approaching: { color: '#fa8c16', label: '接近' },
  tracking: { color: '#1890ff', label: '跟踪中' },
  invalidated: { color: '#bfbfbf', label: '已失效' },
}

interface Props {
  signals: BuySignal[]
  selectedCode: string | null
  onSelect: (signal: BuySignal) => void
  coreWatchCodes: Set<string>
  onToggleCoreWatch: (signal: BuySignal, starred: boolean) => void
  coreWatchBusyTsCode?: string | null
}

const SignalList: React.FC<Props> = ({
  signals,
  selectedCode,
  onSelect,
  coreWatchCodes,
  onToggleCoreWatch,
  coreWatchBusyTsCode,
}) => {
  if (signals.length === 0) {
    return (
      <div style={{ padding: 32, textAlign: 'center' }}>
        <Empty description="暂无信号，请先执行涨停筛选并扫描买点" />
      </div>
    )
  }

  return (
    <div style={{ overflowY: 'auto', height: '100%' }}>
      {signals.map((s) => {
        const cfg = STATUS_CONFIG[s.signal_status] || STATUS_CONFIG.tracking
        const isActive = s.ts_code === selectedCode
        const starred = coreWatchCodes.has(s.ts_code)
        const busy = coreWatchBusyTsCode === s.ts_code
        return (
          <div
            key={s.ts_code}
            onClick={() => onSelect(s)}
            tabIndex={0}
            style={{
              padding: '10px 14px',
              cursor: 'pointer',
              borderLeft: isActive ? `3px solid ${cfg.color}` : '3px solid transparent',
              background: isActive ? '#f0f5ff' : 'transparent',
              borderBottom: '1px solid #f0f0f0',
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => {
              if (!isActive) e.currentTarget.style.background = '#fafafa'
            }}
            onMouseLeave={(e) => {
              if (!isActive) e.currentTarget.style.background = 'transparent'
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600, fontSize: 14 }}>
                <Tooltip title={starred ? '取消特别关注（从核心关注移除）' : '加入核心关注'}>
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={(e) => {
                      e.stopPropagation()
                      if (!busy) onToggleCoreWatch(s, !starred)
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        e.stopPropagation()
                        if (!busy) onToggleCoreWatch(s, !starred)
                      }
                    }}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      color: starred ? '#faad14' : '#d9d9d9',
                      cursor: busy ? 'wait' : 'pointer',
                      opacity: busy ? 0.5 : 1,
                    }}
                  >
                    {starred ? <StarFilled /> : <StarOutlined />}
                  </span>
                </Tooltip>
                {s.name}
              </span>
              <Tag color={cfg.color} style={{ margin: 0, fontSize: 11, lineHeight: '18px', padding: '0 6px' }}>
                {cfg.label}
              </Tag>
            </div>

            <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 4 }}>
              {s.ts_code} {s.industry ? `· ${s.industry}` : ''}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#595959' }}>
              <span>评分: <b style={{ color: s.signal_score >= 70 ? '#f5222d' : s.signal_score >= 50 ? '#fa8c16' : '#8c8c8c' }}>{s.signal_score}</b></span>
              {s.life_line_date && (
                <span>涨停: {s.life_line_date.slice(4, 6)}-{s.life_line_date.slice(6)}</span>
              )}
            </div>

            {s.pullback_pct != null && s.signal_status !== 'invalidated' && (
              <div style={{ fontSize: 12, color: '#595959', marginTop: 2 }}>
                <span>回调: <b style={{ color: '#3f8600' }}>-{s.pullback_pct}%</b></span>
                {s.latest_pct_chg != null && (
                  <span style={{ marginLeft: 12 }}>
                    今涨: <b style={{ color: s.latest_pct_chg >= 0 ? '#cf1322' : '#3f8600' }}>
                      {s.latest_pct_chg >= 0 ? '+' : ''}{s.latest_pct_chg.toFixed(2)}%
                    </b>
                  </span>
                )}
              </div>
            )}

            {s.signal_status === 'approaching' && s.unmet_conditions.length > 0 && (
              <div style={{ fontSize: 11, color: '#fa8c16', marginTop: 2 }}>
                差{s.unmet_conditions.length}条件: {s.unmet_conditions.slice(0, 2).join('、')}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default SignalList
