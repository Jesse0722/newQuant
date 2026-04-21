import React, { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Space, Spin, Table, Typography } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import axios from 'axios'
import { getDashboard } from '../../api/dashboard'
import type { DashboardData } from '../../types'

function parseDashboardError(err: unknown): { message: string; hint?: string } {
  if (axios.isAxiosError(err)) {
    const raw = err.response?.data as { detail?: unknown } | undefined
    const d = raw?.detail
    if (d && typeof d === 'object' && d !== null && 'message' in d) {
      const o = d as { message?: string; hint?: string }
      return {
        message: String(o.message ?? '请求失败'),
        hint: o.hint ? String(o.hint) : undefined,
      }
    }
    if (err.message) return { message: err.message }
  }
  if (err instanceof Error) return { message: err.message }
  return { message: '加载失败' }
}

const Dashboard: React.FC = () => {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<{ message: string; hint?: string } | null>(null)

  const requestDashboard = useCallback(() => {
    getDashboard()
      .then((res) => {
        setData(res.data)
        setError(null)
      })
      .catch((e) => {
        setData(null)
        setError(parseDashboardError(e))
      })
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    requestDashboard()
  }, [requestDashboard])

  const handleRefresh = () => {
    setLoading(true)
    setError(null)
    requestDashboard()
  }

  const sectorColumns = [
    { title: '排名', dataIndex: 'rank', key: 'rank', width: 72 },
    { title: '板块', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120 },
    { title: '涨停家数', dataIndex: 'up_nums', key: 'up_nums', width: 96 },
    { title: '连板家数', dataIndex: 'cons_nums', key: 'cons_nums', width: 96 },
    { title: '涨跌幅%', dataIndex: 'pct_chg', key: 'pct_chg', width: 96 },
    { title: '连板高度', dataIndex: 'up_stat', key: 'up_stat', ellipsis: true },
    { title: '上榜天数', dataIndex: 'days', key: 'days', width: 88 },
  ]

  const ladderColumns = [
    { title: '连板', dataIndex: 'nums', key: 'nums', width: 72 },
    { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
    { title: '代码', dataIndex: 'ts_code', key: 'ts_code', width: 120 },
  ]

  if (loading && !data && !error) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <Alert
          type="error"
          showIcon
          message={error.message}
          description={error.hint}
        />
        <div style={{ marginTop: 16 }}>
          <Button type="primary" onClick={handleRefresh}>
            重试
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        <Space align="center" wrap style={{ justifyContent: 'space-between', width: '100%' }}>
          <div>
            <Typography.Title level={4} style={{ margin: 0 }}>
              涨停情绪
            </Typography.Title>
            <Typography.Text type="secondary">
              数据日 {data?.trade_date}{' '}
              {data?.resolved_by === 'query' ? '（指定日期）' : '（默认最近已完成交易日）'}
            </Typography.Text>
          </div>
          <Button icon={<ReloadOutlined />} onClick={handleRefresh} loading={loading}>
            刷新
          </Button>
        </Space>

        <Card title="最强板块（limit_cpt_list）" bordered={false}>
          <Table
            loading={loading}
            dataSource={data?.sectors ?? []}
            columns={sectorColumns}
            rowKey={(r) => `${r.ts_code}-${r.trade_date}`}
            pagination={false}
            size="small"
            scroll={{ x: 900 }}
          />
        </Card>

        <Card title="连板天梯（limit_step）" bordered={false}>
          <Table
            loading={loading}
            dataSource={data?.ladder ?? []}
            columns={ladderColumns}
            rowKey={(r) => `${r.ts_code}-${r.trade_date}`}
            pagination={false}
            size="small"
          />
        </Card>
      </Space>
    </div>
  )
}

export default Dashboard
