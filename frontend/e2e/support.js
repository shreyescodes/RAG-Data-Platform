import { history, metricsRecent, metricsSummary, metricsTimeseries, successResult } from '../src/test/fixtures.js'

export const ANSWER = successResult.answer

const stage = (name, status) =>
  `event: stage\ndata: ${JSON.stringify({ stage: name, status })}\n\n`

function answerStream(result) {
  return [
    stage('retrieval', 'started'),
    stage('retrieval', 'completed'),
    `event: result\ndata: ${JSON.stringify(result)}\n\n`,
  ].join('')
}

/** Answers every API call in the browser, so no backend or LLM is needed. */
export async function mockApi(page, { result = successResult } = {}) {
  const asked = []
  const json = (route, body) => route.fulfill({ json: body })

  await page.route('**/api/history**', (route) => json(route, history))
  await page.route('**/api/conversations/**', (route) =>
    json(route, { conversation_id: 'chat-1', turns: [successResult] }),
  )
  await page.route('**/api/metrics/summary**', (route) => json(route, metricsSummary))
  await page.route('**/api/metrics/timeseries**', (route) => json(route, metricsTimeseries))
  await page.route('**/api/metrics/recent**', (route) => json(route, metricsRecent))
  await page.route('**/api/query/stream', (route) => {
    asked.push(route.request().postDataJSON())
    return route.fulfill({
      contentType: 'text/event-stream',
      body: answerStream({ ...result, query: asked.at(-1).query }),
    })
  })
  return asked
}

export async function ask(page, question) {
  const input = page.getByLabel('Ask a question about the financial data')
  await input.fill(question)
  await input.press('Enter')
}
