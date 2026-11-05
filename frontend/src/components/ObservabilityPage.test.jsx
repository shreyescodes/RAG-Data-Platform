import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { metricsRecent, metricsSummary, metricsTimeseries } from '../test/fixtures.js'
import { jsonResponse, mockFetch } from '../test/mockFetch.js'
import { ObservabilityPage } from './ObservabilityPage.jsx'

afterEach(() => vi.unstubAllGlobals())

function setup(overrides = {}) {
  const fetch = mockFetch({
    'GET /api/metrics/summary': metricsSummary,
    'GET /api/metrics/timeseries': metricsTimeseries,
    'GET /api/metrics/recent': metricsRecent,
    ...overrides,
  })
  const user = userEvent.setup()
  render(<ObservabilityPage />)
  return { fetch, user }
}

describe('ObservabilityPage', () => {
  it('shows headline metrics as stat tiles', async () => {
    setup()
    const kpis = await screen.findByLabelText('Key metrics')
    expect(within(kpis).getByText('42')).toBeInTheDocument()
    expect(within(kpis).getByText('7.1%')).toBeInTheDocument()
    expect(within(kpis).getByText('1.83 s')).toBeInTheDocument()
    expect(within(kpis).getByText('4.20 s')).toBeInTheDocument()
    expect(within(kpis).getByText('$0.018')).toBeInTheDocument()
    expect(within(kpis).getByText('10.0%')).toBeInTheDocument()
    expect(within(kpis).getByText('4 of 30')).toBeInTheDocument()
  })

  it('renders charts, model usage, failures and recent requests', async () => {
    setup()
    expect(await screen.findByRole('img', { name: /^Requests\./ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Latency\./ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Tokens\./ })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /^Estimated cost\./ })).toBeInTheDocument()

    expect(screen.getAllByText('openai/gpt-oss-120b').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Drop all tables').length).toBe(2) // failing + recent
    expect(screen.getByText('Compare every company')).toBeInTheDocument()
    expect(screen.getByText('SQL generation')).toBeInTheDocument()
    expect(screen.getByText('flagged')).toBeInTheDocument()
    expect(screen.getByText('cache ×1')).toBeInTheDocument()
    expect(screen.getByText('local')).toBeInTheDocument()
  })

  it('refetches everything when the window changes', async () => {
    const { fetch, user } = setup()
    await screen.findByLabelText('Key metrics')
    await user.click(screen.getByRole('button', { name: '7 days' }))
    await waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => url.includes('summary?window=7d'))).toBe(true),
    )
    expect(fetch.mock.calls.some(([url]) => url.includes('timeseries?window=7d'))).toBe(true)
    expect(screen.getByRole('button', { name: '7 days' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('reads chart values from the keyboard and offers a table view', async () => {
    const { user } = setup()
    const chart = await screen.findByRole('img', { name: /^Requests\./ })

    fireEvent.keyDown(chart, { key: 'End' })
    const tooltip = screen.getByRole('status')
    expect(tooltip).toHaveTextContent('Succeeded8')
    expect(tooltip).toHaveTextContent('Failed0')
    fireEvent.keyDown(chart, { key: 'ArrowLeft' })
    expect(screen.getByRole('status')).toHaveTextContent('Succeeded0')
    fireEvent.keyDown(chart, { key: 'Escape' })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    const card = chart.closest('section')
    await user.click(within(card).getByRole('button', { name: 'Table' }))
    const table = within(card).getByRole('table')
    expect(within(table).getAllByRole('row')).toHaveLength(4)
    expect(within(table).getByText('8')).toBeInTheDocument()
  })

  it('shows lines with gaps and a crosshair on hover', async () => {
    setup()
    const chart = await screen.findByRole('img', { name: /^Latency\./ })
    // [1500, null, 1700]: each series is two isolated points, drawn as markers.
    expect(chart.querySelectorAll('.chart-line').length).toBe(0)
    expect(chart.querySelectorAll('.chart-dot').length).toBe(4)
    fireEvent.keyDown(chart, { key: 'Home' })
    expect(chart.querySelector('.chart-crosshair')).not.toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('p953.90 s')
  })

  it('reports an empty window', async () => {
    setup({
      'GET /api/metrics/timeseries': { ...metricsTimeseries, points: [metricsTimeseries.points[1]] },
    })
    expect(await screen.findAllByText('No data in this window.')).toHaveLength(4)
  })

  it('draws a zero-cost window instead of calling it empty', async () => {
    setup({
      'GET /api/metrics/timeseries': {
        ...metricsTimeseries,
        points: metricsTimeseries.points.map((p) => ({ ...p, cost_usd: 0 })),
      },
    })
    expect(await screen.findByRole('img', { name: /^Estimated cost./ })).toBeInTheDocument()
  })

  it('shows API errors', async () => {
    setup({ 'GET /api/metrics/summary': () => jsonResponse({ detail: 'nope' }, { status: 500 }) })
    expect(await screen.findByRole('alert')).toHaveTextContent('nope')
  })
})
