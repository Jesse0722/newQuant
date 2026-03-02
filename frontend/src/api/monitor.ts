import client from './client'
import type { MonitorTemplate, MonitorRule } from '../types'

export const listTemplates = () => client.get<MonitorTemplate[]>('/monitor/templates')
export const getPoolRules = (poolId: string) => client.get<MonitorRule[]>(`/monitor/pools/${poolId}/rules`)
export const createPoolRule = (poolId: string, data: any) => client.post<MonitorRule>(`/monitor/pools/${poolId}/rules`, data)
export const getStockRules = (stockId: string) => client.get<MonitorRule[]>(`/monitor/stocks/${stockId}/rules`)
export const createStockRule = (stockId: string, data: any) => client.post<MonitorRule>(`/monitor/stocks/${stockId}/rules`, data)
export const updateRule = (ruleId: string, data: any) => client.put<MonitorRule>(`/monitor/rules/${ruleId}`, data)
export const deleteRule = (ruleId: string) => client.delete(`/monitor/rules/${ruleId}`)
export const triggerScan = () => client.post<{ task_id: string }>('/monitor/scan')
export const triggerPoolScan = (poolId: string) => client.post<{ task_id: string }>(`/monitor/scan/${poolId}`)
