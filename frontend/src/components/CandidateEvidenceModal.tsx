import { safeEvidenceUrl } from '../utils/safeEvidenceUrl'
import { Empty, Modal, Space, Spin, Table, Tag, Typography } from 'antd'

export interface CandidateEvidenceRow {
  id: string
  text: string
  kind?: string
  source?: string
  channel?: string
  stance?: string
  confidence?: number
  url?: string
}


const stanceLabels: Record<string, string> = { support: '支持', supporting: '支持', contradiction: '反证', against: '反证', opposing: '反证', risk: '风险', neutral: '中性' }

export default function CandidateEvidenceModal({ title, open, loading, rows, path, onClose }: {
  title: string; open: boolean; loading: boolean; rows: CandidateEvidenceRow[]; path?: string; onClose: () => void
}) {
  return <Modal title={title} open={open} onCancel={onClose} onOk={onClose} cancelButtonProps={{ style: { display: 'none' } }} width={900}>
    {path && <Typography.Paragraph>关联路径：{path}</Typography.Paragraph>}
    <Spin spinning={loading}>
      {rows.length ? <Table rowKey="id" dataSource={rows} pagination={false} size="small" columns={[
        { title: '原文 / 摘要', key: 'text', render: (_, row) => <Space direction="vertical" size={4}>
          <Typography.Text>{row.text || '未保留原文片段'}</Typography.Text>
          <Space wrap><Tag>{row.kind === 'quote' ? '原文引用' : ['seed', 'seed_note'].includes(row.kind || '') ? '种子映射（非当日催化）' : '摘要 / 关系证据'}</Tag>
            {row.source && <Tag>{row.source}</Tag>}{row.channel && <Tag>{row.channel}</Tag>}</Space>
        </Space> },
        { title: '立场', dataIndex: 'stance', render: value => <Tag color={['contradiction', 'against', 'opposing', 'risk'].includes(value) ? 'red' : 'default'}>{stanceLabels[value] || '未标注'}</Tag> },
        { title: '置信度', dataIndex: 'confidence', render: value => value ?? '未提供' },
        { title: '来源', key: 'url', render: (_, row) => safeEvidenceUrl(row.url) ? <Typography.Link href={safeEvidenceUrl(row.url)} target="_blank" rel="noreferrer">原文</Typography.Link> : '缺少原文链接' },
      ]} /> : <Empty description="该候选暂无关联证据，不能据此确认结论" />}
    </Spin>
  </Modal>
}
