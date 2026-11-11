import { Descriptions, Typography } from 'antd'

const labels: Record<string, string> = {
  success_count: '成功', failed_count: '失败', skipped_count: '跳过', added: '新增', updated: '更新', skipped: '跳过',
  created_count: '新增消息', evidence_count: '证据数', fallback_count: '回退数', total_signals: '信号数', total: '结果数',
  avg_pct: '平均收益(%)', win_rate: '胜率(%)', quote_count: '行情条数', map_count: '映射条数', message: '结果说明',
  diagnostic: '诊断', outcome: '完成情况', completed_dates: '完成日期', failed_dates: '失败日期', error: '失败原因',
}

export default function TaskResultSummary({ result }: { result: unknown }) {
  if (!result || typeof result !== 'object') return <Typography.Text type="secondary">未返回结构化结果，请查看任务说明。</Typography.Text>
  const values = result as Record<string, unknown>
  const nested = values.imported && typeof values.imported === 'object' ? values.imported as Record<string, unknown> : {}
  const entries = Object.entries({ ...values, ...nested }).filter(([key, value]) => key in labels && value != null)
  return entries.length ? <Descriptions column={1} bordered size="small" items={entries.map(([key, value]) => ({
    key, label: labels[key], children: Array.isArray(value)
      ? value.map(item => typeof item === 'string' ? item : item && typeof item === 'object' ? String(item.message || item.date || '') : '').filter(Boolean).join('；') || '无'
      : typeof value === 'object' ? '请到来源页面查看明细' : String(value),
  }))} /> : <Typography.Text type="secondary">结果已保存，可在来源页面查看候选和证据明细。</Typography.Text>
}
