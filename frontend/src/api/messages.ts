import client from './client'
import type { MessageDaily, MessageOpportunity, MessageTopic } from '../types'

export const getDailyMessages = (params?: {
  trade_date?: string
  ensure_seed?: boolean
}) => client.get<MessageDaily>('/messages/daily', { params })

export const createMessageTopic = (data: Partial<MessageTopic> & { theme: string }) =>
  client.post<MessageTopic>('/messages/topics', data)

export const createMessageOpportunity = (
  data: Partial<MessageOpportunity> & { theme: string }
) => client.post<MessageOpportunity>('/messages/opportunities', data)
