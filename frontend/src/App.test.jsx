import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'
import { EXAMPLE_QUERIES } from './constants.js'
import {
  failedResult,
  history,
  metricsRecent,
  metricsSummary,
  metricsTimeseries,
  stats,
  successResult,
} from './test/fixtures.js'
import { jsonResponse, mockFetch } from './test/mockFetch.js'

afterEach(() => {
  vi.unstubAllGlobals()
  window.location.hash = ''
})

function setup(queryHandler = successResult) {
  const fetch = mockFetch({
    'GET /api/stats': stats,
    'GET /api/history': history,
    'POST /api/query': queryHandler,
    'GET /api/metrics/summary': metricsSummary,
    'GET /api/metrics/timeseries': metricsTimeseries,
    'GET /api/metrics/recent': metricsRecent,
  })
  const user = userEvent.setup()
  render(<App />)
  return { fetch, user }
}

describe('App', () => {
  it('shows dataset stats, suggestions and history on load', async () => {
    setup()
    expect(await screen.findByText('9,512')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: EXAMPLE_QUERIES[0] })).toBeInTheDocument()
    expect(await screen.findByText('Fund positions by quarter')).toBeInTheDocument()
  })

  it('runs a query and renders the answer, SQL, trace and data', async () => {
    const { fetch, user } = setup()

    await user.type(screen.getByLabelText(/ask a question/i), 'Top Berkshire holdings by value{Enter}')

    expect(await screen.findByText('Apple Inc. is the largest holding.', { selector: '.answer-text' })).toBeInTheDocument()
    expect(screen.getByText(successResult.sql)).toBeInTheDocument()
    expect(screen.getByText('1.83 s')).toBeInTheDocument()
    expect(screen.getByText('65,950,296,923')).toBeInTheDocument()
    expect(screen.getByText('Data (2 rows)')).toBeInTheDocument()
    expect(screen.getByText('Reasoning steps (1)')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Fact check' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Sources' })).toBeInTheDocument()
    expect(screen.getByText('3 (1 from cache)')).toBeInTheDocument()
    expect(screen.getByText('openai/gpt-oss-120b (remote)')).toBeInTheDocument()
    expect(document.getElementById('result-row-0')).toHaveTextContent('Apple Inc.')

    const queryCall = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(queryCall[1].body)).toEqual({ query: 'Top Berkshire holdings by value' })
    // Stats and history refresh after the query settles.
    await waitFor(() =>
      expect(fetch.mock.calls.filter(([url]) => url.includes('/history'))).toHaveLength(2),
    )
  })

  it('runs a suggested query on click', async () => {
    const { fetch, user } = setup()
    await user.click(screen.getByRole('button', { name: EXAMPLE_QUERIES[1] }))
    await screen.findByText('Apple Inc. is the largest holding.', { selector: '.answer-text' })
    const queryCall = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(queryCall[1].body).query).toBe(EXAMPLE_QUERIES[1])
  })

  it('shows pipeline failures with the agent trace', async () => {
    const { user } = setup(failedResult)
    await user.type(screen.getByLabelText(/ask a question/i), 'Drop all tables{Enter}')

    expect(await screen.findByRole('alert')).toHaveTextContent(failedResult.error)
    expect(screen.getByText('failed')).toBeInTheDocument()
  })

  it('shows HTTP errors with the request ID', async () => {
    const { user } = setup(() =>
      jsonResponse({ detail: 'x' }, { status: 401, headers: { 'X-Request-ID': 'abc123' } }),
    )
    await user.type(screen.getByLabelText(/ask a question/i), 'Anything at all{Enter}')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/invalid API key/)
    expect(alert).toHaveTextContent('Request ID: abc123')
  })

  it('disables submit for too-short queries', async () => {
    const { user } = setup()
    const submit = screen.getByRole('button', { name: 'Run query' })
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/ask a question/i), 'ab')
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/ask a question/i), 'c')
    expect(submit).toBeEnabled()
  })

  it('renders live market data when present', async () => {
    const enriched = {
      ...successResult,
      enriched_data: {
        market_data: [{ ticker: 'AAPL', current_price: 251.3, currency: 'USD', market_cap: 3.8e12 }],
        sec_filings: [
          { ticker: 'AAPL', form: '10-K', filing_date: '2025-11-01', url: 'https://sec.test/10k' },
        ],
      },
    }
    const { user } = setup(enriched)
    await user.type(screen.getByLabelText(/ask a question/i), 'AAPL stock price{Enter}')

    expect(await screen.findByText('Live market data')).toBeInTheDocument()
    expect(screen.getByText('3.8T')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AAPL 10-K' })).toHaveAttribute('href', 'https://sec.test/10k')
  })

  it('switches to the observability dashboard and back', async () => {
    const { user } = setup()
    await user.click(screen.getByRole('link', { name: 'Observability' }))
    expect(await screen.findByLabelText('Key metrics')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Observability' })).toHaveAttribute('aria-current', 'page')
    expect(screen.queryByLabelText(/ask a question/i)).not.toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Query' }))
    expect(await screen.findByLabelText(/ask a question/i)).toBeInTheDocument()
  })
})
