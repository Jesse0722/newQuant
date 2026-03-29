import React, { useEffect, useState } from 'react'
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
import { useNavigate } from 'react-router-dom'
import {
  listAlerts,
  updateAlert,
  createPlanFromAlert,
  batchDismissPendingAlerts,
  batchDeleteDismissedAlerts,
} from '../../api/alerts'
import type { Alert } from '../../types'

const LS_TIP = 'buyAlert:iaTipDismissed'

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
  const navigate = useNavigate()

  const fetchAlerts = (status?: string, p?: number) => {
    setLoading(true)
    listAlerts({ status: status || tab, page: p || page, size: 20, source: 'buy_radar' })
      .then((res) => {
        setAlerts(res.data.items)
        setTotal(res.data.total)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    fetchAlerts(tab, 1)
    setPage(1)
  }, [tab])

  const dismissTip = () => {
    localStorage.setItem(LS_TIP, '1')
    setShowTip(false)
  }

  const handleDismiss = async (id: string) => {
    await updateAlert(id, { status: 'dismissed' })
    message.success('已忽略')
    fetchAlerts()
  }

  const handleCreatePlan = async (id: string) => {
    await createPlanFromAlert(id)
    message.success('交易计划已创建')
    fetchAlerts()
  }

  const handleBatchDismiss = async () => {
    const res = await batchDismissPendingAlerts({ source: 'buy_radar' })
    message.success(`已忽略 ${res.data.count} 条待处理提醒`)
    fetchAlerts()
  }

  const handleBatchDelete = async () => {
    const res = await batchDeleteDismissedAlerts({ source: 'buy_radar' })
    message.success(`已删除 ${res.data.count} 条已忽略记录`)
    fetchAlerts()
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
        <Typography.Link onClick={() => navigate(`/stocks/${v}`)}>{v}</Typography.Link>
      ),
    },
    {
      title: '名称',
      dataIndex: 'stock_name',
      key: 'stock_name',
      width: 100,
      render: (v: string, r: Alert) => (
        <Typography.Link onClick={() => navigate(`/stocks/${r.ts_code}`)}>{v || '-'}</Typography.Link>
      ),
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
      width: 200,
      fixed: 'right' as const,
      render: (_: unknown, r: Alert) =>
        r.status === 'pending' ? (
          <Space>
            <Button size="small" type="primary" onClick={() => handleCreatePlan(r.id)}>
              创建计划
            </Button>
            <Popconfirm title="确定忽略？" onConfirm={() => handleDismiss(r.id)}>
              <Button size="small">忽略</Button>
            </Popconfirm>
          </Space>
        ) : r.plan_id ? (
          <Typography.Link onClick={() => navigate(`/plans?expand=${r.plan_id}`)}>查看计划</Typography.Link>
        ) : null,
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
        onChange={setTab}
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
          onChange: (p) => {
            setPage(p)
            fetchAlerts(tab, p)
          },
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
