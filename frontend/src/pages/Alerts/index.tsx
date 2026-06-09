import React, { useCallback, useEffect, useState } from 'react'
import {
  Card,
  Table,
  Tag,
  Tabs,
  Space,
  Button,
  Popconfirm,
  message,
  Empty,
  Alert as AntAlert,
  Tooltip,
  Typography,
} from 'antd'
import { StarFilled, StarOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  listAlerts,
  updateAlert,
  batchDismissPendingAlerts,
  batchDeleteDismissedAlerts,
} from '../../api/alerts'
import { getCoreWatchCodes, toggleCoreWatch } from '../../api/pools'
import type { Alert } from '../../types'
import { openStockDetail } from '../../utils/openStockDetail'

const LS_TIP = 'buyAlert:iaTipDismissed'
const ALERTS_CHANGED_EVENT = 'buy-alerts:changed'

const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'orange' },
  processed: { label: '已处理', color: 'green' },
  dismissed: { label: '已忽略', color: 'default' },
}

const Alerts: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('pending')
  const [page, setPage] = useState(1)
  const [showTip, setShowTip] = useState(() => localStorage.getItem(LS_TIP) !== '1')
  const [coreWatchCodes, setCoreWatchCodes] = useState<Set<string>>(new Set())
  const [coreWatchBusyTsCode, setCoreWatchBusyTsCode] = useState<string | null>(null)
  const navigate = useNavigate()

  const requestAlerts = useCallback((status: string, currentPage: number) => {
    listAlerts({ status, page: currentPage, size: 20, source: 'buy_radar' })
      .then((res) => {
        setAlerts(res.data.items)
        setTotal(res.data.total)
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    requestAlerts(tab, page)
  }, [page, requestAlerts, tab])

  useEffect(() => {
    getCoreWatchCodes()
      .then((res) => setCoreWatchCodes(new Set(res.data.ts_codes || [])))
      .catch(() => {})
  }, [])

  const refreshAlerts = useCallback((status = tab, currentPage = page) => {
    setLoading(true)
    requestAlerts(status, currentPage)
  }, [page, requestAlerts, tab])

  const handleTabChange = (nextTab: string) => {
    setLoading(true)
    setTab(nextTab)
    setPage(1)
  }

  const handlePageChange = (nextPage: number) => {
    setLoading(true)
    setPage(nextPage)
  }

  const dismissTip = () => {
    localStorage.setItem(LS_TIP, '1')
    setShowTip(false)
  }

  const notifyAlertsChanged = () => {
    window.dispatchEvent(new Event(ALERTS_CHANGED_EVENT))
  }

  const handleDismiss = async (id: string) => {
    await updateAlert(id, { status: 'dismissed' })
    message.success('已忽略')
    notifyAlertsChanged()
    refreshAlerts()
  }

  const handleToggleCoreWatch = async (r: Alert) => {
    if (!r.ts_code || coreWatchBusyTsCode) return
    const starred = coreWatchCodes.has(r.ts_code)
    setCoreWatchBusyTsCode(r.ts_code)
    try {
      await toggleCoreWatch({
        ts_code: r.ts_code,
        starred: !starred,
        limit_up_date: r.buy_signal?.life_line_date || undefined,
        source: 'buy_alert',
      })
      setCoreWatchCodes((prev) => {
        const next = new Set(prev)
        if (starred) next.delete(r.ts_code)
        else next.add(r.ts_code)
        return next
      })
      message.success(starred ? '已取消特别关注' : '已加入「核心关注」股票池')
    } catch {
      message.error('标星失败，请稍后重试')
    } finally {
      setCoreWatchBusyTsCode(null)
    }
  }

  const handleBatchDismiss = async () => {
    const res = await batchDismissPendingAlerts({ source: 'buy_radar' })
    message.success(`已忽略 ${res.data.count} 条待处理提醒`)
    notifyAlertsChanged()
    refreshAlerts()
  }

  const handleBatchDelete = async () => {
    const res = await batchDeleteDismissedAlerts({ source: 'buy_radar' })
    message.success(`已删除 ${res.data.count} 条已忽略记录`)
    refreshAlerts()
  }

  const riskSummary = (r: Alert) => {
    const s = r.buy_signal
    if (!s) return '-'
    const parts: string[] = []
    if (s.stop_loss_price != null) parts.push(`止损 ${s.stop_loss_price}`)
    if (s.target_price != null) parts.push(`目标 ${s.target_price}`)
    if (s.risk_reward_ratio != null) parts.push(`盈亏比 ${s.risk_reward_ratio}`)
    return parts.length ? parts.join(' / ') : '-'
  }

  const metSummary = (r: Alert) => {
    const m = r.buy_signal?.met_conditions as string[] | undefined
    if (!m?.length) return '-'
    const short = m.slice(0, 3).join('；')
    const full = m.join('；')
    return (
      <Tooltip title={full}>
        <span style={{ cursor: 'help' }}>
          {short}
          {m.length > 3 ? '…' : ''}
        </span>
      </Tooltip>
    )
  }

  const columns = [
    {
      title: '代码',
      dataIndex: 'ts_code',
      key: 'ts_code',
      width: 110,
      render: (v: string) => (
        <Typography.Link onClick={() => openStockDetail(v)}>{v}</Typography.Link>
      ),
    },
    {
      title: '名称',
      dataIndex: 'stock_name',
      key: 'stock_name',
      width: 100,
      render: (v: string, r: Alert) => (
        <Typography.Link onClick={() => openStockDetail(r.ts_code)}>{v || '-'}</Typography.Link>
      ),
    },
    {
      title: '触发价格',
      key: 'trigger_price',
      width: 100,
      align: 'right' as const,
      render: (_: unknown, r: Alert) => {
        const val = r.buy_signal?.latest_close;
        const pct = r.buy_signal?.latest_pct_chg;
        if (val == null) return '-';
        if (pct == null) return (val as number).toFixed(2);
        const color = pct >= 0 ? '#cf1322' : '#3f8600';
        return (
          <Space direction="vertical" size={0} style={{ width: '100%', textAlign: 'right' }}>
            <span style={{ fontWeight: 500 }}>{(val as number).toFixed(2)}</span>
            <span style={{ color, fontSize: 12 }}>{pct >= 0 ? '+' : ''}{pct.toFixed(2)}%</span>
          </Space>
        );
      },
    },
    {
      title: '最新价',
      key: 'latest_price',
      width: 100,
      align: 'right' as const,
      render: (_: unknown, r: Alert) => {
        const price = r.latest_price;
        const pct = r.pct_chg;
        if (price == null) return '-';
        if (pct == null) return price.toFixed(2);
        const color = pct >= 0 ? '#cf1322' : '#3f8600';
        return (
          <Space direction="vertical" size={0} style={{ width: '100%', textAlign: 'right' }}>
            <span style={{ color, fontWeight: 500 }}>{price.toFixed(2)}</span>
            <span style={{ color, fontSize: 12 }}>{pct >= 0 ? '+' : ''}{pct.toFixed(2)}%</span>
          </Space>
        );
      },
    },
    {
      title: '所属行业',
      key: 'industry',
      width: 100,
      ellipsis: true,
      render: (_: unknown, r: Alert) => r.industry || r.buy_signal?.industry || '-',
    },
    {
      title: '策略',
      key: 'strategy',
      width: 120,
      render: (_: unknown, r: Alert) => r.strategy_name || r.template_name || '-',
    },
    {
      title: '评分',
      key: 'score',
      width: 72,
      render: (_: unknown, r: Alert) =>
        r.buy_signal?.signal_score != null ? r.buy_signal.signal_score : '-',
    },
    { title: '触发日', dataIndex: 'trigger_date', key: 'trigger_date', width: 100 },
    {
      title: '已满足条件',
      key: 'met',
      ellipsis: true,
      render: (_: unknown, r: Alert) => metSummary(r),
    },
    {
      title: '风控摘要',
      key: 'risk',
      width: 200,
      ellipsis: true,
      render: (_: unknown, r: Alert) => riskSummary(r),
    },
    {
      title: '盘中',
      key: 'intraday',
      width: 72,
      render: (_: unknown, r: Alert) =>
        r.scan_meta?.intraday_provisional ? <Tag color="blue">盘中</Tag> : <span>—</span>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 88,
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, r: Alert) => {
        const starred = coreWatchCodes.has(r.ts_code)
        const busy = coreWatchBusyTsCode === r.ts_code
        return (
          <Space size={6}>
            <Tooltip title={starred ? '取消特别关注' : '加入核心关注'}>
              <Button
                size="small"
                type="text"
                loading={busy}
                icon={starred ? <StarFilled style={{ color: '#faad14' }} /> : <StarOutlined />}
                onClick={() => handleToggleCoreWatch(r)}
              />
            </Tooltip>
            {r.status === 'pending' && (
            <Popconfirm title="确定忽略？" onConfirm={() => handleDismiss(r.id)}>
              <Button size="small">忽略</Button>
            </Popconfirm>
            )}
          </Space>
        )
      },
    },
  ]

  const emptyDescription =
    tab === 'pending' ? '暂无已触发记录，请先在买点雷达扫描' : '暂无提醒'

  return (
    <Card
      title="买点提醒"
      extra={
        <Space>
          {tab === 'pending' && (
            <Popconfirm
              title="将忽略所有待处理的买点提醒（不限当前页），确定？"
              onConfirm={handleBatchDismiss}
            >
              <Button disabled={total === 0}>一键忽略全部</Button>
            </Popconfirm>
          )}
          {tab === 'dismissed' && (
            <Popconfirm
              title="将永久删除所有已忽略的买点提醒记录，确定？"
              onConfirm={handleBatchDelete}
            >
              <Button danger disabled={total === 0}>
                一键删除已忽略
              </Button>
            </Popconfirm>
          )}
        </Space>
      }
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        以下列表由买点雷达扫描产生：当某只股票在某一策略下判定为买点「已触发」时会出现在此。
      </Typography.Paragraph>
      {showTip && (
        <AntAlert
          type="info"
          showIcon
          closable
          onClose={dismissTip}
          style={{ marginBottom: 16 }}
          message="处理触发记录"
          description={
            <Space direction="vertical" size="small">
              <span>点击股票名称或代码可进入个股页查看 K 线与深度分析。</span>
              <Button type="primary" size="small" onClick={() => navigate('/buy-radar')}>
                去买点雷达
              </Button>
            </Space>
          }
        />
      )}
      <Tabs
        activeKey={tab}
        onChange={handleTabChange}
        items={[
          { key: 'pending', label: '待处理' },
          { key: 'processed', label: '已处理' },
          { key: 'dismissed', label: '已忽略' },
        ]}
      />
      <Table
        dataSource={alerts}
        columns={columns}
        rowKey="id"
        loading={loading}
        scroll={{ x: 1200 }}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: handlePageChange,
        }}
        locale={{
          emptyText:
            tab === 'pending' ? (
              <Empty description={emptyDescription}>
                <Button type="primary" onClick={() => navigate('/buy-radar')}>
                  去买点雷达
                </Button>
              </Empty>
            ) : (
              <Empty description={emptyDescription} />
            ),
        }}
      />
    </Card>
  )
}

export default Alerts
