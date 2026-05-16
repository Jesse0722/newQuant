import client from './client'
import type {
  MessageDaily,
  MessageOpportunity,
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

export const createMessageTopic = (data: Partial<MessageTopic> & { theme: string }) =>
  client.post<MessageTopic>('/messages/topics', data)

export const createMessageOpportunity = (
  data: Partial<MessageOpportunity> & { theme: string }
) => client.post<MessageOpportunity>('/messages/opportunities', data)

export const importMessageSourceItems = (
  data: { items: MessageSourceItemInput[]; aggregate?: boolean }
) => client.post<MessageSourceImportResult>('/messages/source-items/import', data)

export const getMessageXSeeds = () =>
  client.get<MessageXSeedSummary>('/messages/x/seeds')

export const collectMessageXPosts = (data: MessageXCollectRequest) =>
  client.post<MessageXCollectResult>('/messages/x/collect', data)
