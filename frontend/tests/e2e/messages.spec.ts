import { expect, test } from './support/fixtures'

test.beforeEach(async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill('admin123')
  await page.getByTestId('login-submit').click()
  await expect(page).toHaveURL(/\/$/)
})

test('消息中心展示今日题材与个股机会', async ({ page }) => {
  await page.goto('/messages')

  await expect(page.getByRole('heading', { name: '题材与个股机会' })).toBeVisible()
  await expect(page.getByText('今日题材', { exact: true })).toBeVisible()
  await expect(page.getByText('个股机会', { exact: true })).toBeVisible()
  await expect(page.getByText('样本题材').first()).toBeVisible()
  await expect(page.getByText('样本甲', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('今日个股机会')).toBeVisible()
})

test('消息中心高分筛选保留高分机会', async ({ page }) => {
  await page.goto('/messages')

  await expect(page.getByText('样本乙')).toBeVisible()
  await page.getByRole('switch').click()
  await expect(page.getByText('样本甲', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('样本乙')).not.toBeVisible()
})
