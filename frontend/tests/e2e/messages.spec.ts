import { expect, test } from '@playwright/test'

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
  await expect(page.getByText('今日题材')).toBeVisible()
  await expect(page.getByText('个股机会', { exact: true })).toBeVisible()
  await expect(page.getByText('AI算力').first()).toBeVisible()
  await expect(page.getByText('中际旭创')).toBeVisible()
  await expect(page.getByText('今日个股机会')).toBeVisible()
})

test('消息中心高分筛选保留高分机会', async ({ page }) => {
  await page.goto('/messages')

  await expect(page.getByText('三花智控')).toBeVisible()
  await page.getByRole('switch').click()
  await expect(page.getByText('中际旭创')).toBeVisible()
  await expect(page.getByText('三花智控')).not.toBeVisible()
})
