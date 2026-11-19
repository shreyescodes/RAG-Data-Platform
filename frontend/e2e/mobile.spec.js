import { expect, test } from '@playwright/test'
import { ANSWER, ask, mockApi } from './support.js'

test('opens chats from the drawer and closes it afterwards', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  const drawerChat = page.getByRole('button', { name: 'Fund positions by quarter' })
  await expect(drawerChat).toBeHidden()

  await page.getByRole('button', { name: 'Open sidebar' }).click()
  await drawerChat.click()

  await expect(page.locator('.answer-text')).toHaveText(ANSWER)
  await expect(drawerChat).toBeHidden()
})

test('closes the drawer with Escape', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await page.getByRole('button', { name: 'Open sidebar' }).click()
  await expect(page.locator('#new-chat')).toBeVisible()
  await page.keyboard.press('Escape')

  await expect(page.locator('#new-chat')).toBeHidden()
})

test('fits the screen while answering', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')

  await ask(page, 'Top Berkshire holdings by value')
  await expect(page.locator('.answer-text')).toHaveText(ANSWER)

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})
