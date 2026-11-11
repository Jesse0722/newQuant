import { test as base, expect, type Page, type Route } from '@playwright/test'
import type { TradePlan, TradeDetail, WatchStock, Pool, MessageOpportunity, MessageDaily, IndustryDailyReport, MessageAgentDaily, StockChartDataWithMarks, BuySignal } from '../../../src/types'

export const NOW = '2026-11-11T01:00:00Z'
export const STOCK_A = '000001.SZ'
export const STOCK_B = '600000.SH'
export const STOCK_C = '000002.SZ'
export const stockNames: Record<string, string> = { [STOCK_A]: '样本甲', [STOCK_B]: '样本乙', [STOCK_C]: '样本丙' }
export const pools: Pool[] = [
  { id: 'pool-a', name: '观察样本A', description: '', stock_count: 2, created_at: NOW, updated_at: NOW },
  { id: 'pool-b', name: '观察样本B', description: '', stock_count: 1, created_at: NOW, updated_at: NOW },
  { id: 'pool-wave', name: '主升浪样本库', description: '', stock_count: 2, created_at: NOW, updated_at: NOW },
]
export const watchStock = (code: string, poolId = 'pool-a'): WatchStock => ({
  id: `${poolId}-${code}`, pool_id: poolId, ts_code: code, stock_name: stockNames[code] || code,
  added_at: NOW, source: 'manual', pinned: false, added_price: 10, latest_price: 11, pct_chg: 1, note: '', monitor_status: 'active', created_at: NOW,
})
export const chart = (code: string): StockChartDataWithMarks => ({
  basic: { ts_code: code, name: stockNames[code] || code, industry: '样本行业', area: '测试', market: '主板', list_date: '20000101' },
  quotes: Array.from({ length: 30 }, (_, i) => ({ date: `202610${String(i + 1).padStart(2, '0')}`, open: 10, high: 12, low: 9, close: 11, vol: 1000, amount: 10000, pct_chg: 1 })),
  indicators: { ma5: Array(30).fill(10), ma10: Array(30).fill(10), ma20: Array(30).fill(10), rsi: Array(30).fill(50), macd: { dif: Array(30).fill(0.2), dea: Array(30).fill(0.1), histogram: Array(30).fill(0.1) } },
  signal_marks: [],
})
export const signal = (code: string): BuySignal => ({
  ts_code: code, name: stockNames[code], strategy_id: 'test-strategy', strategy_name: '样本策略', signal_status: 'confirmed_triggered', signal_score: 80,
  life_line_date: '20261110', life_line_price: 10, days_since_life_line: 1, latest_close: 11, latest_pct_chg: 1,
  phase2_high: 12, pullback_pct: 2, met_conditions: ['量价待人工确认'], unmet_conditions: [], rsi: 50, macd_hist: 0.1, volume_ratio: 1,
})
export const makePlan = (id = 'plan-new'): TradePlan => ({
  id, title: id === 'plan-old' ? '历史目标计划' : '样本交易计划', status: 'pending', created_at: NOW, updated_at: NOW,
  stocks: [{ id: `${id}-stock`, plan_id: id, ts_code: STOCK_A, stock_name: stockNames[STOCK_A], risk_level: 2, details: [] }],
  pnl_summary: { total_buy_amount: 0, total_sell_amount: 0, total_commission: 0, total_stamp_tax: 0, net_pnl: 0, holding_quantity: 0 },
})
export const opportunity = (id: string, code: string, score = 90): MessageOpportunity => ({
  id, trade_date: '20261111', theme: '样本题材', ts_code: code, stock_name: stockNames[code], opportunity_score: score,
  heat_score: 60, credibility_score: 85, risk_score: 20, evidence_score: 80, mapping_confidence: 90,
  action_suggestion: 'watch', reason: '有来源的研究候选', catalysts: ['样本公告'], risks: ['待人工核实'],
  source_platforms: ['公告'], source_links: ['https://example.org/evidence'], review_status: 'needs_review', generated_by: 'rule', status: 'active', created_at: NOW,
})
export const evidence = (opportunityId = 'opp-a') => [{
  id: `${opportunityId}-link`, opportunity_id: opportunityId, evidence_id: `${opportunityId}-evidence`, created_at: NOW,
  evidence: { id: `${opportunityId}-evidence`, source_item_id: 'source-1', trade_date: '20261111', channel: 'official',
    evidence_text: `${opportunityId} 原文：样本公司披露合作仍待验证。`, stance: 'contradiction', quality_score: 80, credibility_score: 90, confidence: 85,
    extraction_method: 'rule', extractor_name: 'fixture', extractor_version: '1', raw_json: {}, status: 'active', created_at: NOW,
    source_item: { id: 'source-1', source_name: '样本公告', url: 'https://example.org/evidence', content: '样本原文', channel: 'official' } },
}]
export const industry: IndustryDailyReport = {
  id: 'report-1', trade_date: '20261111', title: '样本产业链日报', headline: '证据待验证', report_json: {}, prompt_version: 'test', status: 'completed', created_at: NOW, updated_at: NOW,
  candidates: [{ id: 'candidate-1', report_id: 'report-1', trade_date: '20261111', ts_code: STOCK_A, stock_name: stockNames[STOCK_A], theme: '样本题材',
    path_json: [{ source: '样本需求', relation: '关联', target: '样本甲', strength: 0.8, confidence: 0.8 }],
    evidence_json: [{ evidence_id: 'industry-evidence', evidence_text: '产业原文：订单仍待公告核实', evidence_kind: 'quote', source_name: '样本官方公告', url: 'https://example.org/industry', stance: 'contradiction', confidence: 0.8 }],
    path_score: 60, evidence_score: 70, heat_score: 50, crowding_score: 20, risk_score: 30, final_score: 65, grade: 'medium', reason: '仅作观察', risks: ['待核实'], created_at: NOW }],
}
export const agentDaily: MessageAgentDaily = {
  trade_date: '20261111', generated_at: NOW, model_provider: 'rule', model_name: 'fixture', headline: '样本证据日报', summary: '仅作研究支持', evidence_coverage: { evidence_count: 1, candidate_count: 1, theme_count: 1 }, risk_flags: ['待核实'], next_actions: ['观察'],
  candidates: [{ opportunity_id: 'opp-a', theme: '样本题材', ts_code: STOCK_A, stock_name: stockNames[STOCK_A], opportunity_score: 90, evidence_score: 80, risk_score: 20, review_status: 'needs_review', evidence_count: 1, conclusion: '等待更多证据' }],
}
export interface MockState {
  plans: TradePlan[]
  details: TradeDetail[]
  opportunities: MessageOpportunity[]
  alerts: Array<Record<string, unknown>>
  calls: Array<{ method: string; path: string; url: string; body: Record<string, unknown> }>
  unexpected: string[]
}
export const fulfillJson = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

