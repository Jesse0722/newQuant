import React, { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Table, Tag, Empty, Spin } from 'antd'
import { EyeOutlined, AlertOutlined, FileTextOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getDashboard } from '../../api/dashboard'
import type { DashboardData } from '../../types'

const Dashboard: React.FC = () => {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()

  useEffect(() => {
    getDashboard().then((res) => setData(res.data)).finally(() => setLoading(false))
  }, [])

  const alertColumns = [
    { title: '股票代码', dataIndex: 'ts_code', key: 'ts_code' },
    { title: '股票名称', dataIndex: 'stock_name', key: 'stock_name', render: (v: string) => v || '-' },
    { title: '触发日期', dataIndex: 'trigger_date', key: 'trigger_date' },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={s === 'pending' ? 'orange' : s === 'processed' ? 'green' : 'default'}>
          {s === 'pending' ? '待处理' : s === 'processed' ? '已处理' : '已忽略'}
        </Tag>
      ),
    },
  ]

  const planColumns = [
    { title: '股票', key: 'stock', render: (_: any, r: any) => `${r.stock_name || ''} (${r.ts_code})` },
    {
      title: '类型',
      dataIndex: 'plan_type',
      key: 'plan_type',
      render: (t: string) => ({ trend: '趋势跟踪', short_term: '短线操作', event_driven: '事件驱动' }[t] || t),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (s: string) => (
        <Tag color={s === 'active' ? 'blue' : 'default'}>{s === 'pending' ? '待触发' : '执行中'}</Tag>
      ),
    },
    { title: '盈亏比', dataIndex: 'risk_reward_ratio', key: 'rr', render: (v: number) => v?.toFixed(2) || '-' },
  ]

  const ps = data?.pool_summary

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  return (
    <div>
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={8}>
          <Card hoverable onClick={() => navigate('/pools')}>
            <Statistic title="观察池" value={ps?.total_pools ?? 0} prefix={<EyeOutlined />} suffix="个" />
          </Card>
        </Col>
        <Col span={8}>
          <Card hoverable onClick={() => navigate('/pools')}>
            <Statistic title="监控中股票" value={ps?.monitoring_count ?? 0} prefix={<AlertOutlined />} suffix="只" />
          </Card>
        </Col>
        <Col span={8}>
          <Card hoverable onClick={() => navigate('/plans')}>
            <Statistic title="活跃计划" value={data?.active_plans?.length ?? 0} prefix={<FileTextOutlined />} suffix="个" />
          </Card>
        </Col>
      </Row>

      <Row gutter={16}>
        <Col span={12}>
          <Card title="最新提醒" extra={<a onClick={() => navigate('/alerts')}>查看全部</a>}>
            {data?.recent_alerts?.length ? (
              <Table
                dataSource={data.recent_alerts}
                columns={alertColumns}
                rowKey="id"
                pagination={false}
                size="small"
                onRow={(r) => ({
                  onClick: () => r.plan_id ? navigate(`/plans/${r.plan_id}`) : navigate('/alerts'),
                  style: { cursor: 'pointer' },
                })}
              />
            ) : (
              <Empty description="暂无提醒" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title="活跃计划" extra={<a onClick={() => navigate('/plans')}>查看全部</a>}>
            {data?.active_plans?.length ? (
              <Table dataSource={data.active_plans} columns={planColumns} rowKey="id" pagination={false} size="small"
                onRow={(r) => ({ onClick: () => navigate(`/plans/${r.id}`), style: { cursor: 'pointer' } })} />
            ) : (
              <Empty description="暂无活跃计划" />
            )}
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default Dashboard
