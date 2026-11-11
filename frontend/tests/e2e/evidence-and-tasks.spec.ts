import { test, expect, authenticate, fulfillJson, STOCK_A, NOW } from './support/fixtures'

test.beforeEach(async ({ page }) => authenticate(page))

test('产业链和Agent日报只显示候选关联证据，缺失时明确提示', async ({ page, api }) => {
  await page.goto('/messages')
  await page.getByRole('button', { name: '查看产业链证据', exact: true }).click()
  let dialog = page.getByRole('dialog').filter({ hasText: '产业链证据' })
  await expect(dialog.getByText('产业原文：订单仍待公告核实')).toBeVisible()
  await expect(dialog.getByRole('link', { name: '原文', exact: true })).toHaveAttribute('href', 'https://example.org/industry')
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await page.getByRole('button', { name: '查看日报证据', exact: true }).click()
  dialog = page.getByRole('dialog').filter({ hasText: '日报证据' })
  await expect(dialog.getByText('opp-a 原文：样本公司披露合作仍待验证。')).toBeVisible()
  expect(api.calls.filter(call => call.path.includes('/evidence')).map(call => call.path)).toEqual(['/api/messages/opportunities/opp-a/evidence'])
  await dialog.getByRole('button', { name: /确\s*定/ }).click()
  await page.route('**/api/messages/opportunities/opp-a/evidence', route => fulfillJson(route, []))
  await page.getByRole('button', { name: '查看日报证据', exact: true }).click()
  await expect(page.getByText('该候选暂无关联证据，不能据此确认结论')).toBeVisible()
})

test('机会证据复核与填写原因驳回，取消不产生写请求', async ({ page, api }) => {
  await page.goto('/messages')
  await page.getByRole('button', { name: '查看机会证据', exact: true }).first().click()
  const evidence = page.getByRole('dialog').filter({ hasText: '采纳加入观察' })
  await expect(evidence.getByText('opp-a 原文：样本公司披露合作仍待验证。')).toBeVisible()
  await evidence.getByRole('button', { name: '标记复核' }).click()
  await expect.poll(() => api.opportunities[0].review_status).toBe('reviewed')
  await evidence.getByRole('button', { name: /驳\s*回/ }).click()
  const dismiss = page.getByRole('dialog', { name: '填写驳回原因' })
  await expect(dismiss.getByRole('button', { name: /确\s*定/ })).toBeDisabled()
  await dismiss.getByLabel('驳回原因').fill('官方原文与产业映射不一致')
  await dismiss.getByRole('button', { name: /取\s*消/ }).click()
  expect(api.calls.filter(call => call.path.endsWith('/dismiss'))).toHaveLength(0)
  await evidence.getByRole('button', { name: /驳\s*回/ }).click()
  await dismiss.getByLabel('驳回原因').fill('官方原文与产业映射不一致')
  await dismiss.getByRole('button', { name: /确\s*定/ }).click()
  await expect.poll(() => api.calls.find(call => call.path.endsWith('/dismiss'))?.body.review_reason).toBe('官方原文与产业映射不一致')
})

test('全市场任务遇临时断网后恢复，顶部通知保留结果入口', async ({ page }) => {
  let requests = 0
  await page.route('**/api/sync/status/sync-1', async route => {
    requests += 1
    if (requests <= 2) return route.abort('failed')
    return fulfillJson(route, { task_id: 'sync-1', status: 'completed', progress: 1, message: '恢复后处理完成', result: { success_count: 7, outcome: 'complete' } })
  })
  await page.goto('/data')
  await page.getByRole('button', { name: /全市场同步$/ }).click()
  await expect(page.getByText('状态查询暂时失败，正在重试；后台同步可能仍在执行')).toBeVisible()
  await expect.poll(() => requests, { timeout: 12000 }).toBeGreaterThan(2)
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('恢复后处理完成').first()).toBeVisible()
  await page.getByRole('button').filter({ hasText: '全市场历史回补' }).click()
  await expect(page).toHaveURL(/\/data\?task=sync-1/)
  const result = page.getByRole('dialog', { name: '全市场历史回补' })
  await expect(result.getByText('成功', { exact: true })).toBeVisible()
  await expect(result.getByText('7', { exact: true })).toBeVisible()
})

test('后台任务真正失败才结束，失败原因仍可查看', async ({ page }) => {
  await page.addInitScript(({ now, code }) => localStorage.setItem('newQuant.notificationCenter.items', JSON.stringify([{ id: 'buy_scan:failed-scan', kind: 'buy_scan', status: 'running', title: '失败扫描样本', description: '等待', createdAt: now, updatedAt: now, read: false, taskId: 'failed-scan', link: '/buy-radar', meta: { tsCode: code } }])), { now: NOW, code: STOCK_A })
  await page.route('**/api/strategy/scan-buy-signals-task/failed-scan', route => fulfillJson(route, { status: 'failed', progress: 0, message: '样本数据覆盖不足，任务未评分' }))
  await page.goto('/data')
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('样本数据覆盖不足，任务未评分').first()).toBeVisible()
  await page.getByRole('button').filter({ hasText: '失败扫描样本' }).click()
  await expect(page.getByRole('dialog', { name: '失败扫描样本' }).getByText('样本数据覆盖不足，任务未评分')).toBeVisible()
})

