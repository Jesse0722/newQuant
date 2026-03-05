import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Button, Progress, message, Spin } from 'antd'
import { SyncOutlined } from '@ant-design/icons'
import { getDataSummary } from '../../api/data'
import { syncFullMarket, getTaskStatus } from '../../api/sync'
import type { DataSummary } from '../../types'

const DataPage: React.FC = () => {
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState(0)
  const [taskMessage, setTaskMessage] = useState('')
  const [taskResult, setTaskResult] = useState<{
    success_count?: number
    failed_count?: number
    skipped_count?: number
    days_synced?: number
    message?: string
  } | null>(null)

  const fetchSummary = async () => {
    setLoading(true)
    try {
      const res = await getDataSummary()
      setSummary(res.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSummary()
  }, [])

  useEffect(() => {
    if (!taskId) return
    const poll = setInterval(async () => {
      try {
        const res = await getTaskStatus(taskId)
        setTaskProgress(res.data.progress)
        setTaskMessage(res.data.message || '')
        if (res.data.result) {
          setTaskResult(res.data.result)
        }
        if (res.data.status === 'completed' || res.data.status === 'failed') {
          clearInterval(poll)
          setSyncing(false)
          setTaskId(null)
          if (res.data.status === 'completed') {
            message.success('全市场同步完成')
          } else {
            message.error(res.data.message || '同步失败')
          }
          fetchSummary()
        }
      } catch {
        clearInterval(poll)
        setSyncing(false)
        setTaskId(null)
      }
    }, 1500)
    return () => clearInterval(poll)
  }, [taskId])

  const handleFullMarketSync = async () => {
    setSyncing(true)
    setTaskResult(null)
    try {
      const res = await syncFullMarket(60)
      setTaskId(res.data.task_id)
    } catch (e: any) {
      setSyncing(false)
      message.error(e.response?.data?.message || '启动同步失败')
    }
  }

  const range = summary?.quote_date_range
  const rangeStr = range?.min && range?.max ? `${range.min} ~ ${range.max}` : '-'

  return (
    <div>
      <Card
        title="数据管理"
        extra={
          <Button
            type="primary"
            icon={<SyncOutlined spin={syncing} />}
            loading={syncing}
            onClick={handleFullMarketSync}
            disabled={syncing}
          >
            全市场 60 日同步
          </Button>
        }
      >
        <Spin spinning={loading}>
        <Descriptions column={1} bordered size="small" style={{ maxWidth: 480 }}>
          <Descriptions.Item label="股票数量">{summary?.stock_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="行情条数">{summary?.total_quotes?.toLocaleString() ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="日期范围">{rangeStr}</Descriptions.Item>
          <Descriptions.Item label="最新数据日期">{summary?.last_sync_at ?? '-'}</Descriptions.Item>
        </Descriptions>
        </Spin>

        {syncing && (
          <div style={{ marginTop: 24 }}>
            <Progress percent={Math.round(taskProgress * 100)} status="active" />
            <p style={{ color: '#666', marginTop: 8 }}>{taskMessage}</p>
          </div>
        )}

        {taskResult && !syncing && (
          <div style={{ marginTop: 24, padding: 16, background: '#f5f5f5', borderRadius: 8 }}>
            <h4>同步结果</h4>
            <p>成功：{taskResult.success_count?.toLocaleString() ?? 0} 条</p>
            <p>跳过（已存在）：{taskResult.skipped_count?.toLocaleString() ?? 0} 条</p>
            <p>失败天数：{taskResult.failed_count ?? 0} 天</p>
            <p>同步交易日：{taskResult.days_synced ?? 0} 天</p>
          </div>
        )}
      </Card>
    </div>
  )
}

export default DataPage
