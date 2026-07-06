import client from './client'
import type {
  MessageDaily,
  MessageDailyConclusion,
  MessageAgentRun,
  MessageAgentRunResult,
  MessageAgentDaily,
  MessageEvidence,
  MessageKeywordImportResult,
  MessageOpportunity,
  MessageOpportunityEvidence,
  MessageSeedKeyword,
  MessageSeedKeywordInput,
  MessageSourceImportResult,
  MessageSourceItemInput,
  MessageTopic,
  MessageXCollectRequest,
  MessageXCollectResult,
  MessageXSeedSummary,
} from '../types'

export const getDailyMessages = (params?: {
  trade_date?: string
  ensure_seed?: boolean
}) => client.get<MessageDaily>('/messages/daily', { params })

export const getDailyMessageConclusion = (params?: {
  trade_date?: string
  ensure_seed?: boolean
  limit?: number
}) => client.get<MessageDailyConclusion>('/messages/daily-conclusion', { params })

export const getMessageAgentDaily = (params?: {
  trade_date?: string
  limit?: number
}) => client.get<MessageAgentDaily>('/messages/agent-daily', { params })

export const generateMessageAgentDaily = (data: {
  trade_date?: string
  use_llm?: boolean
  provider?: string
  model?: string
  limit?: number
}) => client.post<MessageAgentDaily>('/messages/agent-daily/generate', data)

export const createMessageTopic = (data: Partial<MessageTopic> & { theme: string }) =>
  client.post<MessageTopic>('/messages/topics', data)

export const createMessageOpportunity = (
  data: Partial<MessageOpportunity> & { theme: string }
) => client.post<MessageOpportunity>('/messages/opportunities', data)

export const importMessageSourceItems = (
  data: { items: MessageSourceItemInput[]; aggregate?: boolean }
) => client.post<MessageSourceImportResult>('/messages/source-items/import', data)

export const getMessageEvidence = (params?: {
  trade_date?: string
  theme?: string
  ts_code?: string
  stance?: string
  status?: string
  source_item_id?: string
  limit?: number
}) => client.get<MessageEvidence[]>('/messages/evidence', { params })

export const getMessageOpportunityEvidence = (opportunityId: string) =>
  client.get<MessageOpportunityEvidence[]>(`/messages/opportunities/${opportunityId}/evidence`)

export const reviewMessageOpportunity = (
  opportunityId: string,
  data: { review_status: string; review_reason?: string }
) => client.post<MessageOpportunity>(`/messages/opportunities/${opportunityId}/review`, data)

export const acceptMessageOpportunity = (opportunityId: string) =>
  client.post<MessageOpportunity>(`/messages/opportunities/${opportunityId}/accept`)

export const dismissMessageOpportunity = (
  opportunityId: string,
  data?: { review_reason?: string }
) => client.post<MessageOpportunity>(`/messages/opportunities/${opportunityId}/dismiss`, data || {})

export const listMessageAgentRuns = (params?: {
  agent_name?: string
  trade_date?: string
  status?: string
  limit?: number
}) => client.get<MessageAgentRun[]>('/message-agents/runs', { params })

export const runMessageAgent = (data: {
  agent_name: string
  trade_date?: string
  source_item_ids?: string[]
  limit?: number
  provider?: string
  model?: string
  dry_run?: boolean
}) => client.post<MessageAgentRunResult>('/message-agents/run', data)

export const getMessageXSeeds = () =>
  client.get<MessageXSeedSummary>('/messages/x/seeds')

export const collectMessageXPosts = (data: MessageXCollectRequest) =>
  client.post<MessageXCollectResult>('/messages/x/collect', data)

export const listMessageKeywords = () =>
  client.get<MessageSeedKeyword[]>('/messages/keywords')

export const saveMessageKeyword = (data: MessageSeedKeywordInput) =>
  client.post<MessageSeedKeyword>('/messages/keywords', data)

export const importMessageKeywords = (data: { items: MessageSeedKeywordInput[] }) =>
  client.post<MessageKeywordImportResult>('/messages/keywords/import', data)

export const importDefaultMessageKeywords = () =>
  client.post<MessageKeywordImportResult>('/messages/keywords/import-default')
