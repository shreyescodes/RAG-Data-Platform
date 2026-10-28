import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'
import { EXAMPLE_QUERIES } from './constants.js'
import { failedResult, history, stats, successResult } from './test/fixtures.js'
import { jsonResponse, mockFetch } from './test/mockFetch.js'

afterEach(() => vi.unstubAllGlobals())

function setup(queryHandler = successResult) {
  const fetch = mockFetch({
    'GET /api/stats': stats,
    'GET /api/history': history,
    'POST /api/query': queryHandler,
  })
  const user = userEvent.setup()
  render(<App />)
  return { fetch, user }
}

describe('App', () => {
  it('shows dataset stats, suggestions and history on load', async () => {
    setup()
    expect(await screen.findByText('5,398')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: EXAMPLE_QUERIES[0] })).toBeInTheDocument()
    expect(await screen.findByText('Average churn by stage')).toBeInTheDocument()
  })

  it('runs a query and renders the answer, SQL, trace and data', async () => {
    const { fetch, user } = setup()

    await user.type(screen.getByLabelText(/ask a question/i), 'Top companies by ARR{Enter}')

    expect(await screen.findByText('Atlas Analytics has the highest ARR.')).toBeInTheDocument()
    expect(screen.getByText(successResult.sql)).toBeInTheDocument()
    expect(screen.getByText('1.83 s')).toBeInTheDocument()
    expect(screen.getByText('12,000,000')).toBeInTheDocument()
    expect(screen.getByText('Data (2 rows)')).toBeInTheDocument()
    expect(screen.getByText('Reasoning steps (1)')).toBeInTheDocument()

    const queryCall = fetch.mock.calls.find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(queryCall[1].body)).toEqual({ query: 'Top companies by ARR' })
    // Stats and history refresh after the query settles.
    await waitFor(() =>
      expect(fetch.mock.calls.filter(([url]) => url.includes('/history'))).toHaveLength(2),
    )
  })

  it('runs a suggested query on click', async () => {
    const { fetch, user } = setup()
    await user.click(screen.getByRole('button', { name: EXAMPLE_QUERIES[1] }))
    await screen.findByText('Atlas Analytics has the highest ARR.')
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
})
