import { expect, test } from '@playwright/test'
import { failedResult } from '../src/test/fixtures.js'
import { ANSWER, ask, mockApi } from './support.js'

const answers = (page) => page.locator('.answer-text')

test('answers a question and shows how it got there', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await ask(page, 'Top Berkshire holdings by value')

  await expect(answers(page)).toHaveText(ANSWER)
  await expect(page.locator('.asked')).toHaveText('Top Berkshire holdings by value')
  await expect(page.getByRole('heading', { name: 'Fact check' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sources' })).toBeVisible()
  await expect(page.getByLabel('Ask a question about the financial data')).toHaveValue('')
})

test('keeps a follow-up in the same conversation', async ({ page }) => {
  const asked = await mockApi(page)
  await page.goto('/')

  await ask(page, 'Top Berkshire holdings by value')
  await expect(answers(page)).toHaveCount(1)
  await ask(page, 'And the smallest one?')

  await expect(answers(page)).toHaveCount(2)
  expect(asked[1].conversation_id).toBe(asked[0].conversation_id)
})

test('starts a separate conversation with New chat', async ({ page }) => {
  const asked = await mockApi(page)
  await page.goto('/')
  await ask(page, 'Top Berkshire holdings by value')
  await expect(answers(page)).toHaveCount(1)

  await page.getByRole('button', { name: 'New chat' }).click()

  await expect(page.getByRole('heading', { name: 'Ask the data.' })).toBeVisible()
  await expect(answers(page)).toHaveCount(0)
  await ask(page, 'A different question')
  await expect(answers(page)).toHaveCount(1)
  expect(asked[1].conversation_id).not.toBe(asked[0].conversation_id)
})

test('reopens a saved chat without asking the model again', async ({ page }) => {
  const asked = await mockApi(page)
  await page.goto('/')

  await page.getByRole('button', { name: 'Fund positions by quarter' }).click()

  await expect(answers(page)).toHaveText(ANSWER)
  expect(asked).toHaveLength(0)
})

test('explains a question it cannot answer', async ({ page }) => {
  await mockApi(page, { result: failedResult })
  await page.goto('/')

  await ask(page, 'Drop all tables')

  await expect(page.getByRole('alert')).toContainText(failedResult.error)
})

test('remembers a collapsed sidebar', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const newChat = page.locator('#new-chat')

  await page.getByRole('button', { name: 'Close sidebar' }).click()
  await expect(newChat).toBeHidden()
  await page.reload()

  await expect(newChat).toBeHidden()
  await page.getByRole('button', { name: 'Open sidebar' }).click()
  await expect(newChat).toBeVisible()
})

test('shows the observability dashboard', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await page.getByRole('link', { name: 'Observability' }).click()

  await expect(page.getByLabel('Key metrics')).toBeVisible()
})
