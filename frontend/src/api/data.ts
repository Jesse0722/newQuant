import client from './client'
import type { DataSummary } from '../types'

export const getDataSummary = () => client.get<DataSummary>('/data/summary')
