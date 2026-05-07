import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Spin, Table, Tag, Tooltip, Progress } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  ReloadOutlined,
  ThunderboltOutlined,
  FallOutlined,
  FireOutlined,
  WarningOutlined,
  RiseOutlined,
} from '@ant-design/icons'
import axios from 'axios'
import { getDashboard } from '../../api/dashboard'
import type { DashboardData, DashboardFlowSectorRow, DashboardLimitLadderRow } from '../../types'
import StatCard from '../../components/StatCard'

function parseDashboardError(err: unknown): { message: string; hint?: string } {
  if (axios.isAxiosError(err)) {
    const raw = err.response?.data as { detail?: unknown; message?: unknown; hint?: unknown } | undefined
    if (typeof raw?.message === 'string' && raw.message.trim()) {
      return { message: raw.message, hint: typeof raw?.hint === 'string' ? raw.hint : undefined }
    }
    const d = raw?.detail
    if (typeof d === 'string' && d.trim()) return { message: d }
    if (d && typeof d === 'object' && d !== null && 'message' in d) {
      const o = d as { message?: string; hint?: string }
      return { message: String(o.message ?? '请求失败'), hint: o.hint ? String(o.hint) : undefined }
    }
    if (err.message) return { message: err.message }
  }
  if (err instanceof Error) return { message: err.message }
  return { message: '加载失败' }
}

const PctCell: React.FC<{ value?: number | null }> = ({ value }) => {
  if (value == null || Number.isNaN(value)) return <span style={{ color: 'var(--text-muted)' }}>-</span>
  const up = value >= 0
  return <span className={up ? 'up mono' : 'down mono'}>{up ? '+' : ''}{value.toFixed(2)}%</span>
}

const LadderTags: React.FC<{
  title: string
  icon: React.ReactNode
  data: DashboardLimitLadderRow[]
  tone: 'up' | 'down'
  onGoStock: (tsCode: string) => void
}> = ({ title, icon, data, tone, onGoStock }) => {
  const top = data.slice(0, 12)
  return (
    <div className="glow-card" style={{ padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ color: tone === 'up' ? 'var(--color-up)' : 'var(--color-down)' }}>{icon}</span>
        <span style={{ fontWeight: 700 }}>{title}</span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
        {top.length === 0 && <span style={{ color: 'var(--text-muted)' }}>暂无数据</span>}
        {top.map((x) => (
          <Tag
            key={`${x.ts_code}-${x.trade_date}`}
            style={{
              cursor: 'pointer',
              border: 'none',
              background: tone === 'up' ? 'var(--color-up-dim)' : 'var(--color-down-dim)',
              color: tone === 'up' ? 'var(--color-up)' : 'var(--color-down)',
              fontFamily: 'var(--font-mono)',
              paddingInline: 8,
            }}
            onClick={() => onGoStock(x.ts_code)}
          >
            {x.name} {x.nums}板
          </Tag>
        ))}
      </div>
    </div>
  )
}

