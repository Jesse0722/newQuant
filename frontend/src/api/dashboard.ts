import client from './client'
import type { DashboardData } from '../types'

export const getDashboard = (params?: { trade_date?: string }) =>
  client.get<DashboardData>('/dashboard', { params })