test('跨进程定时任务和数据源错误进入通知并按版本去重', async ({ page }) => {
  await page.route('**/api/sync/tasks/recent?**', route => fulfillJson(route, { items: [{ id: 'scheduled:1', task_id: 'scheduled:1', type: 'scheduled_latest_kline_sync', status: 'failed', message: '行情权限失效，请检查Token', created_at: NOW, updated_at: NOW, source: 'scheduler', link: '/data', result: { failed_count: 2 } }] }))
  await page.goto('/data')
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('行情权限失效，请检查Token')).toBeVisible()
  await page.getByRole('button', { name: '全部已读' }).click()
  await page.getByRole('button', { name: '清理已读' }).click()
  await page.reload()
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('行情权限失效，请检查Token')).toHaveCount(0)
})

test('主升浪扫描候选可加入观察池，独立mock验证结果路径', async ({ page, api }) => {
  await page.goto('/strategy?tab=main_wave')
  await page.getByRole('button', { name: /执行主升浪选股$/ }).click()
  await expect(page.getByText('样本甲', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: '加入股票池', exact: true }).first().click()
  const add = page.getByRole('dialog', { name: '添加到股票池', exact: true })
  await add.getByRole('combobox').click()
  await page.locator('.ant-select-item-option-content').filter({ hasText: /^观察样本A/ }).click()
  await add.getByRole('button', { name: '确认添加', exact: true }).click()
  await expect.poll(() => api.calls.find(call => call.path === '/api/pools/pool-a/stocks/batch')?.body.ts_codes).toEqual([STOCK_A])
})

for (const kind of ['scan', 'backtest'] as const) {
  test(`雷达${kind === 'scan' ? '扫描' : '回测'}临时查询失败后继续跟踪终态`, async ({ page }) => {
    let attempts = 0
    const taskId = `${kind}-retry`
    const endpoint = kind === 'scan' ? 'scan-buy-signals-task' : 'strategy-backtest'
    await page.route(`**/api/strategy/${endpoint}/${taskId}`, async route => {
      attempts += 1
      if (attempts === 1) return fulfillJson(route, { message: '临时网络异常' }, 503)
      return fulfillJson(route, { task_id: taskId, status: 'completed', progress: 1, message: '重试完成', result: kind === 'scan'
        ? { signals: [{ ts_code: STOCK_A, name: '样本甲', strategy_id: 'test-strategy', signal_status: 'confirmed_triggered', signal_score: 80, met_conditions: ['重试后证据'], unmet_conditions: [] }], scan_time: NOW, total: 1, triggered_count: 1, approaching_count: 0 }
        : { strategy_id: 'test-strategy', total_signals: 1, win_rate_1d: 0, win_rate_3d: 0, win_rate_5d: 0, avg_return_1d: -1, avg_return_3d: -2, avg_return_5d: -7, worst_return_5d: -7, max_drawdown: null, profit_factor: 0, disclaimer: '信号收盘后验收益，不含成本', signals: [] } })
    })
    await page.goto(`/buy-radar?task=${taskId}&kind=${kind}&pool=pool-a&strategy=test-strategy`)
    await expect(page.getByText(/状态查询暂时失败/).first()).toBeVisible()
    if (kind === 'scan') await expect(page.getByText('重试后证据')).toBeVisible()
    else {
      await expect(page.getByText('最差单笔5日收益')).toBeVisible()
      await expect(page.getByText('信号收盘后验收益，不含成本')).toBeVisible()
      await expect(page.getByText('最大回撤(5日)')).toHaveCount(0)
    }
    expect(attempts).toBeGreaterThanOrEqual(2)
  })
}

test('浏览器存储额度异常不会让已提交同步变成失败', async ({ page }) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key === 'newQuant.notificationCenter.items') throw new DOMException('quota', 'QuotaExceededError')
      return original.call(this, key, value)
    }
  })
  await page.goto('/data')
  await page.getByRole('button', { name: /全市场同步$/ }).click()
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('历史回补完成').first()).toBeVisible()
  await expect(page.getByText('全市场历史回补', { exact: true }).first()).toBeVisible()
})

test('刷新后没有持久任务ID的采集结果标为待确认，不冒充任务失败', async ({ page }) => {
  await page.addInitScript(now => localStorage.setItem('newQuant.notificationCenter.items', JSON.stringify([{ id: 'collection:restored', kind: 'collection', status: 'running', title: '页面内采集', description: '处理中', createdAt: now, updatedAt: now, read: false, link: '/messages' }])), NOW)
  await page.goto('/data')
  await page.getByRole('button', { name: '任务消息中心' }).click()
  await expect(page.getByText('待确认', { exact: true })).toBeVisible()
  await expect(page.getByText('页面已重新载入，执行结果尚未确认，请查看来源记录')).toBeVisible()
})