export async function installApiMock(page: Page): Promise<MockState> {
  const state: MockState = { plans: [makePlan()], details: [], opportunities: [opportunity('opp-a', STOCK_A), opportunity('opp-b', STOCK_B, 60)], alerts: [], calls: [], unexpected: [] }
  const enrich = (plan: TradePlan): TradePlan => {
    const codes = plan.stocks.map(stock => stock.ts_code)
    const details = state.details.filter(detail => codes.includes(detail.ts_code))
    const buy = details.filter(row => row.direction === 'buy').reduce((sum, row) => sum + row.amount, 0)
    const sell = details.filter(row => row.direction === 'sell').reduce((sum, row) => sum + row.amount, 0)
    return { ...plan, actual_pnl: sell - buy, pnl_scope: 'stock_lifetime', pnl_summary: { total_buy_amount: buy, total_sell_amount: sell, total_commission: 0, total_stamp_tax: 0, net_pnl: sell - buy, holding_quantity: details.reduce((sum, row) => sum + (row.direction === 'buy' ? row.quantity : -row.quantity), 0) }, stocks: plan.stocks.map(stock => ({ ...stock, details: details.filter(detail => detail.ts_code === stock.ts_code) })) }
  }
  await page.route(url => !['127.0.0.1', 'localhost'].includes(url.hostname), route => route.abort('blockedbyclient'))
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    let body: Record<string, unknown> = {}
    try { body = request.postDataJSON() || {} } catch { /* empty or multipart body */ }
    state.calls.push({ method, path, url: url.href, body })
    if (path === '/api/dashboard') return fulfillJson(route, { trade_date: '20261111', resolved_by: 'query', sectors: [], ladder: [] })
    if (path === '/api/sync/tasks/recent') return fulfillJson(route, { items: [] })
    if (path === '/api/pools' && method === 'GET') return fulfillJson(route, pools)
    if (path === '/api/pools/core-watch/codes') return fulfillJson(route, { pool_id: 'pool-a', ts_codes: [] })
    if (path === '/api/pools/core-watch/toggle') return fulfillJson(route, { starred: body.starred, ts_code: body.ts_code, pool_id: 'pool-a' })
    if (path === '/api/pools/all-stocks') return fulfillJson(route, [STOCK_A, STOCK_B, STOCK_C].map(code => ({ ts_code: code, stock_name: stockNames[code], pool_id: 'pool-a', pool_name: '观察样本A' })))
    const poolStocks = path.match(/^\/api\/pools\/([^/]+)\/stocks$/)
    if (poolStocks && method === 'GET') {
      const codes = poolStocks[1] === 'pool-b' ? [STOCK_C] : [STOCK_A, STOCK_B]
      return fulfillJson(route, { items: codes.map(code => watchStock(code, poolStocks[1])), total: codes.length })
    }
    const stockChart = path.match(/^\/api\/stocks\/([^/]+)\/chart$/)
    if (stockChart) return fulfillJson(route, chart(stockChart[1]))
    if (/^\/api\/stocks\/[^/]+\/ai-analysis$/.test(path)) return fulfillJson(route, { analysis: null })
    if (/^\/api\/stocks\/[^/]+\/alerts$/.test(path)) return fulfillJson(route, [])
    const detailPath = path.match(/^\/api\/stocks\/([^/]+)\/details$/)
    if (detailPath && method === 'POST') {
      const detail: TradeDetail = { id: `detail-${state.details.length + 1}`, ts_code: detailPath[1], trade_date: String(body.trade_date), trade_time: String(body.trade_time || ''), direction: String(body.direction), price: Number(body.price), quantity: Number(body.quantity), amount: Number(body.price) * Number(body.quantity), commission: 0, stamp_tax: 0, created_at: NOW }
      state.details.push(detail); return fulfillJson(route, detail, 201)
    }
    if (detailPath) return fulfillJson(route, state.details.filter(detail => detail.ts_code === detailPath[1]))
    if (path === '/api/alerts/pending-count') return fulfillJson(route, { count: state.alerts.filter(row => row.status === 'pending').length })
    if (path === '/api/alerts') { const rows = state.alerts.filter(row => row.status === url.searchParams.get('status')); return fulfillJson(route, { items: rows, total: rows.length }) }
    if (path === '/api/strategy/buy-strategies') return fulfillJson(route, [{ id: 'test-strategy', name: '样本策略', description: '研究确认', default_params: {} }])
    if (path === '/api/strategy/scan-buy-signals-task' && method === 'POST') {
      state.alerts = [{ id: 'alert-a', ts_code: STOCK_A, stock_name: stockNames[STOCK_A], status: 'pending', strategy_name: '样本策略', trigger_date: '20261111', buy_signal: signal(STOCK_A), scan_meta: {} }]
      return fulfillJson(route, { task_id: 'scan-1' })
    }
    if (path.startsWith('/api/strategy/scan-buy-signals-task/')) return fulfillJson(route, { task_id: 'scan-1', status: 'completed', progress: 1, message: '扫描完成', result: { signals: [signal(STOCK_A), signal(STOCK_B)], scan_time: NOW, total: 2, triggered_count: 2, approaching_count: 0, strategy_id: 'test-strategy' } })
    if (path === '/api/plans' && method === 'GET') { const items = state.plans.filter(plan => !url.searchParams.get('status') || plan.status === url.searchParams.get('status')); return fulfillJson(route, { items: items.map(enrich), total: items.length }) }
    if (path === '/api/plans' && method === 'POST') {
      const plan: TradePlan = { ...makePlan(`plan-created-${state.plans.length}`), title: String(body.title), alert_id: typeof body.alert_id === 'string' ? body.alert_id : undefined, stocks: (body.stocks as Array<{ ts_code: string; risk_level: number }>).map((stock, i) => ({ id: `plan-stock-${i}`, plan_id: 'plan-created', ...stock, stock_name: stockNames[stock.ts_code], details: [] })) }
      if (body.alert_id) state.alerts.forEach(alert => { if (alert.id === body.alert_id) alert.status = 'processed' })
      state.plans.unshift(plan); return fulfillJson(route, enrich(plan), 201)
    }
    const planPath = path.match(/^\/api\/plans\/([^/]+)(\/review)?$/)
    if (planPath) {
      const plan = state.plans.find(row => row.id === planPath[1]) || (planPath[1] === 'plan-old' ? makePlan('plan-old') : null)
      if (!plan) return fulfillJson(route, { message: '计划不存在' }, 404)
      if (method === 'PUT') {
        if (planPath[2]) Object.assign(plan, body, { review_pnl_snapshot: enrich(plan).actual_pnl })
        else Object.assign(plan, body)
      }
      return fulfillJson(route, enrich(plan))
    }
    if (path === '/api/messages/daily') { const daily: MessageDaily = { trade_date: '20261111', generated_at: NOW, stats: { topic_count: 1, opportunity_count: state.opportunities.length, top_score: 90 }, topics: [{ id: 'topic-1', trade_date: '20261111', theme: '样本题材', lifecycle_stage: 'early', sentiment: 'positive', heat_score: 65, credibility_score: 85, crowding_score: 20, source_platforms: ['公告'], tags: [], created_at: NOW, updated_at: NOW }], opportunities: state.opportunities }; return fulfillJson(route, daily) }
    if (path === '/api/industry-reports/daily') return fulfillJson(route, industry)
    if (path === '/api/messages/agent-daily') return fulfillJson(route, agentDaily)
    if (path === '/api/message-agents/runs') return fulfillJson(route, [])
    const oppPath = path.match(/^\/api\/messages\/opportunities\/([^/]+)\/(evidence|review|accept|dismiss)$/)
    if (oppPath) {
      if (oppPath[2] === 'evidence') return fulfillJson(route, evidence(oppPath[1]))
      const row = state.opportunities.find(item => item.id === oppPath[1])!
      Object.assign(row, body, { review_status: oppPath[2] === 'review' ? 'reviewed' : oppPath[2] === 'accept' ? 'accepted' : 'dismissed' })
      if (oppPath[2] === 'dismiss') { row.status = 'dismissed'; state.opportunities = state.opportunities.filter(item => item !== row) }
      return fulfillJson(route, row)
    }
    if (path === '/api/messages/x/collect') return fulfillJson(route, { imported: { created_count: 1, skipped_count: 0, aggregation: { opportunity_count: 2 } } })
    if (path === '/api/data/summary') return fulfillJson(route, { stock_count: 3, total_quotes: 90, quote_date_range: { min: '20261001', max: '20261111' }, last_sync_at: '20261111' })
    if (path === '/api/data/sync-history') return fulfillJson(route, [])
    if (path === '/api/data/sync-overview') return fulfillJson(route, { days: 7, total: { tasks: 0, success: 0, failed: 0, skipped: 0 }, by_task_type: [] })
    if (path === '/api/data/provider') return fulfillJson(route, { provider: 'composite' })
    if (path === '/api/data/tushare-check') return fulfillJson(route, { token_configured: false, proxy_configured: false, api_test: 'ok', rows_returned: 5 })
    if (path === '/api/sync/full-market') return fulfillJson(route, { task_id: 'sync-1' })
    if (path.startsWith('/api/sync/status/')) return fulfillJson(route, { task_id: path.split('/').pop(), status: 'completed', progress: 1, message: '历史回补完成', result: { success_count: 2, failed_count: 0, outcome: 'complete', completed_dates: ['20261110'] } })
    if (path === '/api/strategy/limit-up/collect') return fulfillJson(route, { added: 1, updated: 0, skipped: 0, dates_processed: ['20261111'], errors: [] })
    if (path === '/api/strategy/templates' || path === '/api/strategy/limit-up-templates') return fulfillJson(route, [{ id: 'ma_support', name: '均线支撑', default_params: {} }])
    if (path === '/api/market/sectors') return fulfillJson(route, [])
    if (path === '/api/strategy/main-wave-screen') return fulfillJson(route, { task_id: 'wave-screen-1' })
    if (path.startsWith('/api/strategy/result/')) return fulfillJson(route, { task_id: 'wave-screen-1', status: 'completed', progress: 1, message: '研究扫描完成', ts_codes: [STOCK_A], stock_names: stockNames, items: [{ ts_code: STOCK_A, stock_name: stockNames[STOCK_A], total_score: 80, status: 'watching', entry_score: 60, entry_stage: 'watching', data_quality: { score: 80, warnings: [] } }], total: 1 })
    if (/^\/api\/pools\/[^/]+\/stocks\/batch$/.test(path)) return fulfillJson(route, { added: 1, skipped: 0, errors: [] })
    if (path === '/api/market/main-wave/analyze-batch') return fulfillJson(route, { total: 2, items: [STOCK_A, STOCK_B].map(code => ({ ts_code: code, name: stockNames[code], status: 'watching', total_score: 65, scores: { trend: 20, structure: 20, pullback_repair: 10, sector_resonance: 5 }, metrics: {}, reasons: {} })) })
    if (/^\/api\/market\/stocks\/[^/]+\/main-wave$/.test(path)) return fulfillJson(route, { ts_code: path.split('/')[4], name: '样本', status: 'watching', total_score: 65, metrics: {}, reasons: {} })
    if (path === '/api/market/main-wave/sectors/backfill/status') return fulfillJson(route, { required_trade_date: '20261111', total: 0, ready: 0, stale: 0, missing: 0, sectors: [], items: [] })
    state.unexpected.push(`${method} ${path}`)
    return fulfillJson(route, { message: `未定义的隔离测试请求：${method} ${path}` }, 404)
  })
  return state
}

export async function authenticate(page: Page) {
  await page.addInitScript(() => localStorage.setItem('newquant:auth', JSON.stringify({ username: 'admin', loginAt: '2026-11-11T01:00:00Z' })))
}
export const test = base.extend<{ api: MockState }>({
  api: [async ({ page }, use) => { const state = await installApiMock(page); const errors: string[] = []; page.on('pageerror', error => errors.push(error.message)); await use(state); expect(errors, '浏览器不得出现未处理异常').toEqual([]); expect(state.unexpected, '所有业务API必须显式mock，不能使用真实服务').toEqual([]) }, { auto: true }],
})
export { expect }
