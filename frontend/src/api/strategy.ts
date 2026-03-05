import client from './client'

export interface ScreenTemplate {
  id: string
  name: string
  default_params: Record<string, any>
}

export interface ScreenCondition {
  template_id: string
  params: Record<string, any>
}

export interface ScreenResult {
  task_id: string
  status: string
  progress: number
  message: string
  ts_codes: string[]
  stock_names: Record<string, string>
  total: number
}

export const getScreenTemplates = () =>
  client.get<ScreenTemplate[]>('/strategy/templates')

export const runIndicatorScreen = (data: {
  scope: string
  conditions: ScreenCondition[]
  logic?: string
}) => client.post<{ task_id: string }>('/strategy/screen', data)

export const runAiScreen = (data: { description: string; scope?: string }) =>
  client.post<{ task_id: string }>('/strategy/ai-screen', data)

export const getScreenResult = (taskId: string) =>
  client.get<ScreenResult>(`/strategy/result/${taskId}`)
