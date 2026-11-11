import { test, expect, authenticate, STOCK_A, STOCK_B, chart, watchStock, fulfillJson, signal, NOW } from './support/fixtures'

test.beforeEach(async ({ page }) => authenticate(page))

test('观察池→雷达→提醒→关联计划→成交→复盘，写入只到隔离mock', async ({ page, api }) => {
  await page.goto('/pools/pool-a')
  await expect(page.getByText('样本甲', { exact: true }).first()).toBeVisible()
  await page.goto('/buy-radar')
  await page.getByRole('button', { name: '扫描买点' }).click()
  await expect(page.getByText('量价待人工确认').first()).toBeVisible()
  await page.getByRole('button', { name: '买点提醒', exact: true }).click()
  await page.getByRole('button', { name: '创建计划' }).click()
  const create = page.getByRole('dialog', { name: '新建交易计划' })
  await create.getByLabel('标题', { exact: true }).fill('工作流验收计划')
  await create.getByRole('button', { name: /确\s*定/ }).click()
  await expect(create).not.toBeVisible()
  await expect.poll(() => api.plans[0].alert_id).toBe('alert-a')
  await expect.poll(() => api.alerts[0].status).toBe('processed')
  await expect(page.getByText('股票累计现金流，非本计划归因盈亏').first()).toBeVisible()
  await page.getByRole('button', { name: '添加明细' }).first().click()
  const detail = page.getByRole('dialog', { name: '添加交易明细', exact: true })
  await detail.getByLabel('成交日期').fill('2026-11-10')
  await detail.getByLabel('成交日期').press('Enter')
  await detail.getByLabel('方向', { exact: true }).click()
  await page.locator('.ant-select-item-option-content').filter({ hasText: /^买入$/ }).click()
  await detail.getByLabel('成交价格').fill('10')
  await detail.getByLabel('成交数量（股）').fill('100')
  await detail.getByRole('button', { name: /确\s*定/ }).click()
  await expect.poll(() => api.details.length).toBe(1)
  await expect(page.getByText('1,000.00', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: /复\s*盘/ }).first().click()
  const review = page.getByRole('dialog', { name: '复盘', exact: true })
  await review.getByLabel('复盘总结').fill('样本证据不足，继续观察')
  await review.getByLabel('经验教训').fill('保留原文与执行记录')
  await review.getByRole('button', { name: /确\s*定/ }).click()
  await expect(page.getByText('样本证据不足，继续观察')).toBeVisible()
  await expect.poll(() => api.plans[0].review_pnl_snapshot).toBe(-1000)
})

test('首屏以外的计划深链精确定位，并可全部收起', async ({ page }) => {
  await page.goto('/plans/plan-old')
  await expect(page.getByText('已定位链接中的计划（不在当前分页）。')).toBeVisible()
  await expect(page.getByText('股票累计现金流，非本计划归因盈亏')).toHaveCount(1)
  const targetRow = page.getByRole('row').filter({ has: page.getByText('历史目标计划', { exact: true }) }).first()
  await targetRow.getByText('历史目标计划', { exact: true }).click()
  await expect(page.getByText('股票累计现金流，非本计划归因盈亏')).not.toBeVisible()
  await page.goto('/plans/missing-plan')
  await expect(page.getByRole('alert').filter({ hasText: '链接中的交易计划不存在' })).toBeVisible()
  await expect(page.getByText('股票累计现金流，非本计划归因盈亏')).not.toBeVisible()
})

test('切池时迟到的旧列表不会覆盖新池', async ({ page }) => {
  let release: () => void = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  let started: () => void = () => {}
  const requested = new Promise<void>(resolve => { started = resolve })
  await page.route('**/api/pools/pool-a/stocks?**', async route => { started(); await blocked; await fulfillJson(route, { items: [{ id: 'old-a', ts_code: STOCK_A, stock_name: '迟到的旧池股票' }], total: 1 }) })
  await page.goto('/pools/pool-a')
  await requested
  await page.getByText('观察样本B', { exact: true }).click()
  await expect(page.getByText('样本丙', { exact: true }).first()).toBeVisible()
  const lateResponse = page.waitForResponse(response => response.url().includes('/api/pools/pool-a/stocks'))
  release()
  await lateResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByText('迟到的旧池股票', { exact: true })).toHaveCount(0)
  await expect(page.getByText('样本丙', { exact: true }).first()).toBeVisible()
})

