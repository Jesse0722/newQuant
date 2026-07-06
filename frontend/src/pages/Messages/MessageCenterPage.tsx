import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
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
  FileSearchOutlined,
  FireOutlined,
  ReloadOutlined,
  StarFilled,
  StarOutlined,
  ThunderboltOutlined,
  UploadOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import {
  addIndustryCandidateToPool,
  generateIndustryReport,
  getIndustryDailyReport,
} from '../../api/industryReports'
import {
  acceptMessageOpportunity,
  collectMessageXPosts,
  dismissMessageOpportunity,
  generateMessageAgentDaily,
  getDailyMessages,
  getMessageAgentDaily,
  getMessageOpportunityEvidence,
  importDefaultMessageKeywords,
  importMessageKeywords,
  listMessageAgentRuns,
  listMessageKeywords,
  reviewMessageOpportunity,
  runMessageAgent,
  saveMessageKeyword,
} from '../../api/messages'
import { toggleCoreWatch } from '../../api/pools'
import type {
  MessageDaily,
  MessageAgentDaily,
  MessageAgentRun,
  MessageEvidence,
  IndustryDailyReport,
  IndustryReportCandidate,
  MessageLifecycleStage,
  MessageOpportunity,
  MessageOpportunityEvidence,
  MessageSeedKeyword,
  MessageSeedKeywordInput,
  MessageSentiment,
} from '../../types'
import { openStockDetail } from '../../utils/openStockDetail'

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

const stanceMap: Record<string, { label: string; color: string }> = {
  support: { label: '支持', color: 'green' },
  risk: { label: '风险', color: 'orange' },
  contradiction: { label: '反证', color: 'red' },
  neutral: { label: '中性', color: 'blue' },
}

const candidateGradeMap: Record<string, { label: string; color: string }> = {
  strong: { label: '强证据', color: 'green' },
  medium: { label: '中证据', color: 'blue' },
  weak: { label: '弱证据', color: 'default' },
  risk_watch: { label: '风险观察', color: 'orange' },
}

const keywordTypeOptions = [
  { value: 'industry', label: 'industry' },
  { value: 'product', label: 'product' },
  { value: 'company', label: 'company' },
  { value: 'catalyst', label: 'catalyst' },
]

const keywordLanguageOptions = [
  { value: 'en', label: 'en' },
  { value: 'zh', label: 'zh' },
]

const keywordStatusOptions = [
  { value: 'active', label: 'active' },
  { value: 'disabled', label: 'disabled' },
]

const keywordRowKey = (row: MessageSeedKeyword) =>
  `${row.keyword}-${row.type}-${row.theme}-${row.language}`

const normalizedKeyword = (value?: string) => (value || '').trim().toLowerCase().replace(/\s+/g, ' ')

