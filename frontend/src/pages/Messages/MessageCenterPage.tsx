import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  EyeOutlined,
  FireOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
  ThunderboltOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import { collectMessageXPosts, getDailyMessages } from '../../api/messages'
import { toggleCoreWatch } from '../../api/pools'
import type { MessageDaily, MessageLifecycleStage, MessageOpportunity, MessageSentiment } from '../../types'

const stageMap: Record<string, { label: string; color: string }> = {
  early: { label: '早期', color: 'cyan' },
  spreading: { label: '扩散', color: 'green' },
  climax: { label: '高潮', color: 'orange' },
  cooling: { label: '退潮', color: 'default' },
}

const sentimentMap: Record<string, { label: string; color: string }> = {
  positive: { label: '正向', color: 'red' },
  neutral: { label: '中性', color: 'blue' },
  negative: { label: '负向', color: 'green' },
}

const actionMap: Record<string, { label: string; color: string }> = {
  watch: { label: '关注', color: 'blue' },
  add_to_pool: { label: '加入观察', color: 'green' },
  risk_watch: { label: '风险观察', color: 'orange' },
}

const formatTradeDate = (value: string) =>
  value?.length === 8 ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value

const scoreStatus = (score: number): 'success' | 'normal' | 'exception' =>
  score >= 80 ? 'success' : score >= 60 ? 'normal' : 'exception'

