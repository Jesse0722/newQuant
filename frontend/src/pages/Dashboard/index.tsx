import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Spin, Table, Tag, Tooltip, Progress, Popover, Empty } from 'antd'
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
import type {
  DashboardData,
  DashboardFlowSectorRow,
  DashboardLimitLadderRow,
  DashboardSectorStock,
  DashboardThsHotSector,
  DashboardThsHotStock,
} from '../../types'
import StatCard from '../../components/StatCard'
import { openStockDetail } from '../../utils/openStockDetail'

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

const LadderTags: React.FC<{
  title: string
  icon: React.ReactNode
  data: DashboardLimitLadderRow[]
  tone: 'up' | 'down'
  onGoStock: (tsCode: string) => void
}> = ({ title, icon, data, tone, onGoStock }) => {
  const groups = useMemo(() => {
    const sorted = [...data].sort((a, b) => {
      const an = Number.parseInt(String(a.nums ?? '0'), 10) || 0
      const bn = Number.parseInt(String(b.nums ?? '0'), 10) || 0
      if (bn !== an) return bn - an
      return String(a.ts_code || '').localeCompare(String(b.ts_code || ''))
    })
    const m = new Map<number, DashboardLimitLadderRow[]>()
    sorted.forEach((row) => {
      const n = Number.parseInt(String(row.nums ?? '0'), 10) || 0
      const key = n > 0 ? n : 1
      m.set(key, [...(m.get(key) ?? []), row])
    })
    return Array.from(m.entries()).map(([nums, rows]) => ({ nums, rows }))
  }, [data])
  const toneColor = tone === 'up' ? 'var(--color-up)' : 'var(--color-down)'
  const toneBg = tone === 'up' ? 'var(--color-up-dim)' : 'var(--color-down-dim)'
  return (
    <div className="glow-card" style={{ padding: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: toneColor }}>{icon}</span>
          <span style={{ fontWeight: 700 }}>{title}</span>
        </div>
        <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12 }}>{data.length}家</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxHeight: 420, overflowY: 'auto', paddingRight: 4 }}>
        {groups.length === 0 && <span style={{ color: 'var(--text-muted)' }}>暂无数据</span>}
        {groups.map((group) => (
          <div key={group.nums} style={{ display: 'grid', gridTemplateColumns: '64px 1fr', gap: 10, alignItems: 'start' }}>
            <div
              className="mono"
              style={{
                position: 'sticky',
                top: 0,
                color: toneColor,
                fontWeight: 700,
                lineHeight: '24px',
              }}
            >
              {group.nums}板
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {group.rows.map((x) => (
                <Tooltip key={`${x.ts_code}-${x.trade_date}`} title={[x.ts_code, x.industry].filter(Boolean).join(' · ')}>
                  <Tag
                    style={{
                      cursor: 'pointer',
                      border: 'none',
                      background: toneBg,
                      color: toneColor,
                      fontFamily: 'var(--font-mono)',
                      paddingInline: 8,
                      marginInlineEnd: 0,
                    }}
                    onClick={() => onGoStock(x.ts_code)}
                  >
                    {x.name}
                  </Tag>
                </Tooltip>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const SectorStockTags: React.FC<{
  stocks?: DashboardSectorStock[]
  tone: 'up' | 'down'
  onGoStock: (tsCode: string) => void
}> = ({ stocks = [], tone, onGoStock }) => {
  if (stocks.length === 0) return <span style={{ color: 'var(--text-muted)' }}>-</span>
  const toneColor = tone === 'up' ? 'var(--color-up)' : 'var(--color-down)'
  const toneBg = tone === 'up' ? 'var(--color-up-dim)' : 'var(--color-down-dim)'
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
      {stocks.map((stock) => (
        <Tooltip key={`${stock.ts_code}-${stock.name}`} title={stock.ts_code || undefined}>
          <Tag
            style={{
              cursor: stock.ts_code ? 'pointer' : 'default',
              border: 'none',
              background: toneBg,
              color: toneColor,
              marginInlineEnd: 0,
              maxWidth: 110,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
            onClick={() => stock.ts_code && onGoStock(stock.ts_code)}
          >
            {stock.name || stock.ts_code}
          </Tag>
        </Tooltip>
      ))}
    </div>
  )
}

const HotValue: React.FC<{ value?: number | null }> = ({ value }) => {
  if (value == null || Number.isNaN(value)) return <span style={{ color: 'var(--text-muted)' }}>-</span>
  if (value >= 10000) return <span className="mono">{(value / 10000).toFixed(1)}万</span>
  return <span className="mono">{Math.round(value).toLocaleString()}</span>
}

const PctValue: React.FC<{ value?: number | null }> = ({ value }) => {
  if (value == null || Number.isNaN(value)) return <span style={{ color: 'var(--text-muted)' }}>-</span>
  return <span className={value >= 0 ? 'up mono' : 'down mono'}>{value >= 0 ? '+' : ''}{value.toFixed(2)}%</span>
}

type HotSectorLinkedStock = DashboardSectorStock & {
  source: 'limit' | 'hot'
  pct_chg?: number | null
  tag?: string | null
}

const normalizeSectorName = (value?: string | null) =>
  String(value || '')
    .replace(/\s+/g, '')
    .replace(/[（）]/g, (m) => (m === '（' ? '(' : ')'))
    .toLowerCase()

const Dashboard: React.FC = () => {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null)

  const requestDashboard = useCallback((forceRefresh = false) => {
    getDashboard(undefined, { forceRefresh })
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
  const topInflowSectors = useMemo(() => inflowSectors.slice(0, 5), [inflowSectors])
  const topOutflowSectors = useMemo(() => outflowSectors.slice(0, 5), [outflowSectors])
  const thsHotStocks: DashboardThsHotStock[] = useMemo(() => data?.ths_hot?.stocks ?? [], [data])
  const thsHotSectors: DashboardThsHotSector[] = useMemo(() => data?.ths_hot?.sectors ?? [], [data])

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
  const outflowSourceLabel = summary.outflow_source === 'tushare.limit_list_d'
    ? 'Tushare 跌停清单'
    : summary.outflow_source === 'akshare.pool'
      ? 'AkShare 跌停池'
      : summary.outflow_source === 'derived.daily'
        ? '日线推断'
        : '未知'

  const getHotSectorLinkedStocks = useCallback((row: DashboardThsHotSector): HotSectorLinkedStock[] => {
    const targetName = normalizeSectorName(row.name)
    const linked = new Map<string, HotSectorLinkedStock>()
    const addStock = (stock: HotSectorLinkedStock) => {
      const key = stock.ts_code || stock.name
      if (!key || linked.has(key)) return
      linked.set(key, stock)
    }

    inflowSectors
      .filter((sector) => normalizeSectorName(sector.name) === targetName)
      .flatMap((sector) => sector.stocks || [])
      .forEach((stock) => addStock({ ...stock, source: 'limit' }))

    thsHotStocks
      .filter((stock) => {
        const tags = stock.concept_tags || []
        return tags.some((tag) => {
          const normalizedTag = normalizeSectorName(tag)
          return normalizedTag === targetName || normalizedTag.includes(targetName) || targetName.includes(normalizedTag)
        })
      })
      .forEach((stock) => addStock({
        ts_code: stock.ts_code,
        name: stock.name || stock.ts_code || stock.code,
        source: 'hot',
        pct_chg: stock.pct_chg,
        tag: stock.popularity_tag,
      }))

    return Array.from(linked.values())
  }, [inflowSectors, thsHotStocks])

  const renderHotSectorStatusTag = useCallback((row: DashboardThsHotSector) => {
    if (!row.tag) return null
    const linkedStocks = getHotSectorLinkedStocks(row)
    const limitStocks = linkedStocks.filter((stock) => stock.source === 'limit')
    const hotStocks = linkedStocks.filter((stock) => stock.source === 'hot')
    const content = (
      <div style={{ width: 320, maxWidth: '70vw' }}>
        <div style={{ fontWeight: 700, marginBottom: 8 }}>{row.name} · {row.tag}</div>
        {limitStocks.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>涨停明细</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {limitStocks.map((stock) => (
                <Tag
                  key={`limit-${stock.ts_code || stock.name}`}
                  color="red"
                  style={{ cursor: stock.ts_code ? 'pointer' : 'default', marginInlineEnd: 0 }}
                  onClick={() => stock.ts_code && openStockDetail(stock.ts_code)}
                >
                  {stock.name || stock.ts_code}
                </Tag>
              ))}
            </div>
          </div>
        )}
        {hotStocks.length > 0 && (
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 6 }}>
              同花顺热股关联
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {hotStocks.map((stock) => (
                <Tooltip
                  key={`hot-${stock.ts_code || stock.name}`}
                  title={[stock.ts_code, stock.tag, stock.pct_chg != null ? `${stock.pct_chg.toFixed(2)}%` : null].filter(Boolean).join(' · ')}
                >
                  <Tag
                    style={{ cursor: stock.ts_code ? 'pointer' : 'default', marginInlineEnd: 0 }}
                    onClick={() => stock.ts_code && openStockDetail(stock.ts_code)}
                  >
                    {stock.name || stock.ts_code}
                  </Tag>
                </Tooltip>
              ))}
            </div>
          </div>
        )}
        {linkedStocks.length === 0 && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无股票明细" />
        )}
        <div style={{ color: 'var(--text-muted)', fontSize: 12, marginTop: 10 }}>
          热榜接口不提供完整涨停成分；这里展示当前可关联到的股票。
        </div>
      </div>
    )
    return (
      <Popover content={content} trigger="click" placement="leftTop">
        <Tag color="red" style={{ marginInlineEnd: 0, cursor: 'pointer' }}>{row.tag}</Tag>
      </Popover>
    )
  }, [getHotSectorLinkedStocks])

  const inflowColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58 },
    { title: '流入板块', dataIndex: 'name', key: 'name', width: 140 },
    { title: <Tooltip title="当日该板块涨停股票数量"><span>涨停家数</span></Tooltip>, dataIndex: 'up_nums', key: 'up_nums', width: 90, render: (v?: number | null) => <span className="up mono">{v ?? '-'}</span> },
    {
      title: '具体股票',
      dataIndex: 'stocks',
      key: 'stocks',
      render: (stocks?: DashboardSectorStock[]) => (
        <SectorStockTags stocks={stocks} tone="up" onGoStock={openStockDetail} />
      ),
    },
  ]

  const outflowColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58 },
    { title: '流出板块', dataIndex: 'name', key: 'name', width: 140 },
    { title: <Tooltip title="当日该板块跌停股票数量"><span>跌停家数</span></Tooltip>, dataIndex: 'down_nums', key: 'down_nums', width: 90, render: (v?: number | null) => <span className="down mono">{v ?? '-'}</span> },
    {
      title: '具体股票',
      dataIndex: 'stocks',
      key: 'stocks',
      render: (stocks?: DashboardSectorStock[]) => (
        <SectorStockTags stocks={stocks} tone="down" onGoStock={openStockDetail} />
      ),
    },
  ]

  const thsHotStockColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58, render: (v?: number) => <span className="mono">{v ?? '-'}</span> },
    {
      title: '个股',
      dataIndex: 'name',
      key: 'name',
      width: 132,
      render: (_: string, row: DashboardThsHotStock) => (
        <Tooltip title={row.ts_code || row.code || undefined}>
          <span
            style={{ cursor: row.ts_code ? 'pointer' : 'default', fontWeight: 600 }}
            onClick={() => row.ts_code && openStockDetail(row.ts_code)}
          >
            {row.name}
          </span>
        </Tooltip>
      ),
    },
    { title: '热度', dataIndex: 'hot', key: 'hot', width: 86, render: (v?: number | null) => <HotValue value={v} /> },
    { title: '涨跌幅', dataIndex: 'pct_chg', key: 'pct_chg', width: 82, render: (v?: number | null) => <PctValue value={v} /> },
    {
      title: '标签',
      dataIndex: 'concept_tags',
      key: 'concept_tags',
      render: (tags?: string[], row?: DashboardThsHotStock) => (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {row?.popularity_tag && <Tag color="volcano" style={{ marginInlineEnd: 0 }}>{row.popularity_tag}</Tag>}
          {(tags ?? []).slice(0, 2).map((tag) => <Tag key={tag} style={{ marginInlineEnd: 0 }}>{tag}</Tag>)}
        </div>
      ),
    },
  ]

  const thsHotSectorColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 58, render: (v?: number) => <span className="mono">{v ?? '-'}</span> },
    {
      title: '板块',
      dataIndex: 'name',
      key: 'name',
      width: 136,
      render: (v: string, row: DashboardThsHotSector) => (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontWeight: 600 }}>{v}</span>
          <Tag color={row.type === 'concept' ? 'blue' : 'cyan'} style={{ marginInlineEnd: 0 }}>{row.type_label || row.type}</Tag>
        </div>
      ),
    },
    { title: '热度', dataIndex: 'hot', key: 'hot', width: 86, render: (v?: number | null) => <HotValue value={v} /> },
    { title: '涨跌幅', dataIndex: 'pct_chg', key: 'pct_chg', width: 82, render: (v?: number | null) => <PctValue value={v} /> },
    {
      title: '状态',
      key: 'tags',
      render: (_: unknown, row: DashboardThsHotSector) => (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {renderHotSectorStatusTag(row)}
          {row.hot_tag && <Tag style={{ marginInlineEnd: 0 }}>{row.hot_tag}</Tag>}
        </div>
      ),
    },
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
        <Button style={{ marginTop: 16 }} type="primary" onClick={() => { setLoading(true); requestDashboard(true) }} icon={<ReloadOutlined />}>重试</Button>
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
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            跌停数据源：<span style={{ color: 'var(--text-secondary)' }}>{outflowSourceLabel}</span>
            <Tooltip title="优先 Tushare，失败回退 AkShare，再回退日线推断。">
              <span style={{ marginLeft: 6, color: 'var(--accent)', cursor: 'help' }}>口径说明</span>
            </Tooltip>
          </div>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => { setLoading(true); requestDashboard(true) }}
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
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <FireOutlined style={{ color: 'var(--color-warn)' }} />
              <span style={{ fontWeight: 700 }}>同花顺人气排名 Top 100</span>
            </div>
            <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12 }}>{thsHotStocks.length}只</span>
          </div>
          <Table
            dataSource={thsHotStocks}
            columns={thsHotStockColumns}
            rowKey={(r) => `${r.rank}-${r.ts_code || r.code}`}
            pagination={false}
            size="small"
            scroll={{ x: 620, y: 360 }}
            locale={{ emptyText: <span style={{ color: 'var(--text-muted)' }}>{data?.ths_hot?.error || '暂无人气数据'}</span> }}
          />
        </div>

        <div className="glow-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ThunderboltOutlined style={{ color: 'var(--accent)' }} />
              <span style={{ fontWeight: 700 }}>同花顺热门板块 Top 20</span>
            </div>
            <span className="mono" style={{ color: 'var(--text-muted)', fontSize: 12 }}>概念+行业</span>
          </div>
          <Table
            dataSource={thsHotSectors}
            columns={thsHotSectorColumns}
            rowKey={(r) => `${r.type}-${r.code}-${r.rank}`}
            pagination={false}
            size="small"
            scroll={{ x: 620, y: 360 }}
            locale={{ emptyText: <span style={{ color: 'var(--text-muted)' }}>{data?.ths_hot?.error || '暂无板块热榜'}</span> }}
          />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div className="glow-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <ThunderboltOutlined style={{ color: 'var(--color-up)' }} />
            <span style={{ fontWeight: 700 }}>资金流入最强板块 Top 5</span>
          </div>
          <Table
            dataSource={topInflowSectors}
            columns={inflowColumns}
            rowKey={(r) => `${r.name}-${r.rank ?? ''}`}
            pagination={false}
            size="small"
            scroll={{ x: 660 }}
            locale={{ emptyText: <span style={{ color: 'var(--text-muted)' }}>暂无流入数据</span> }}
          />
        </div>

        <div className="glow-card" style={{ padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
            <FallOutlined style={{ color: 'var(--color-down)' }} />
            <span style={{ fontWeight: 700 }}>资金流出最弱板块 Top 5</span>
          </div>
          <Table
            dataSource={topOutflowSectors}
            columns={outflowColumns}
            rowKey={(r) => `${r.name}-${r.rank ?? ''}`}
            pagination={false}
            size="small"
            scroll={{ x: 660 }}
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
          onGoStock={openStockDetail}
        />
        <LadderTags
          title="连跌梯队（资金撤退）"
          icon={<FallOutlined />}
          data={outflowLadder}
          tone="down"
          onGoStock={openStockDetail}
        />
      </div>
    </div>
  )
}

export default Dashboard
