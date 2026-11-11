import React, { useEffect, useState } from 'react'
import { Card, Descriptions, Button, Progress, message, Spin, InputNumber, Space, Row, Col, Statistic, Table, Tag, Select } from 'antd'
import { SyncOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { useSearchParams } from 'react-router-dom'
import { pollTask } from '../../services/taskPolling'
import { beginTaskNotification, beginOperationNotification, finishOperationNotification } from '../../services/notificationCenter'
import { getDataSummary, getSyncHistory, checkTushare, getSyncOverview, getDataProvider, setDataProvider } from '../../api/data'
import { syncFullMarket, getTaskStatus } from '../../api/sync'
import { collectLimitUp } from '../../api/strategy'
import type { DataSummary, FullMarketDateResult, SyncHistoryItem, SyncOverview, TaskStatus } from '../../types'

interface ApiErrorLike {
  response?: {
    data?: {
      message?: string
    }
  }
}

const DataPage: React.FC = () => {
  const [searchParams] = useSearchParams()
  const linkedTask = searchParams.get('task')
  const linkedHistory = searchParams.get('history')
  const [summary, setSummary] = useState<DataSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [taskProgress, setTaskProgress] = useState(0)
  const [taskMessage, setTaskMessage] = useState('')
  const [taskResult, setTaskResult] = useState<TaskStatus['result'] | null>(null)
  const [lastSync, setLastSync] = useState<SyncHistoryItem | null>(null)
  const [syncHistory, setSyncHistory] = useState<SyncHistoryItem[]>([])
  const [syncOverview, setSyncOverview] = useState<SyncOverview | null>(null)
  const [limitUpCollecting, setLimitUpCollecting] = useState(false)
  const [limitUpResult, setLimitUpResult] = useState<{
    added: number
    updated: number
    skipped: number
    dates_processed: string[]
  } | null>(null)
  const [fullMarketDays, setFullMarketDays] = useState(5)
  const [limitUpWindowDays, setLimitUpWindowDays] = useState(1)
  const [tushareCheck, setTushareCheck] = useState<{
    token_configured: boolean
    proxy_configured: boolean
    api_test: string
    rows_returned?: number
    data_provider?: 'tencent' | 'baostock' | 'tushare' | 'akshare' | 'composite'
  } | null>(null)
  const [dataProvider, setDataProviderState] = useState<'tencent' | 'baostock' | 'tushare' | 'akshare' | 'composite'>('composite')
  const [switchingProvider, setSwitchingProvider] = useState(false)

  const handleCheckTushare = async () => {
    const notice = beginOperationNotification('数据源连接检查', '/data', 'data_source')
    try {
      const res = await checkTushare()
      setTushareCheck(res.data)
      finishOperationNotification(notice, res.data.api_test === 'ok' ? 'success' : 'error', res.data.api_test || '未返回连接检查结果', res.data)
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      const text = apiError.response?.data?.message || '检查失败'
      message.error(text)
      finishOperationNotification(notice, 'error', text)
    }
  }

  const fetchSummary = async () => {
    setLoading(true)
    try {
      const res = await getDataSummary()
      setSummary(res.data)
    } finally {
      setLoading(false)
    }
  }

  const fetchSyncHistory = async () => {
    try {
      const [historyRes, overviewRes] = await Promise.all([
        getSyncHistory('all', 30),
        getSyncOverview(7),
      ])
      setSyncHistory(historyRes.data || [])
      setSyncOverview(overviewRes.data || null)
      const completed = (historyRes.data || []).find((r) => r.task_type === 'full_market' && (r.status === 'completed' || r.status === 'failed'))
      setLastSync(completed || null)
    } catch {
      setLastSync(null)
      setSyncHistory([])
      setSyncOverview(null)
    }
  }

  const fetchDataProvider = async () => {
    try {
      const res = await getDataProvider()
      setDataProviderState(res.data.provider)
    } catch {
      // noop
    }
  }

  useEffect(() => {
    fetchSummary()
    fetchSyncHistory()
    fetchDataProvider()
  }, [])

  const handleSwitchProvider = async (provider: 'tencent' | 'baostock' | 'tushare' | 'akshare' | 'composite') => {
    setSwitchingProvider(true)
    try {
      await setDataProvider(provider)
      setDataProviderState(provider)
      message.success(`主数据源已切换为 ${provider}`)
      await handleCheckTushare()
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      message.error(apiError.response?.data?.message || '切换数据源失败')
    } finally {
      setSwitchingProvider(false)
    }
  }

  useEffect(() => {
    if (linkedTask) { setTaskId(linkedTask); setSyncing(true) }
  }, [linkedTask])

  useEffect(() => {
    if (!taskId) return
    return pollTask({
      query: async () => (await getTaskStatus(taskId)).data,
      onUpdate: data => {
        setTaskProgress(data.progress)
        setTaskMessage(data.message || '')
        if (data.result) setTaskResult(data.result)
        if (['completed', 'failed', 'cancelled', 'interrupted'].includes(data.status)) {
          setSyncing(false)
          setTaskId(null)
          if (data.status === 'completed') {
            if (data.result?.has_source_warnings || (data.result?.outcome && data.result.outcome !== 'complete')) {
              message.warning(data.message || '历史回补部分完成，请查看结果')
            } else message.success('历史回补处理完成，请核对覆盖情况')
          } else message.error(data.message || '同步失败或中断')
          void fetchSummary()
          void fetchSyncHistory()
        }
      },
      onRetry: () => setTaskMessage('状态查询暂时失败，正在重试；后台同步可能仍在执行'),
    })
  }, [taskId])

  const handleFullMarketSync = async () => {
    setSyncing(true)
    setTaskResult(null)
    try {
      const res = await syncFullMarket(fullMarketDays)
      setTaskId(res.data.task_id)
      beginTaskNotification('sync_task', '全市场历史回补', res.data.task_id, `/data?task=${res.data.task_id}`, { taskType: 'full_market' })
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      setSyncing(false)
      message.error(apiError.response?.data?.message || '启动同步失败')
    }
  }

  const handleLimitUpCollect = async () => {
    setLimitUpCollecting(true)
    setLimitUpResult(null)
    const notice = beginOperationNotification('涨停池采集', '/data')
    try {
      const res = await collectLimitUp({ window_days: limitUpWindowDays })
      setLimitUpResult({
        added: res.data.added,
        updated: res.data.updated,
        skipped: res.data.skipped,
        dates_processed: res.data.dates_processed || [],
      })
      const text = `涨停筛选完成：新增 ${res.data.added} 只，更新 ${res.data.updated} 只`
      message.success(text)
      finishOperationNotification(notice, 'success', text, res.data)
    } catch (error: unknown) {
      const apiError = error as ApiErrorLike
      const text = apiError.response?.data?.message || '涨停筛选失败'
      message.error(text)
      finishOperationNotification(notice, 'error', text)
    } finally {
      setLimitUpCollecting(false)
    }
  }

  const range = summary?.quote_date_range
  const rangeStr = range?.min && range?.max ? `${range.min} ~ ${range.max}` : '-'

  return (
    <div>
      {linkedHistory && <p role="status">执行记录：{linkedHistory}（见下方同步历史）</p>}
      <Card
        title="数据管理"
        extra={
          <Space>
            <Space>
              <span>主数据源</span>
              <Select<'tencent' | 'baostock' | 'tushare' | 'akshare' | 'composite'>
                size="small"
                style={{ width: 140 }}
                value={dataProvider}
                loading={switchingProvider}
                onChange={handleSwitchProvider}
                options={[
                  { value: 'tencent', label: 'tencent' },
                  { value: 'baostock', label: 'baostock' },
                  { value: 'tushare', label: 'tushare' },
                  { value: 'akshare', label: 'akshare' },
                  { value: 'composite', label: 'composite' },
                ]}
              />
            </Space>
            <Button size="small" onClick={handleCheckTushare}>
              检查连接
            </Button>
            <Space>
              <span>同步最近</span>
              <InputNumber
                min={1}
                max={250}
                value={fullMarketDays}
                onChange={(v) => setFullMarketDays(v ?? 5)}
                style={{ width: 80 }}
              />
              <span>个交易日</span>
            </Space>
            <Button
              type="primary"
              icon={<SyncOutlined spin={syncing} />}
              loading={syncing}
              onClick={handleFullMarketSync}
              disabled={syncing}
            >
              全市场同步
            </Button>
          </Space>
        }
      >
        {syncOverview && (
          <Card size="small" title="最近任务总览（可视化）" style={{ marginBottom: 16 }}>
            <Row gutter={12}>
              <Col span={6}><Statistic title="任务数" value={syncOverview.total.tasks} /></Col>
              <Col span={6}><Statistic title="成功条目" value={syncOverview.total.success} valueStyle={{ color: '#3f8600' }} /></Col>
              <Col span={6}><Statistic title="失败条目" value={syncOverview.total.failed} valueStyle={{ color: '#cf1322' }} /></Col>
              <Col span={6}><Statistic title="跳过条目" value={syncOverview.total.skipped} valueStyle={{ color: '#595959' }} /></Col>
            </Row>
            <div style={{ marginTop: 14 }}>
              {(syncOverview.by_task_type || []).map((item) => {
                const total = item.success + item.failed + item.skipped
                const successPct = total > 0 ? Math.round((item.success / total) * 100) : 0
                const failedPct = total > 0 ? Math.round((item.failed / total) * 100) : 0
                const skippedPct = Math.max(0, 100 - successPct - failedPct)
                return (
                  <div key={item.task_type} style={{ marginBottom: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: 13 }}>{item.task_type}（{item.tasks} 次）</span>
                      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>成功 {item.success} / 失败 {item.failed} / 跳过 {item.skipped}</span>
                    </div>
                    <Progress
                      percent={100}
                      success={{ percent: successPct, strokeColor: '#52c41a' }}
                      strokeColor={failedPct > 0 ? '#ff7875' : '#d9d9d9'}
                      format={() => `${successPct}% / ${failedPct}% / ${skippedPct}%`}
                    />
                  </div>
                )
              })}
            </div>
          </Card>
        )}

        <Spin spinning={loading}>
        <Descriptions column={1} bordered size="small" style={{ maxWidth: 480 }}>
          <Descriptions.Item label="股票数量">{summary?.stock_count ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="行情条数">{summary?.total_quotes?.toLocaleString() ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="日期范围">{rangeStr}</Descriptions.Item>
          <Descriptions.Item label="最新数据日期">{summary?.last_sync_at ?? '-'}</Descriptions.Item>
        </Descriptions>
        </Spin>

        {tushareCheck && (
          <div style={{ marginTop: 16, padding: 12, background: tushareCheck.api_test === 'ok' ? 'var(--color-up-dim)' : 'var(--color-down-dim)', border: '1px solid', borderColor: tushareCheck.api_test === 'ok' ? 'rgba(0,230,118,0.35)' : 'rgba(255,71,87,0.35)', borderRadius: 8 }}>
            <p><strong>{(tushareCheck.data_provider || dataProvider).toUpperCase()} 诊断</strong></p>
            <p>当前主数据源：{tushareCheck.data_provider || dataProvider}</p>
            <p>Token 已配置：{tushareCheck.token_configured ? '是' : '否'}</p>
            <p>代理已配置：{tushareCheck.proxy_configured ? '是' : '否'}</p>
            <p>接口测试：{tushareCheck.api_test}</p>
            {tushareCheck.rows_returned != null && tushareCheck.rows_returned > 0 && (
              <p>返回行数：{tushareCheck.rows_returned}</p>
            )}
          </div>
        )}

        {syncing && (
          <div style={{ marginTop: 24 }}>
            <Progress percent={Math.round(taskProgress * 100)} status="active" />
            <p style={{ color: 'var(--text-secondary)', marginTop: 8 }}>{taskMessage}</p>
          </div>
        )}

        {(taskResult || lastSync?.result) && !syncing && (
          <div style={{ marginTop: 24, padding: 16, background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 8 }}>
            <h4>
              {taskResult ? '同步结果' : '上次同步'}
              {lastSync && !taskResult && lastSync.completed_at && (
                <span style={{ fontWeight: 'normal', color: 'var(--text-secondary)', marginLeft: 8 }}>
                  {dayjs(lastSync.completed_at).format('YYYY-MM-DD HH:mm')}
                </span>
              )}
            </h4>
            {(taskResult || lastSync?.result) && (
              <>
                <p>新增：{(taskResult?.success_count ?? lastSync?.result?.success_count ?? 0).toLocaleString()} 条</p>
                <p>跳过（已存在）：{(taskResult?.skipped_count ?? lastSync?.result?.skipped_count ?? 0).toLocaleString()} 条</p>
                <p>失败天数：{taskResult?.failed_count ?? lastSync?.result?.failed_count ?? 0} 天</p>
                <p>本地有有效行情的交易日：{taskResult?.days_synced ?? lastSync?.result?.days_synced ?? 0} 天</p>
                {(taskResult?.requested_dates ?? lastSync?.result?.requested_dates) && (
                  <>
                    <p>请求日期：{(taskResult?.requested_dates ?? lastSync?.result?.requested_dates)?.join('、')}</p>
                    <p>目标清单达标日期：{(taskResult?.completed_dates ?? lastSync?.result?.completed_dates)?.join('、') || '无'}</p>
                    <p>空数据日期：{(taskResult?.empty_dates ?? lastSync?.result?.empty_dates)?.join('、') || '无'}</p>
                    <p>不支持日期：{(taskResult?.unsupported_dates ?? lastSync?.result?.unsupported_dates)?.join('、') || '无'}</p>
                    <p>真实市场覆盖率：待验证（当前目标清单不是历史市场分母）</p>
                  </>
                )}
                {(taskResult?.diagnostic ?? lastSync?.result?.diagnostic) && (
                  <p style={{ color: 'var(--color-down)', marginTop: 8 }}>
                    诊断：{taskResult?.diagnostic ?? lastSync?.result?.diagnostic}
                  </p>
                )}
                {(taskResult?.date_results ?? lastSync?.result?.date_results) && (
                  <Table<FullMarketDateResult>
                    size="small"
                    rowKey="trade_date"
                    dataSource={taskResult?.date_results ?? lastSync?.result?.date_results}
                    pagination={{ pageSize: 10 }}
                    scroll={{ x: 640 }}
                    columns={[
                      { title: '日期', dataIndex: 'trade_date' },
                      { title: '日期结果', dataIndex: 'status', render: (value: string) => ({ success: '清单覆盖达标', partial: '部分完成', empty: '空数据', failed: '失败', unsupported: '不支持', requires_repair: '已有行待修复' }[value] || value) },
                      { title: '新增', dataIndex: 'inserted' },
                      { title: '目标数', dataIndex: 'target_count' },
                      { title: '核心字段有效', dataIndex: 'valid_core_count' },
                      { title: '当前清单覆盖', dataIndex: 'target_coverage_ratio', render: (value: number | null) => value == null ? '—' : `${(value * 100).toFixed(1)}%` },
                    ]}
                  />
                )}
              </>
            )}
          </div>
        )}
      </Card>

      <Card title="涨停筛选" style={{ marginTop: 24 }}>
        <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
          直接调用 AkShare 接口获取涨停股，加入观察池并自动下载 60 日 K 线。默认日期窗口与「最近已完成交易日」一致：盘后含当日；盘中为上一交易日（不再仅从自然日昨天起算）。
        </p>
        <Space>
          <span>处理最近</span>
          <InputNumber
            min={1}
            max={60}
            value={limitUpWindowDays}
            onChange={(v) => setLimitUpWindowDays(v ?? 1)}
            style={{ width: 80 }}
          />
          <span>个交易日</span>
          <Button
            type="primary"
            icon={<ThunderboltOutlined spin={limitUpCollecting} />}
            loading={limitUpCollecting}
            onClick={handleLimitUpCollect}
            disabled={limitUpCollecting}
            style={{ color: '#031a2b', fontWeight: 600 }}
          >
            执行涨停筛选
          </Button>
        </Space>
        {limitUpResult && (
          <div
            style={{
              marginTop: 16,
              padding: 12,
              background: 'var(--bg-surface)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 8,
              color: 'var(--text-primary)',
            }}
          >
            <p style={{ marginBottom: 8 }}>新增：{limitUpResult.added} 只</p>
            <p style={{ marginBottom: 8 }}>更新：{limitUpResult.updated} 只</p>
            <p style={{ marginBottom: 8 }}>跳过（ST 等）：{limitUpResult.skipped} 只</p>
            <p style={{ marginBottom: 0 }}>处理日期：{limitUpResult.dates_processed?.join(', ') || '-'}</p>
          </div>
        )}
      </Card>

      <Card title="同步任务历史明细" style={{ marginTop: 24 }}>
        <Table
          rowKey="id"
          size="small"
          pagination={{ pageSize: 10 }}
          dataSource={syncHistory}
          columns={[
            {
              title: '任务类型',
              dataIndex: 'task_type',
              key: 'task_type',
              render: (v: string) => <Tag>{v}</Tag>,
            },
            {
              title: '状态',
              dataIndex: 'status',
              key: 'status',
              render: (v: string) => {
                const color = v === 'completed' ? 'green' : v === 'failed' ? 'red' : 'blue'
                return <Tag color={color}>{v}</Tag>
              },
            },
            {
              title: '成功',
              key: 'success_count',
              render: (_: unknown, r: SyncHistoryItem) => (r.result?.success_count ?? 0).toLocaleString(),
            },
            {
              title: '失败',
              key: 'failed_count',
              render: (_: unknown, r: SyncHistoryItem) => (r.result?.failed_count ?? 0).toLocaleString(),
            },
            {
              title: '跳过',
              key: 'skipped_count',
              render: (_: unknown, r: SyncHistoryItem) => (r.result?.skipped_count ?? 0).toLocaleString(),
            },
            {
              title: '任务说明',
              key: 'message',
              render: (_: unknown, r: SyncHistoryItem) => r.result?.message || '-',
            },
            {
              title: '完成时间',
              dataIndex: 'completed_at',
              key: 'completed_at',
              render: (v: string | null) => (v ? dayjs(v).format('YYYY-MM-DD HH:mm:ss') : '-'),
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default DataPage
