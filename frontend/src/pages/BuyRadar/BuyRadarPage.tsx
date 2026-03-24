import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Button, Segmented, Spin, message, Badge, Space } from 'antd'
import { RadarChartOutlined, ScanOutlined, ReloadOutlined } from '@ant-design/icons'
import { scanBuySignals } from '../../api/strategy'
import SignalList from './SignalList'
import SignalDetail from './SignalDetail'
import type { BuySignal, BuySignalStatus, BuySignalScanResult } from '../../types'

type FilterStatus = 'all' | BuySignalStatus

const BuyRadarPage: React.FC = () => {
  const [scanResult, setScanResult] = useState<BuySignalScanResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<FilterStatus>('all')
  const [selectedSignal, setSelectedSignal] = useState<BuySignal | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const filteredSignals = scanResult
    ? filter === 'all'
      ? scanResult.signals.filter((s) => s.signal_status !== 'invalidated')
      : scanResult.signals.filter((s) => s.signal_status === filter)
    : []

  const handleScan = async () => {
    setLoading(true)
    try {
      const res = await scanBuySignals()
      setScanResult(res.data)
      message.success(
        `扫描完成: ${res.data.triggered_count} 只触发, ${res.data.approaching_count} 只接近, 共 ${res.data.total} 只`
      )
      if (res.data.signals.length > 0) {
        const first = res.data.signals.find((s) => s.signal_status !== 'invalidated') || res.data.signals[0]
        setSelectedSignal(first)
      }
    } catch {
      message.error('扫描失败，请确保已执行涨停筛选并同步K线')
    } finally {
      setLoading(false)
    }
  }

  const handleSelect = useCallback((signal: BuySignal) => {
    setSelectedSignal(signal)
  }, [])

  // 键盘快捷键：上下切换
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!filteredSignals.length) return
      const currentIdx = selectedSignal
        ? filteredSignals.findIndex((s) => s.ts_code === selectedSignal.ts_code)
        : -1

      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault()
        const next = Math.min(currentIdx + 1, filteredSignals.length - 1)
        setSelectedSignal(filteredSignals[next])
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault()
        const prev = Math.max(currentIdx - 1, 0)
        setSelectedSignal(filteredSignals[prev])
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [filteredSignals, selectedSignal])

  const scanTime = scanResult?.scan_time
    ? new Date(scanResult.scan_time).toLocaleString('zh-CN')
    : null

  return (
    <div ref={containerRef} style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 112px)' }}>
      {/* 顶部工具栏 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '12px 0', borderBottom: '1px solid #f0f0f0', marginBottom: 0, flexShrink: 0,
      }}>
        <Space size="middle">
          <Button
            type="primary"
            icon={<ScanOutlined />}
            loading={loading}
            onClick={handleScan}
            size="large"
          >
            扫描买点
          </Button>
          <Segmented
            options={[
              { label: `全部${scanResult ? ` (${scanResult.signals.filter(s => s.signal_status !== 'invalidated').length})` : ''}`, value: 'all' },
              {
                label: (
                  <Badge count={scanResult?.triggered_count || 0} size="small" offset={[8, -2]}>
                    <span style={{ padding: '0 4px' }}>已触发</span>
                  </Badge>
                ),
                value: 'triggered',
              },
              {
                label: (
                  <Badge count={scanResult?.approaching_count || 0} size="small" offset={[8, -2]} color="#fa8c16">
                    <span style={{ padding: '0 4px' }}>接近</span>
                  </Badge>
                ),
                value: 'approaching',
              },
              { label: '跟踪中', value: 'tracking' },
              { label: '已失效', value: 'invalidated' },
            ]}
            value={filter}
            onChange={(v) => setFilter(v as FilterStatus)}
          />
        </Space>
        <div style={{ fontSize: 12, color: '#8c8c8c' }}>
          {scanTime && <>扫描时间: {scanTime}</>}
          <span style={{ marginLeft: 12, color: '#bfbfbf' }}>
            快捷键: <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11 }}>↑</kbd>
            <kbd style={{ border: '1px solid #d9d9d9', borderRadius: 3, padding: '0 4px', fontSize: 11, marginLeft: 2 }}>↓</kbd> 切换
          </span>
        </div>
      </div>

      {/* 主体：左右分栏 */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, marginTop: 0 }}>
        {/* 左侧信号列表 */}
        <div style={{
          width: 320, minWidth: 280, maxWidth: 360, flexShrink: 0,
          borderRight: '1px solid #f0f0f0', background: '#fff',
          display: 'flex', flexDirection: 'column',
        }}>
          <div style={{
            padding: '8px 14px', borderBottom: '1px solid #f0f0f0',
            fontSize: 13, color: '#8c8c8c', flexShrink: 0,
          }}>
            {filteredSignals.length} 只股票
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ textAlign: 'center', padding: 48 }}><Spin tip="扫描中..." /></div>
            ) : (
              <SignalList
                signals={filteredSignals}
                selectedCode={selectedSignal?.ts_code || null}
                onSelect={handleSelect}
              />
            )}
          </div>
        </div>

        {/* 右侧详情 */}
        <div style={{ flex: 1, minWidth: 0, padding: '12px 16px', overflowY: 'auto' }}>
          <SignalDetail signal={selectedSignal} />
        </div>
      </div>
    </div>
  )
}

export default BuyRadarPage