const Dashboard: React.FC = () => {
  const navigate = useNavigate()
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null)

  const requestDashboard = useCallback(() => {
    getDashboard()
      .then((res) => { setData(res.data); setError(null) })
      .catch((e) => { setData(null); setError(parseDashboardError(e)) })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { requestDashboard() }, [requestDashboard])

  const inflowSectors: DashboardFlowSectorRow[] = useMemo(
    () => data?.inflow_sectors ?? (data?.sectors as DashboardFlowSectorRow[] | undefined) ?? [],
    [data],
  )
  const outflowSectors: DashboardFlowSectorRow[] = useMemo(
    () => data?.outflow_sectors ?? [],
    [data],
  )
  const inflowLadder: DashboardLimitLadderRow[] = useMemo(
    () => data?.inflow_ladder ?? data?.ladder ?? [],
    [data],
  )
  const outflowLadder: DashboardLimitLadderRow[] = useMemo(
    () => data?.outflow_ladder ?? [],
    [data],
  )

  const summary = useMemo(() => {
    const s = data?.summary
    if (s) return s
    const inflowLimitCount = inflowSectors.reduce((acc, x) => acc + Number(x.up_nums || 0), 0)
    const outflowLimitCount = outflowSectors.reduce((acc, x) => acc + Number(x.down_nums || 0), 0)
    return {
      inflow_sector_count: inflowSectors.length,
      outflow_sector_count: outflowSectors.length,
      inflow_limit_count: inflowLimitCount,
      outflow_limit_count: outflowLimitCount,
      net_limit_count: inflowLimitCount - outflowLimitCount,
      flow_ratio: outflowLimitCount > 0 ? Number((inflowLimitCount / outflowLimitCount).toFixed(2)) : null,
      max_up_streak: Math.max(...inflowLadder.map((x) => Number(x.nums || 0)), 0),
      max_down_streak: Math.max(...outflowLadder.map((x) => Number(x.nums || 0)), 0),
    }
  }, [data, inflowSectors, outflowSectors, inflowLadder, outflowLadder])

  const netAbs = Math.max(Math.abs(summary.net_limit_count), 1)
  const netPct = Math.min(100, Math.round((Math.abs(summary.net_limit_count) / (summary.inflow_limit_count + summary.outflow_limit_count || 1)) * 100))

  const inflowColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58 },
    { title: '流入板块', dataIndex: 'name', key: 'name', width: 140 },
    { title: '涨停家数', dataIndex: 'up_nums', key: 'up_nums', width: 90, render: (v?: number | null) => <span className="up mono">{v ?? '-'}</span> },
    { title: '连板数', dataIndex: 'cons_nums', key: 'cons_nums', width: 80, render: (v?: number | null) => (v == null ? '-' : v) },
    {
      title: (
        <Tooltip title="涨停板块口径的强度值，非板块指数日涨幅">
          <span>板块强度</span>
        </Tooltip>
      ),
      dataIndex: 'pct_chg',
      key: 'pct_chg',
      width: 92,
      render: (v?: number | null) => <PctCell value={v} />,
    },
    { title: '连板高度', dataIndex: 'up_stat', key: 'up_stat', render: (v?: string | null) => v || '-' },
  ]

  const outflowColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58 },
    { title: '流出板块', dataIndex: 'name', key: 'name', width: 140 },
    { title: '跌停家数', dataIndex: 'down_nums', key: 'down_nums', width: 90, render: (v?: number | null) => <span className="down mono">{v ?? '-'}</span> },
    { title: '连续跌停', dataIndex: 'max_limit_times', key: 'max_limit_times', width: 90, render: (v?: number | null) => (v == null ? '-' : v) },
    { title: '板块强度', dataIndex: 'pct_chg', key: 'pct_chg', width: 92, render: (v?: number | null) => <PctCell value={v} /> },
  ]

  if (loading && !data && !error) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 400, gap: 12 }}>
        <Spin size="large" />
        <span style={{ color: 'var(--text-muted)' }}>正在加载资金流向看板...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="glow-card" style={{ maxWidth: 560, margin: '60px auto', padding: 28, textAlign: 'center' }}>
        <div style={{ fontSize: 18, color: 'var(--color-down)', fontWeight: 700 }}>{error.message}</div>
        {error.hint && <div style={{ marginTop: 8, color: 'var(--text-muted)' }}>{error.hint}</div>}
        <Button style={{ marginTop: 16 }} type="primary" onClick={() => { setLoading(true); requestDashboard() }} icon={<ReloadOutlined />}>重试</Button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>资金流向总览</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            数据日期：<span className="mono" style={{ color: 'var(--accent)' }}>{data?.trade_date ?? '-'}</span>
          </div>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => { setLoading(true); requestDashboard() }}
          loading={loading}
          style={{ background: 'var(--accent-dim)', borderColor: 'var(--accent-border)', color: 'var(--accent)' }}
        >
          刷新数据
        </Button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 12 }}>
        <StatCard title="流入板块" value={summary.inflow_sector_count} unit="个" icon={<ThunderboltOutlined />} accentColor="var(--color-up)" />
        <StatCard title="流入涨停" value={summary.inflow_limit_count} unit="家" icon={<RiseOutlined />} accentColor="var(--color-up)" />
        <StatCard title="最高连板" value={summary.max_up_streak} unit="板" icon={<FireOutlined />} accentColor="var(--color-warn)" />
        <StatCard title="流出板块" value={summary.outflow_sector_count} unit="个" icon={<FallOutlined />} accentColor="var(--color-down)" />
        <StatCard title="流出跌停" value={summary.outflow_limit_count} unit="家" icon={<WarningOutlined />} accentColor="var(--color-down)" />
        <StatCard title="最高连跌" value={summary.max_down_streak} unit="板" icon={<FallOutlined />} accentColor="var(--color-down)" />
      </div>

      <div className="glow-card" style={{ padding: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <span style={{ fontWeight: 700 }}>净流向情绪</span>
          <span className={`mono ${summary.net_limit_count >= 0 ? 'up' : 'down'}`}>
            {summary.net_limit_count >= 0 ? '+' : ''}{summary.net_limit_count}（涨停-跌停）
          </span>
        </div>
        <Progress
          percent={netPct}
          showInfo={false}
          strokeColor={summary.net_limit_count >= 0 ? 'var(--color-up)' : 'var(--color-down)'}
          trailColor="var(--bg-card-hover)"
        />
        <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-muted)' }}>
          流入 {summary.inflow_limit_count} / 流出 {summary.outflow_limit_count}
          {summary.flow_ratio != null ? ` · 强弱比 ${summary.flow_ratio}` : ''}
          · 绝对净差 {netAbs}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div className="glow-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <ThunderboltOutlined style={{ color: 'var(--color-up)' }} />
            <span style={{ fontWeight: 700 }}>资金流入板块（涨停）</span>
          </div>
          <Table
            dataSource={inflowSectors}
            columns={inflowColumns}
            rowKey={(r) => `${r.name}-${r.rank ?? ''}`}
            pagination={false}
            size="small"
            scroll={{ x: 640 }}
            locale={{ emptyText: <span style={{ color: 'var(--text-muted)' }}>暂无流入数据</span> }}
          />
        </div>

        <div className="glow-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <FallOutlined style={{ color: 'var(--color-down)' }} />
            <span style={{ fontWeight: 700 }}>资金流出板块（跌停）</span>
          </div>
          <Table
            dataSource={outflowSectors}
            columns={outflowColumns}
            rowKey={(r) => `${r.name}-${r.rank ?? ''}`}
            pagination={false}
            size="small"
            scroll={{ x: 560 }}
            locale={{ emptyText: <span style={{ color: 'var(--text-muted)' }}>暂无流出数据</span> }}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <LadderTags
          title="连板梯队（资金进攻）"
          icon={<FireOutlined />}
          data={inflowLadder}
          tone="up"
          onGoStock={(tsCode) => navigate(`/stocks/${tsCode}`)}
        />
        <LadderTags
          title="连跌梯队（资金撤退）"
          icon={<FallOutlined />}
          data={outflowLadder}
          tone="down"
          onGoStock={(tsCode) => navigate(`/stocks/${tsCode}`)}
        />
      </div>
    </div>
  )
}

export default Dashboard