const sortAndDedupeKeywords = (rows: MessageSeedKeyword[]) => {
  const sorted = [...rows].sort((a, b) => {
    if (a.status !== b.status) return a.status === 'active' ? -1 : 1
    if (a.priority !== b.priority) return b.priority - a.priority
    const themeOrder = a.theme.localeCompare(b.theme, 'zh-Hans-CN')
    if (themeOrder) return themeOrder
    return a.keyword.localeCompare(b.keyword, 'zh-Hans-CN')
  })
  const seen = new Set<string>()
  return sorted.filter((row) => {
    const key = normalizedKeyword(row.keyword)
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

const upsertKeywordRows = (rows: MessageSeedKeyword[], next: MessageSeedKeyword) => {
  const nextKey = normalizedKeyword(next.keyword)
  const filtered = rows.filter((row) => normalizedKeyword(row.keyword) !== nextKey)
  return sortAndDedupeKeywords([next, ...filtered])
}

const formatTradeDate = (value: string) =>
  value?.length === 8 ? `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}` : value

const scoreStatus = (score: number): 'success' | 'normal' | 'exception' =>
  score >= 80 ? 'success' : score >= 60 ? 'normal' : 'exception'

const errorText = (error: unknown, fallback: string) => {
  const apiError = error as { response?: { data?: { message?: string; detail?: string } } }
  const messageText = apiError.response?.data?.message
  const detailText = apiError.response?.data?.detail
  return detailText ? `${messageText || fallback}：${detailText}` : (messageText || fallback)
}

const sourceLinkForPlatform = (row: MessageOpportunity, index: number) => {
  const link = row.source_links?.[index]
  if (link) return link
  return row.source_platforms.length === 1 ? row.source_links?.find(Boolean) : undefined
}

const evidenceUrl = (row: MessageEvidence) => {
  if (row.source_item?.url) return row.source_item.url
  const rawUrl = row.raw_json?.url
  return typeof rawUrl === 'string' ? rawUrl : undefined
}

const stageTag = (stage: MessageLifecycleStage) => {
  const item = stageMap[stage] || { label: stage, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}

const sentimentTag = (sentiment: MessageSentiment) => {
  const item = sentimentMap[sentiment] || { label: sentiment, color: 'default' }
  return <Tag color={item.color}>{item.label}</Tag>
}

const MessageCenterPage: React.FC = () => {
  const [daily, setDaily] = useState<MessageDaily | null>(null)
  const [loading, setLoading] = useState(true)
  const [themeFilter, setThemeFilter] = useState<string>('all')
  const [highScoreOnly, setHighScoreOnly] = useState(false)
  const [coreWatchBusy, setCoreWatchBusy] = useState<string | null>(null)
  const [xCollecting, setXCollecting] = useState(false)
  const [keywordImporting, setKeywordImporting] = useState(false)
  const [keywordModalOpen, setKeywordModalOpen] = useState(false)
  const [keywords, setKeywords] = useState<MessageSeedKeyword[]>([])
  const [keywordLoading, setKeywordLoading] = useState(false)
  const [keywordSaving, setKeywordSaving] = useState(false)
  const [keywordPage, setKeywordPage] = useState(1)
  const [industryReport, setIndustryReport] = useState<IndustryDailyReport | null>(null)
  const [industryLoading, setIndustryLoading] = useState(false)
  const [industryGenerating, setIndustryGenerating] = useState(false)
  const [agentRuns, setAgentRuns] = useState<MessageAgentRun[]>([])
  const [agentDaily, setAgentDaily] = useState<MessageAgentDaily | null>(null)
  const [agentDailyLoading, setAgentDailyLoading] = useState(false)
  const [agentDailyGenerating, setAgentDailyGenerating] = useState(false)
  const [agentRunsLoading, setAgentRunsLoading] = useState(false)
  const [agentRunning, setAgentRunning] = useState(false)
  const [evidenceModalOpen, setEvidenceModalOpen] = useState(false)
  const [evidenceLoading, setEvidenceLoading] = useState(false)
  const [reviewBusy, setReviewBusy] = useState(false)
  const [selectedOpportunity, setSelectedOpportunity] = useState<MessageOpportunity | null>(null)
  const [opportunityEvidence, setOpportunityEvidence] = useState<MessageOpportunityEvidence[]>([])
  const [keywordForm] = Form.useForm<MessageSeedKeywordInput>()

  const fetchIndustryReport = useCallback(async () => {
    setIndustryLoading(true)
    try {
      const res = await getIndustryDailyReport()
      setIndustryReport(res.data)
    } catch (error) {
      message.error(errorText(error, '加载产业链日报失败'))
    } finally {
      setIndustryLoading(false)
    }
  }, [])

  const fetchDaily = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getDailyMessages({ ensure_seed: false })
      setDaily(res.data)
      setThemeFilter((prev) => {
        if (prev === 'all') return prev
        return res.data.topics.some((t) => t.theme === prev) ? prev : 'all'
      })
    } catch (error) {
      message.error(errorText(error, '加载题材挖掘失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchAgentRuns = useCallback(async () => {
    setAgentRunsLoading(true)
    try {
      const res = await listMessageAgentRuns({ limit: 5 })
      setAgentRuns(res.data)
    } catch (error) {
      message.error(errorText(error, '加载Agent运行记录失败'))
    } finally {
      setAgentRunsLoading(false)
    }
  }, [])

  const fetchAgentDaily = useCallback(async (tradeDate?: string) => {
    setAgentDailyLoading(true)
    try {
      const res = await getMessageAgentDaily({ trade_date: tradeDate, limit: 5 })
      setAgentDaily(res.data)
    } catch (error) {
      message.error(errorText(error, '加载证据日报失败'))
    } finally {
      setAgentDailyLoading(false)
    }
  }, [])

  const handleGenerateAgentDaily = async (useLlm = false) => {
    setAgentDailyGenerating(true)
    try {
      const res = await generateMessageAgentDaily({
        trade_date: daily?.trade_date,
        use_llm: useLlm,
        provider: useLlm ? 'deepseek' : undefined,
        model: useLlm ? 'deepseek-v4-flash' : undefined,
        limit: 5,
      })
      setAgentDaily(res.data)
      message.success(useLlm ? 'DeepSeek证据日报已生成' : '证据日报已刷新')
    } catch (error) {
      message.error(errorText(error, '生成证据日报失败'))
    } finally {
      setAgentDailyGenerating(false)
    }
  }

  const handleRunDeepSeekCleaner = async () => {
    setAgentRunning(true)
    try {
      const res = await runMessageAgent({
        agent_name: 'llm_evidence_cleaner',
        trade_date: daily?.trade_date,
        provider: 'deepseek',
        model: 'deepseek-v4-flash',
        limit: 20,
      })
      message.success(
        `DeepSeek清洗完成：证据${res.data.evidence_count}条，回退${res.data.fallback_count}条`
      )
      await fetchAgentRuns()
      await fetchAgentDaily(daily?.trade_date)
    } catch (error) {
      message.error(errorText(error, 'DeepSeek清洗失败'))
    } finally {
      setAgentRunning(false)
    }
  }

  useEffect(() => {
    fetchDaily()
    fetchIndustryReport()
    fetchAgentRuns()
    fetchAgentDaily()
  }, [fetchDaily, fetchIndustryReport, fetchAgentRuns, fetchAgentDaily])

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

  const openOpportunityEvidence = async (row: MessageOpportunity) => {
    setSelectedOpportunity(row)
    setEvidenceModalOpen(true)
    setEvidenceLoading(true)
    try {
      const res = await getMessageOpportunityEvidence(row.id)
      setOpportunityEvidence(res.data)
    } catch (error) {
      setOpportunityEvidence([])
      message.error(errorText(error, '加载机会证据失败'))
    } finally {
      setEvidenceLoading(false)
    }
  }

  const replaceOpportunity = (next: MessageOpportunity | null) => {
    if (!next) return
    setSelectedOpportunity(next)
    setDaily((prev) => {
      if (!prev) return prev
      const opportunities = next.status === 'dismissed'
        ? prev.opportunities.filter((item) => item.id !== next.id)
        : prev.opportunities.map((item) => item.id === next.id ? next : item)
      return {
        ...prev,
        opportunities,
        stats: {
          ...prev.stats,
          opportunity_count: opportunities.length,
          top_score: opportunities[0]?.opportunity_score ?? null,
        },
      }
    })
  }

  const handleReviewOpportunity = async () => {
    if (!selectedOpportunity) return
    setReviewBusy(true)
    try {
      const res = await reviewMessageOpportunity(selectedOpportunity.id, {
        review_status: 'reviewed',
        review_reason: '人工已查看证据',
      })
      replaceOpportunity(res.data)
      message.success('已标记复核')
    } catch (error) {
      message.error(errorText(error, '标记复核失败'))
    } finally {
      setReviewBusy(false)
    }
  }

  const handleAcceptOpportunity = async () => {
    if (!selectedOpportunity) return
    setReviewBusy(true)
    try {
      const res = await acceptMessageOpportunity(selectedOpportunity.id)
      replaceOpportunity(res.data)
      message.success(`${res.data.stock_name || res.data.ts_code || '候选'} 已采纳并加入核心关注`)
    } catch (error) {
      message.error(errorText(error, '采纳机会失败'))
    } finally {
      setReviewBusy(false)
    }
  }

  const handleDismissOpportunity = async () => {
    if (!selectedOpportunity) return
    setReviewBusy(true)
    try {
      const res = await dismissMessageOpportunity(selectedOpportunity.id, { review_reason: '人工驳回' })
      replaceOpportunity(res.data)
      setEvidenceModalOpen(false)
      message.success('已驳回候选')
    } catch (error) {
      message.error(errorText(error, '驳回机会失败'))
    } finally {
      setReviewBusy(false)
    }
  }

  const handleCandidateCoreWatch = async (row: IndustryReportCandidate) => {
    setCoreWatchBusy(row.ts_code)
    try {
      await addIndustryCandidateToPool(row.id)
      message.success(`${row.stock_name || row.ts_code} 已加入核心关注`)
    } catch (error) {
      message.error(errorText(error, '加入核心关注失败'))
    } finally {
      setCoreWatchBusy(null)
    }
  }

  const handleGenerateIndustryReport = async () => {
    setIndustryGenerating(true)
    try {
      const res = await generateIndustryReport({ refresh_seeds: true })
      setIndustryReport(res.data)
      message.success(`产业链日报已生成：${res.data.candidates.length} 个候选`)
    } catch (error) {
      message.error(errorText(error, '生成产业链日报失败'))
    } finally {
      setIndustryGenerating(false)
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
      message.error(errorText(error, 'X采集失败'))
    } finally {
      setXCollecting(false)
    }
  }

  const fetchKeywords = useCallback(async () => {
    setKeywordLoading(true)
    try {
      const res = await listMessageKeywords()
      setKeywords(sortAndDedupeKeywords(res.data))
    } catch (error) {
      message.error(errorText(error, '加载关键词失败'))
    } finally {
      setKeywordLoading(false)
    }
  }, [])

  const openKeywordModal = () => {
    setKeywordModalOpen(true)
    keywordForm.setFieldsValue({
      type: 'industry',
      priority: 5,
      language: 'en',
      status: 'active',
    })
    fetchKeywords()
  }

  const handleImportKeywords = async () => {
    setKeywordImporting(true)
    try {
      const res = await importDefaultMessageKeywords()
      message.success(
        `关键词导入完成：新增${res.data.created_count}个，更新${res.data.updated_count}个，跳过${res.data.skipped_count}个`
      )
      await fetchKeywords()
    } catch (error) {
      message.error(errorText(error, '关键词导入失败'))
    } finally {
      setKeywordImporting(false)
    }
  }

  const handleAddKeyword = async (values: MessageSeedKeywordInput) => {
    setKeywordSaving(true)
    try {
      const keyword = values.keyword.trim()
      const theme = values.theme.trim()
      if (!keyword || !theme) {
        message.warning('请输入关键词和题材')
        return
      }
      const duplicated = keywords.some((row) => normalizedKeyword(row.keyword) === normalizedKeyword(keyword))
      if (duplicated) {
        keywordForm.setFields([{ name: 'keyword', errors: ['关键词已存在'] }])
        message.warning(`关键词「${keyword}」已存在`)
        return
      }
      const payload: MessageSeedKeywordInput = {
        keyword,
        type: values.type || 'industry',
        theme,
        priority: values.priority || 3,
        language: values.language || 'en',
        status: values.status || 'active',
      }
      const res = await saveMessageKeyword(payload)
      message.success(`关键词已保存：${res.data.keyword}`)
      setKeywords((prev) => upsertKeywordRows(prev, res.data))
      setKeywordPage(1)
      keywordForm.resetFields()
      keywordForm.setFieldsValue({ type: 'industry', priority: 5, language: 'en', status: 'active' })
    } catch (error) {
      message.error(errorText(error, '保存关键词失败'))
    } finally {
      setKeywordSaving(false)
    }
  }

  const handleToggleKeyword = async (row: MessageSeedKeyword) => {
    const nextStatus = row.status === 'active' ? 'disabled' : 'active'
    setKeywordSaving(true)
    try {
      await importMessageKeywords({
        items: [{
          keyword: row.keyword,
          type: row.type,
          theme: row.theme,
          priority: row.priority,
          language: row.language,
          status: nextStatus,
        }],
      })
      message.success(nextStatus === 'active' ? '关键词已启用' : '关键词已禁用')
      await fetchKeywords()
    } catch (error) {
      message.error(errorText(error, '更新关键词状态失败'))
    } finally {
      setKeywordSaving(false)
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
            <Typography.Link onClick={() => row.ts_code && openStockDetail(row.ts_code)}>
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
      title: '复核',
      dataIndex: 'review_status',
      key: 'review_status',
      width: 100,
      render: (value: string) => (
        <Tag color={value === 'accepted' ? 'green' : value === 'dismissed' ? 'red' : value === 'needs_review' ? 'orange' : 'blue'}>
          {value || 'reviewed'}
        </Tag>
      ),
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
          {row.source_platforms.map((item, index) => {
            const link = sourceLinkForPlatform(row, index)
            const tag = <Tag color="blue" style={link ? { cursor: 'pointer' } : undefined}>{item}</Tag>
            return link ? (
              <a key={`${item}-${link}`} href={link} target="_blank" rel="noreferrer">
                {tag}
              </a>
            ) : (
              <React.Fragment key={item}>{tag}</React.Fragment>
            )
          })}
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
            <Tooltip title="查看证据">
              <Button
                size="small"
                icon={<FileSearchOutlined />}
                onClick={() => openOpportunityEvidence(row)}
              />
            </Tooltip>
            {row.ts_code && (
              <Tooltip title="查看股票详情">
                <Button
                size="small"
                icon={<EyeOutlined />}
                onClick={() => row.ts_code && openStockDetail(row.ts_code)}
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

  const candidateColumns = [
    {
      title: '标的',
      key: 'stock',
      width: 150,
      render: (_: unknown, row: IndustryReportCandidate) => (
        <Space direction="vertical" size={0}>
          <Typography.Link onClick={() => openStockDetail(row.ts_code)}>
            {row.stock_name || row.ts_code}
          </Typography.Link>
          <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>{row.ts_code}</span>
        </Space>
      ),
    },
    {
      title: '主题',
      dataIndex: 'theme',
      key: 'theme',
      width: 110,
      render: (theme: string) => <Tag color="cyan">{theme}</Tag>,
    },
    {
      title: '等级',
      dataIndex: 'grade',
      key: 'grade',
      width: 100,
      render: (grade: string) => {
        const item = candidateGradeMap[grade] || { label: grade, color: 'default' }
        return <Tag color={item.color}>{item.label}</Tag>
      },
    },
    {
      title: '综合分',
      dataIndex: 'final_score',
      key: 'final_score',
      width: 120,
      sorter: (a: IndustryReportCandidate, b: IndustryReportCandidate) => a.final_score - b.final_score,
      render: (score: number) => <Progress percent={Math.round(score)} size="small" status={scoreStatus(score)} />,
    },
    {
      title: '路径 / 证据',
      key: 'path',
      render: (_: unknown, row: IndustryReportCandidate) => {
        const path = row.path_json.map((step) => `${step.source}→${step.target}`).join(' / ')
        return (
          <Tooltip title={path}>
            <Space size={8} wrap>
              <Tag>路径 {row.path_score}</Tag>
              <Tag>证据 {row.evidence_score}</Tag>
              <span style={{ color: 'var(--text-secondary)' }}>{row.reason}</span>
            </Space>
          </Tooltip>
        )
      },
    },
    {
      title: '风险',
      key: 'risk',
      width: 150,
      render: (_: unknown, row: IndustryReportCandidate) => (
        <Tooltip title={row.risks.join('；')}>
          <Space>
            <WarningOutlined style={{ color: row.risk_score >= 65 ? 'var(--color-warn)' : 'var(--text-muted)' }} />
            <span>{row.risk_score}</span>
          </Space>
        </Tooltip>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 130,
      fixed: 'right' as const,
      render: (_: unknown, row: IndustryReportCandidate) => (
        <Space>
          <Tooltip title="查看股票详情">
            <Button size="small" icon={<EyeOutlined />} onClick={() => openStockDetail(row.ts_code)} />
          </Tooltip>
          <Tooltip title="加入核心关注">
            <Button
              size="small"
              icon={coreWatchBusy === row.ts_code ? <StarFilled /> : <StarOutlined />}
              loading={coreWatchBusy === row.ts_code}
              onClick={() => handleCandidateCoreWatch(row)}
            />
          </Tooltip>
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
          <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>题材挖掘</div>
          <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: 22 }}>
            今日题材与个股机会
          </h2>
          <div style={{ color: 'var(--text-secondary)', fontSize: 13 }}>
            {daily ? formatTradeDate(daily.trade_date) : '-'} · 聚焦 AI 产业链传播与映射
          </div>
        </div>
        <Space>
          <Button icon={<UploadOutlined />} onClick={openKeywordModal}>
            关键词管理
          </Button>
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

      <Card
        size="small"
        title="Agent运行记录"
        extra={
          <Space>
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              onClick={handleRunDeepSeekCleaner}
              loading={agentRunning}
            >
              DeepSeek清洗
            </Button>
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchAgentRuns} loading={agentRunsLoading}>
              刷新
            </Button>
          </Space>
        }
      >
        {agentRuns.length ? (
          <Table
            rowKey="id"
            size="small"
            loading={agentRunsLoading}
            dataSource={agentRuns}
            pagination={false}
            columns={[
              {
                title: 'Agent',
                dataIndex: 'agent_name',
                width: 200,
                render: (value: string, row: MessageAgentRun) => (
                  <Space>
                    <span className="mono">{value}</span>
                    <Tag>{row.agent_version}</Tag>
                  </Space>
                ),
              },
              {
                title: '状态',
                dataIndex: 'status',
                width: 100,
                render: (status: string) => (
                  <Tag color={status === 'success' ? 'green' : status === 'failed' ? 'red' : 'default'}>{status}</Tag>
                ),
              },
              {
                title: '日期',
                dataIndex: 'trade_date',
                width: 110,
                render: (value: string | null) => value ? formatTradeDate(value) : '-',
              },
              {
                title: '输出',
                key: 'output',
                render: (_: unknown, row: MessageAgentRun) => (
                  <Space size={[6, 6]} wrap>
                    <Tag>消息 {String(row.output_json.source_item_count ?? '-')}</Tag>
                    <Tag>证据 {String(row.output_json.evidence_count ?? '-')}</Tag>
                    {row.error_message && <Tag color="red">{row.error_message}</Tag>}
                  </Space>
                ),
              },
              {
                title: '耗时',
                dataIndex: 'duration_ms',
                width: 90,
                render: (value: number | null) => value == null ? '-' : `${value}ms`,
              },
            ]}
          />
        ) : (
          <Empty description="暂无Agent运行记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>

      <Card
        title={
          <Space>
            <FileSearchOutlined />
            <span>Agent证据日报</span>
            {agentDaily?.model_provider && <Tag color="blue">{agentDaily.model_provider}</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => fetchAgentDaily(daily?.trade_date)}
              loading={agentDailyLoading}
            >
              读取
            </Button>
            <Button
              size="small"
              onClick={() => handleGenerateAgentDaily(false)}
              loading={agentDailyGenerating}
            >
              规则生成
            </Button>
            <Button
              size="small"
              type="primary"
              onClick={() => handleGenerateAgentDaily(true)}
              loading={agentDailyGenerating}
            >
              DeepSeek生成
            </Button>
          </Space>
        }
      >
        <Spin spinning={agentDailyLoading && !agentDaily}>
          {agentDaily ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {agentDaily.headline}
                </Typography.Title>
                <Typography.Paragraph style={{ margin: '6px 0 0', color: 'var(--text-secondary)' }}>
                  {agentDaily.summary}
                </Typography.Paragraph>
              </div>
              <Space size={[6, 6]} wrap>
                <Tag>证据 {String(agentDaily.evidence_coverage.evidence_count ?? 0)}</Tag>
                <Tag>候选 {String(agentDaily.evidence_coverage.candidate_count ?? 0)}</Tag>
                <Tag>题材 {String(agentDaily.evidence_coverage.theme_count ?? 0)}</Tag>
                {agentDaily.risk_flags.slice(0, 3).map((item) => (
                  <Tag key={item} color="orange">{item}</Tag>
                ))}
              </Space>
              {agentDaily.next_actions.length ? (
                <Space size={[6, 6]} wrap>
                  {agentDaily.next_actions.slice(0, 4).map((item) => (
                    <Tag key={item} color="green">{item}</Tag>
                  ))}
                </Space>
              ) : null}
              {agentDaily.candidates.length ? (
                <Table
                  rowKey={(row) => `${row.ts_code || row.theme}-${row.theme}`}
                  size="small"
                  dataSource={agentDaily.candidates}
                  pagination={false}
                  columns={[
                    {
                      title: '候选',
                      key: 'target',
                      width: 150,
                      render: (_: unknown, row) => (
                        <Space direction="vertical" size={0}>
                          <span>{row.stock_name || row.ts_code || row.theme}</span>
                          <span className="mono" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                            {row.ts_code || 'THEME'}
                          </span>
                        </Space>
                      ),
                    },
                    {
                      title: '题材',
                      dataIndex: 'theme',
                      width: 110,
                      render: (theme: string) => <Tag color="cyan">{theme}</Tag>,
                    },
                    {
                      title: '证据',
                      key: 'evidence',
                      width: 140,
                      render: (_: unknown, row) => (
                        <Space>
                          <Tag>条数 {row.evidence_count}</Tag>
                          <Tag>分 {row.evidence_score}</Tag>
                        </Space>
                      ),
                    },
                    {
                      title: '结论',
                      dataIndex: 'conclusion',
                      ellipsis: true,
                      render: (value: string) => (
                        <Tooltip title={value}>
                          <span>{value}</span>
                        </Tooltip>
                      ),
                    },
                  ]}
                />
              ) : (
                <Empty description="暂无证据候选" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Space>
          ) : (
            <Empty description="暂无证据日报" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </Spin>
      </Card>

      <Card
        title={
          <Space>
            <ThunderboltOutlined />
            <span>产业链日报</span>
            {industryReport?.status && <Tag color="blue">{industryReport.status}</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={fetchIndustryReport} loading={industryLoading}>
              读取
            </Button>
            <Button
              size="small"
              type="primary"
              onClick={handleGenerateIndustryReport}
              loading={industryGenerating}
            >
              生成
            </Button>
          </Space>
        }
      >
        <Spin spinning={industryLoading && !industryReport}>
          {industryReport ? (
            <Space direction="vertical" size={12} style={{ width: '100%' }}>
              <div>
                <Typography.Title level={5} style={{ margin: 0 }}>
                  {industryReport.headline || industryReport.title}
                </Typography.Title>
                <Typography.Paragraph style={{ margin: '6px 0 0', color: 'var(--text-secondary)' }}>
                  {industryReport.summary}
                </Typography.Paragraph>
              </div>
              <Space size={[6, 6]} wrap>
                {(industryReport.report_json.core_catalysts || []).map((item) => (
                  <Tag key={item} color="cyan">{item}</Tag>
                ))}
                {(industryReport.report_json.risk_flags || []).slice(0, 3).map((item) => (
                  <Tag key={item} color="orange">{item}</Tag>
                ))}
              </Space>
              {industryReport.candidates.length ? (
                <Table
                  rowKey="id"
                  size="small"
                  columns={candidateColumns}
                  dataSource={industryReport.candidates}
                  pagination={{ pageSize: 5, size: 'small' }}
                  scroll={{ x: 1050 }}
                />
              ) : (
                <Empty description="本次日报暂无候选标的" />
              )}
            </Space>
          ) : (
            <Empty
              description="暂无产业链日报"
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            >
              <Button type="primary" onClick={handleGenerateIndustryReport} loading={industryGenerating}>
                生成产业链日报
              </Button>
            </Empty>
          )}
        </Spin>
      </Card>

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

      <Modal
        title={`${selectedOpportunity?.stock_name || selectedOpportunity?.ts_code || '主题机会'} · 证据`}
        open={evidenceModalOpen}
        onCancel={() => setEvidenceModalOpen(false)}
        footer={
          <Space>
            <Button onClick={() => setEvidenceModalOpen(false)}>关闭</Button>
            <Button onClick={handleDismissOpportunity} loading={reviewBusy} danger>
              驳回
            </Button>
            <Button onClick={handleReviewOpportunity} loading={reviewBusy}>
              标记复核
            </Button>
            <Button type="primary" onClick={handleAcceptOpportunity} loading={reviewBusy}>
              采纳加入观察
            </Button>
          </Space>
        }
        width={900}
      >
        <Spin spinning={evidenceLoading}>
          {opportunityEvidence.length ? (
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={opportunityEvidence}
              columns={[
                {
                  title: '证据片段',
                  key: 'evidence',
                  render: (_: unknown, row: MessageOpportunityEvidence) => (
                    <Space direction="vertical" size={4}>
                      <Typography.Text>{row.evidence?.evidence_text || '-'}</Typography.Text>
                      <Space size={[4, 4]} wrap>
                        {row.evidence?.source_item?.source_name && <Tag>{row.evidence.source_item.source_name}</Tag>}
                        {row.evidence?.channel && <Tag color="blue">{row.evidence.channel}</Tag>}
                        {row.evidence?.theme && <Tag color="cyan">{row.evidence.theme}</Tag>}
                        {row.evidence?.ts_code && <Tag>{row.evidence.ts_code}</Tag>}
                      </Space>
                    </Space>
                  ),
                },
                {
                  title: '立场',
                  key: 'stance',
                  width: 90,
                  render: (_: unknown, row: MessageOpportunityEvidence) => {
                    const stance = row.evidence?.stance || 'neutral'
                    const item = stanceMap[stance] || { label: stance, color: 'default' }
                    return <Tag color={item.color}>{item.label}</Tag>
                  },
                },
                {
                  title: '分数',
                  key: 'scores',
                  width: 180,
                  render: (_: unknown, row: MessageOpportunityEvidence) => (
                    <Space direction="vertical" size={2}>
                      <span>质量 {row.evidence?.quality_score ?? '-'}</span>
                      <span>可信 {row.evidence?.credibility_score ?? '-'}</span>
                      <span>置信 {row.evidence?.confidence ?? '-'}</span>
                    </Space>
                  ),
                },
                {
                  title: '来源',
                  key: 'source',
                  width: 100,
                  render: (_: unknown, row: MessageOpportunityEvidence) => {
                    const url = row.evidence ? evidenceUrl(row.evidence) : undefined
                    return url ? (
                      <Typography.Link href={url} target="_blank" rel="noreferrer">
                        原文
                      </Typography.Link>
                    ) : '-'
                  },
                },
              ]}
            />
          ) : (
            <Empty description="暂无关联证据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
          )}
        </Spin>
      </Modal>

      <Modal
        title="关键词管理"
        open={keywordModalOpen}
        onCancel={() => setKeywordModalOpen(false)}
        footer={null}
        width={920}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Form
            form={keywordForm}
            layout="inline"
            onFinish={handleAddKeyword}
            initialValues={{ type: 'industry', priority: 5, language: 'en', status: 'active' }}
          >
            <Form.Item
              name="keyword"
              rules={[
                { required: true, message: '请输入关键词' },
                {
                  validator: (_, value) => {
                    const key = normalizedKeyword(value)
                    if (!key) return Promise.resolve()
                    const duplicated = keywords.some((row) => normalizedKeyword(row.keyword) === key)
                    return duplicated ? Promise.reject(new Error('关键词已存在')) : Promise.resolve()
                  },
                },
              ]}
            >
              <Input placeholder="关键词 / 公司名" style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="theme" rules={[{ required: true, message: '请输入题材' }]}>
              <Input placeholder="题材" style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="type">
              <Select options={keywordTypeOptions} style={{ width: 120 }} />
            </Form.Item>
            <Form.Item name="language">
              <Select options={keywordLanguageOptions} style={{ width: 80 }} />
            </Form.Item>
            <Form.Item name="priority">
              <InputNumber min={1} max={5} style={{ width: 80 }} />
            </Form.Item>
            <Form.Item name="status">
              <Select options={keywordStatusOptions} style={{ width: 100 }} />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={keywordSaving}>
                新增
              </Button>
            </Form.Item>
          </Form>

          <Space>
            <Button icon={<UploadOutlined />} onClick={handleImportKeywords} loading={keywordImporting}>
              导入默认种子
            </Button>
            <Button icon={<ReloadOutlined />} onClick={fetchKeywords} loading={keywordLoading}>
              刷新关键词
            </Button>
          </Space>

          <Table
            rowKey={keywordRowKey}
            size="small"
            loading={keywordLoading}
            dataSource={keywords}
            pagination={{
              current: keywordPage,
              pageSize: 8,
              showSizeChanger: false,
              onChange: setKeywordPage,
            }}
            columns={[
              {
                title: '关键词',
                dataIndex: 'keyword',
                width: 170,
                render: (value: string) => <span className="mono">{value}</span>,
              },
              { title: '题材', dataIndex: 'theme', width: 120 },
              { title: '类型', dataIndex: 'type', width: 100 },
              { title: '语言', dataIndex: 'language', width: 70 },
              { title: '优先级', dataIndex: 'priority', width: 80 },
              {
                title: '状态',
                dataIndex: 'status',
                width: 90,
                render: (status: string) => <Tag color={status === 'active' ? 'green' : 'default'}>{status}</Tag>,
              },
              {
                title: '操作',
                key: 'action',
                width: 100,
                render: (_: unknown, row: MessageSeedKeyword) => (
                  <Button size="small" onClick={() => handleToggleKeyword(row)} loading={keywordSaving}>
                    {row.status === 'active' ? '禁用' : '启用'}
                  </Button>
                ),
              },
            ]}
          />
        </Space>
      </Modal>
    </div>
  )
}

export default MessageCenterPage