const stageTag = (stage: MessageLifecycleStage) => {
  const item = stageMap[stage] || { label: stage, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}

const sentimentTag = (sentiment: MessageSentiment) => {
  const item = sentimentMap[sentiment] || { label: sentiment, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}

const MessageCenterPage: React.FC = () => {
  const navigate = useNavigate()
  const [daily, setDaily] = useState<MessageDaily | null>(null)
  const [loading, setLoading] = useState(true)
  const [themeFilter, setThemeFilter] = useState<string>('all')
  const [highScoreOnly, setHighScoreOnly] = useState(false)
  const [coreWatchBusy, setCoreWatchBusy] = useState<string | null>(null)
  const [xCollecting, setXCollecting] = useState(false)

  const fetchDaily = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getDailyMessages({ ensure_seed: true })
      setDaily(res.data)
      setThemeFilter((prev) => {
        if (prev === 'all') return prev
        return res.data.topics.some((t) => t.theme === prev) ? prev : 'all'
      })
    } catch {
      message.error('加载消息中心失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDaily()
  }, [fetchDaily])

  const themeOptions = useMemo(() => [
    { value: 'all', label: '全部题材' },
    ...(daily?.topics || []).map((t) => ({ value: t.theme, label: t.theme })),
  ], [daily])

  const filteredOpportunities = useMemo(() => {
    let rows = daily?.opportunities || []
    if (themeFilter !== 'all') {
      rows = rows.filter((r) => r.theme === themeFilter)
    }
    if (highScoreOnly) {
      rows = rows.filter((r) => r.opportunity_score >= 80)
    }
    return rows
  }, [daily, highScoreOnly, themeFilter])

  const handleCoreWatch = async (row: MessageOpportunity) => {
    if (!row.ts_code) {
      message.warning('该机会没有股票代码')
      return
    }
    setCoreWatchBusy(row.ts_code)
    try {
      await toggleCoreWatch({ ts_code: row.ts_code, starred: true })
      message.success(`${row.stock_name || row.ts_code} 已加入核心关注`)
    } catch {
      message.error('加入核心关注失败')
    } finally {
      setCoreWatchBusy(null)
    }
  }

  const handleCollectX = async () => {
    setXCollecting(true)
    try {
      const res = await collectMessageXPosts({
        min_priority: 5,
        keyword_limit: 12,
        max_results: 20,
        aggregate: true,
      })
      const aggregation = res.data.imported.aggregation
      message.success(
        `X采集完成：新增${res.data.imported.created_count}条，跳过${res.data.imported.skipped_count}条，机会${aggregation?.opportunity_count ?? 0}个`
      )
      await fetchDaily()
    } catch (error) {
      const apiError = error as { response?: { data?: { message?: string; detail?: string } } }
      message.error(apiError.response?.data?.message || 'X采集失败')
    } finally {
      setXCollecting(false)
    }
  }

  const columns = [
    {
      title: '标的',
      key: 'stock',
      width: 150,
      render: (_: unknown, row: MessageOpportunity) => (
        <Space direction="vertical" size={0}>
          {row.ts_code ? (
            <Typography.Link onClick={() => navigate(`/stocks/${row.ts_code}`)}>
              {row.stock_name || row.ts_code}
            </Typography.Link>
          ) : (
            <span>{row.stock_name || '-'}</span>
          )}
          <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {row.ts_code || 'THEME'}
          </span>
        </Space>
      ),
    },
    {
      title: '题材',
      dataIndex: 'theme',
      key: 'theme',
      width: 110,
      render: (theme: string) => <Tag color="cyan">{theme}</Tag>,
    },
    {
      title: '机会分',
      dataIndex: 'opportunity_score',
      key: 'opportunity_score',
      width: 120,
      sorter: (a: MessageOpportunity, b: MessageOpportunity) => a.opportunity_score - b.opportunity_score,
      render: (score: number) => (
        <Progress percent={score} size="small" status={scoreStatus(score)} />
      ),
    },
    {
      title: '建议',
      dataIndex: 'action_suggestion',
      key: 'action_suggestion',
      width: 100,
      render: (value: string) => {
        const item = actionMap[value] || { label: value, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      },
    },
    {
      title: '机会逻辑',
      dataIndex: 'reason',
      key: 'reason',
      ellipsis: true,
      render: (reason: string) => (
        <Tooltip title={reason}>
          <span>{reason || '-'}</span>
        </Tooltip>
      ),
    },
    {
      title: '催化剂',
      key: 'catalysts',
      width: 220,
      render: (_: unknown, row: MessageOpportunity) => (
        <Space size={[4, 4]} wrap>
          {row.catalysts.slice(0, 3).map((item) => <Tag key={item}>{item}</Tag>)}
        </Space>
      ),
    },
    {
      title: '风险',
      key: 'risk',
      width: 180,
      render: (_: unknown, row: MessageOpportunity) => (
        <Tooltip title={row.risks.join('；')}>
          <Space>
            <WarningOutlined style={{ color: row.risk_score >= 65 ? 'var(--color-warn)' : 'var(--text-muted)' }} />
            <span>{row.risk_score}</span>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '来源',
      key: 'sources',
      width: 180,
      render: (_: unknown, row: MessageOpportunity) => (
        <Space size={[4, 4]} wrap>
          {row.source_platforms.map((item) => <Tag key={item} color="blue">{item}</Tag>)}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 150,
      fixed: 'right' as const,
      render: (_: unknown, row: MessageOpportunity) => (
        <Space>
          {row.ts_code && (
            <Tooltip title="查看股票详情">
              <Button
                size="small"
                icon={<EyeOutlined />}
                onClick={() => navigate(`/stocks/${row.ts_code}`)}
              />
            </Tooltip>
          )}
          {row.ts_code && (
            <Tooltip title="加入核心关注">
              <Button
                size="small"
                icon={coreWatchBusy === row.ts_code ? <StarFilled /> : <StarOutlined />}
                loading={coreWatchBusy === row.ts_code}
                onClick={() => handleCoreWatch(row)}
              />
            </Tooltip>
          )}
        </Space>
      ),
    },
  ]

  if (loading && !daily) {
    return (
      <div style={{ minHeight: 360, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <section style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'center' }}>
        <div>
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>今日消息</div>
          <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: 22 }}>
            题材与个股机会
          </h2>
          <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {daily ? formatTradeDate(daily.trade_date) : '-'} · 聚焦 AI 产业链传播与映射
          </div>
        </div>
        <Space>
          <Button icon={<ThunderboltOutlined />} onClick={handleCollectX} loading={xCollecting}>
            采集X
          </Button>
          <Button icon={<ReloadOutlined />} onClick={fetchDaily} loading={loading}>
            刷新
          </Button>
        </Space>
      </section>

      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="今日题材" value={daily?.stats.topic_count || 0} prefix={<FireOutlined />} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="个股机会" value={daily?.stats.opportunity_count || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="最高机会分" value={daily?.stats.top_score || 0} />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="强势题材" value={daily?.stats.leading_theme || '-'} />
          </Card>
        </Col>
      </Row>

      <section>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
          {(daily?.topics || []).map((topic) => (
            <Card
              key={topic.id}
              size="small"
              title={
                <Space>
                  <span>{topic.theme}</span>
                  {stageTag(topic.lifecycle_stage)}
                  {sentimentTag(topic.sentiment)}
                </Space>
              }
              extra={<span className="mono" style={{ color: 'var(--accent)' }}>{topic.heat_score}</span>}
            >
              <p style={{ color: 'var(--text-secondary)', minHeight: 44, marginBottom: 12 }}>
                {topic.summary}
              </p>
              <Space direction="vertical" size={6} style={{ width: '100%' }}>
                <div>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>可信度</span>
                  <Progress percent={topic.credibility_score} size="small" />
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>拥挤度</span>
                  <Progress percent={topic.crowding_score} size="small" status={topic.crowding_score >= 70 ? 'exception' : 'normal'} />
                </div>
              </Space>
              <Space size={[4, 4]} wrap style={{ marginTop: 12 }}>
                {topic.source_platforms.map((item) => <Tag key={item}>{item}</Tag>)}
              </Space>
            </Card>
          ))}
        </div>
      </section>

      <Card
        title="今日个股机会"
        extra={
          <Space>
            <Select
              size="small"
              value={themeFilter}
              style={{ width: 140 }}
              options={themeOptions}
              onChange={setThemeFilter}
            />
            <Space size={6}>
              <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>高分</span>
              <Switch size="small" checked={highScoreOnly} onChange={setHighScoreOnly} />
            </Space>
          </Space>
        }
      >
        {filteredOpportunities.length ? (
          <Table
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={filteredOpportunities}
            pagination={false}
            scroll={{ x: 1280 }}
          />
        ) : (
          <Empty description="暂无符合条件的机会" />
        )}
      </Card>
    </div>
  )
}

export default MessageCenterPage
