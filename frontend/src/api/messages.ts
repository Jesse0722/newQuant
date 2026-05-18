import client from './client'
import type {
  MessageDaily,
  MessageDailyConclusion,
  MessageKeywordImportResult,
  MessageOpportunity,
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

export const listMessageKeywords = () =>
  client.get<MessageSeedKeyword[]>('/messages/keywords')

export const saveMessageKeyword = (data: MessageSeedKeywordInput) =>
  client.post<MessageSeedKeyword>('/messages/keywords', data)

export const importMessageKeywords = (data: { items: MessageSeedKeywordInput[] }) =>
  client.post<MessageKeywordImportResult>('/messages/keywords/import', data)

export const importDefaultMessageKeywords = () =>
  client.post<MessageKeywordImportResult>('/messages/keywords/import-default')