test('主升浪图缓存命中也作废另一股票的在途响应', async ({ page }) => {
  let release: () => void = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  let started: () => void = () => {}
  const requested = new Promise<void>(resolve => { started = resolve })
  await page.route(`**/api/stocks/${STOCK_B}/chart?**`, async route => { started(); await blocked; await fulfillJson(route, chart(STOCK_B)) })
  await page.goto('/pools/pool-wave')
  await expect(page.getByTestId('main-wave-chart')).toHaveAttribute('data-stock-code', STOCK_A)
  await page.getByRole('row').filter({ hasText: '样本乙' }).first().click()
  await requested
  await page.getByRole('row').filter({ hasText: '样本甲' }).first().click()
  await expect(page.getByTestId('main-wave-chart')).toHaveAttribute('data-stock-code', STOCK_A)
  const lateResponse = page.waitForResponse(response => response.url().includes(`/api/stocks/${STOCK_B}/chart`))
  release()
  await lateResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByTestId('main-wave-chart')).toHaveAttribute('data-stock-code', STOCK_A)
})

test('雷达切股后迟到图表响应不会覆盖当前股票', async ({ page }) => {
  await page.addInitScript(({ a, b, now }) => {
    localStorage.setItem('newQuant.buyRadar.lastScanResult.v1', JSON.stringify({ savedAt: now, activePoolId: 'pool-a', activeStrategyId: 'all', limitUpRange: null, selectedTsCode: a.ts_code,
      scanResultsByStrategy: { all: { signals: [a, b], scan_time: now, total: 2, triggered_count: 2, approaching_count: 0 } } }))
  }, { a: signal(STOCK_A), b: signal(STOCK_B), now: NOW })
  let release: () => void = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  let started: () => void = () => {}
  const requested = new Promise<void>(resolve => { started = resolve })
  await page.route(`**/api/stocks/${STOCK_A}/chart?**`, async route => { started(); await blocked; await fulfillJson(route, chart(STOCK_A)) })
  await page.goto('/buy-radar')
  await requested
  await page.getByRole('option', { name: '样本乙 600000.SH', exact: true }).click()
  await expect(page.getByTestId('signal-chart')).toHaveAttribute('data-stock-code', STOCK_B)
  const lateResponse = page.waitForResponse(response => response.url().includes(`/api/stocks/${STOCK_A}/chart`))
  release()
  await lateResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByTestId('signal-chart')).toHaveAttribute('data-stock-code', STOCK_B)
})


test('加载更多失败后重试同一页，切池时丢弃旧池后续页', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1400 })
  const pages: number[] = []
  let release: () => void = () => {}
  const blocked = new Promise<void>(resolve => { release = resolve })
  let secondPageStarted: () => void = () => {}
  const started = new Promise<void>(resolve => { secondPageStarted = resolve })
  await page.route('**/api/pools/pool-a/stocks?**', async route => {
    const pageNumber = Number(new URL(route.request().url()).searchParams.get('page'))
    pages.push(pageNumber)
    if (pageNumber === 1) return fulfillJson(route, { items: Array.from({ length: 6 }, (_, i) => ({ ...watchStock(i === 0 ? STOCK_A : `00010${i}.SZ`), stock_name: `首屏样本${i}` })), total: 7 })
    if (pages.filter(value => value === 2).length === 1) return fulfillJson(route, { message: '短暂分页失败' }, 503)
    secondPageStarted()
    await blocked
    return fulfillJson(route, { items: [{ ...watchStock(STOCK_B), stock_name: '旧池第二页' }], total: 7 })
  })
  await page.goto('/pools/pool-a')
  await page.getByRole('button', { name: /加载更多/ }).click()
  await expect(page.getByText('加载更多失败，请重试')).toBeVisible()
  await page.getByRole('button', { name: /加载更多/ }).click()
  await started
  expect(pages).toEqual([1, 2, 2])
  await page.getByText('观察样本B', { exact: true }).click()
  await expect(page.getByText('样本丙', { exact: true }).first()).toBeVisible()
  const lateResponse = page.waitForResponse(response => response.url().includes('/api/pools/pool-a/stocks') && new URL(response.url()).searchParams.get('page') === '2')
  release()
  await lateResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await expect(page.getByText('旧池第二页')).toHaveCount(0)
  await expect(page.getByText('样本丙', { exact: true }).first()).toBeVisible()
})
