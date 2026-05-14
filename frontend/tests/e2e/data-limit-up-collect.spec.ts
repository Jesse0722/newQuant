import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/$/)
})

test('数据管理页可触发涨停筛选请求', async ({ page }) => {
  const collectApi = page.waitForResponse(
    (resp) =>
      resp.url().includes('/api/strategy/limit-up/collect') &&
      resp.request().method() === 'POST'
  )

  await page.goto('/data')
  await page.getByRole('button', { name: '执行涨停筛选' }).click()

  const response = await collectApi
  expect(response.ok()).toBeTruthy()

  const body = await response.json()
  expect(body).toHaveProperty('added')
  expect(body).toHaveProperty('updated')
  expect(body).toHaveProperty('skipped')
})

test('涨停筛选接口失败时显示错误提示', async ({ page }) => {
  await page.route('**/api/strategy/limit-up/collect**', async (route) => {
    await route.fulfill({
      status: 500,
      contentType: 'application/json',
      body: JSON.stringify({ message: '模拟失败' }),
    })
  })

  await page.goto('/data')
  await page.getByRole('button', { name: '执行涨停筛选' }).click()

  await expect(page.getByText('模拟失败')).toBeVisible()
})
