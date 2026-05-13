import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.context().clearCookies()
  await page.goto('/login')
  await page.evaluate(() => localStorage.clear())
})

test('未登录访问首页会跳转登录页', async ({ page }) => {
  await page.goto('/')

  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: '登录工作台' })).toBeVisible()
})

test('错误账号密码无法登录', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill('wrong-password')
  await page.getByTestId('login-submit').click()

  await expect(page.getByText('账号或密码错误')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)
})

test('默认账号登录成功并保持会话', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByTestId('login-submit').click()

  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible()

  await page.reload()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '仪表盘' })).toBeVisible()
})
