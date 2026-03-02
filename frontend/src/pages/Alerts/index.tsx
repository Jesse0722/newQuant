import React, { useEffect, useState } from 'react'
import { Card, Table, Tag, Tabs, Space, Button, Popconfirm, message, Empty } from 'antd'
import { useNavigate } from 'react-router-dom'
import { listAlerts, updateAlert, createPlanFromAlert } from '../../api/alerts'
import { triggerScan } from '../../api/monitor'
import type { Alert } from '../../types'

const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待处理', color: 'orange' },
  processed: { label: '已处理', color: 'green' },
  dismissed: { label: '已忽略', color: 'default' },
}

const Alerts: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [tab, setTab] = useState('pending')
  const [page, setPage] = useState(1)
  const navigate = useNavigate()

  const fetchAlerts = (status?: string, p?: number) => {
    setLoading(true)
    listAlerts({ status: status || tab, page: p || page, size: 20 })
      .then((res) => {
        setAlerts(res.data.items)
        setTotal(res.data.total)
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { fetchAlerts(tab, 1); setPage(1) }, [tab])

  const handleScan = async () => {
    setScanning(true)
    await triggerScan()
    message.success('扫描任务已提交')
    setScanning(false)
    setTimeout(() => fetchAlerts(), 3000)
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

  const columns = [
    { title: '股票代码', dataIndex: 'ts_code', key: 'ts_code' },
    { title: '股票名称', dataIndex: 'stock_name', key: 'stock_name', render: (v: string) => v || '-' },
    { title: '触发策略', dataIndex: 'template_name', key: 'template_name', render: (v: string) => v || '自定义' },
    { title: '触发日期', dataIndex: 'trigger_date', key: 'trigger_date' },
    {
      title: '行情快照',
      dataIndex: 'snapshot',
      key: 'snapshot',
      render: (s: any) => s ? `收:${s.close} 高:${s.high} 低:${s.low}` : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => <Tag color={statusMap[s]?.color}>{statusMap[s]?.label || s}</Tag>,
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, r: Alert) =>
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
          <a onClick={() => navigate(`/plans/${r.plan_id}`)}>查看计划</a>
        ) : null,
    },
  ]

  return (
    <Card
      title="监控提醒"
      extra={
        <Button type="primary" loading={scanning} onClick={handleScan}>
          手动扫描
        </Button>
      }
    >
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
        pagination={{ current: page, total, pageSize: 20, onChange: (p) => { setPage(p); fetchAlerts(tab, p) } }}
        locale={{ emptyText: <Empty description="暂无提醒" /> }}
      />
    </Card>
  )
}

export default Alerts
