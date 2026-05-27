import client from './client'
import type { IndustryDailyReport, IndustryReportCandidate } from '../types'

export const getIndustryDailyReport = (params?: { trade_date?: string }) =>
  client.get<IndustryDailyReport | null>('/industry-reports/daily', { params })

export const generateIndustryReport = (data: {
  trade_date?: string
  refresh_seeds?: boolean
  use_llm?: boolean
}) => client.post<IndustryDailyReport>('/industry-reports/generate', data)

export const getIndustryReportCandidates = (params?: { trade_date?: string }) =>
  client.get<IndustryReportCandidate[]>('/industry-reports/candidates', { params })

export const addIndustryCandidateToPool = (candidateId: string) =>
  client.post(`/industry-reports/candidates/${candidateId}/add-to-pool`)
