import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { successResult } from '../test/fixtures.js'
import { formatPercent, formatScore } from '../utils/format.js'
import { CitationsPanel } from './CitationsPanel.jsx'

describe('CitationsPanel', () => {
  it('renders nothing without citations', () => {
    const { container } = render(<CitationsPanel citations={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows every retrieval score per table and how it was selected', () => {
    render(<CitationsPanel citations={successResult.citations} />)

    const table = screen.getByRole('table', { name: /tables shown to the sql generator/i })
    const [, metrics, companies] = within(table).getAllByRole('row')
    expect(within(metrics).getByText('performance_metrics')).toBeInTheDocument()
    expect(within(metrics).getByText('retrieved')).toBeInTheDocument()
    expect(within(metrics).getByText('91%')).toBeInTheDocument()
    expect(within(metrics).getByText('0.62')).toBeInTheDocument()
    expect(within(metrics).getByText('7.4')).toBeInTheDocument()
    expect(within(metrics).getByText('arr, mrr')).toBeInTheDocument()
    expect(within(companies).getByText('join')).toBeInTheDocument()
    expect(within(companies).getByText('no')).toBeInTheDocument()

    expect(screen.getByText('hybrid+rerank')).toBeInTheDocument()
    expect(screen.getByText('80%')).toBeInTheDocument()
  })

  it('shows column lineage and row identity', () => {
    render(<CitationsPanel citations={successResult.citations} />)
    expect(screen.getByText('performance_metrics.arr')).toBeInTheDocument()
    expect(screen.getByText('Each row is identified by name.')).toBeInTheDocument()
  })

  it('describes aggregated rows and links live sources', () => {
    render(
      <CitationsPanel
        citations={{
          ...successResult.citations,
          aggregated: true,
          key_columns: ['investment_stage'],
          output_columns: [
            { output_column: 'avg', sources: ['performance_metrics.churn_rate'], derivation: 'aggregate' },
          ],
          live_sources: [
            { kind: 'market_data', ticker: 'AAPL', label: 'AAPL quote (Yahoo Finance)', url: 'https://y.test' },
            { kind: 'sec_filing', ticker: 'AAPL', label: 'AAPL 10-K (2026-01-01)', url: null },
          ],
        }}
      />,
    )
    expect(screen.getByText('Each row is a group, keyed by investment_stage.')).toBeInTheDocument()
    expect(screen.getByText(/aggregate of/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AAPL quote (Yahoo Finance)' })).toHaveAttribute(
      'href',
      'https://y.test',
    )
    expect(screen.getByText('AAPL 10-K (2026-01-01)')).toBeInTheDocument()
  })

  it('formats missing scores as dashes', () => {
    expect(formatScore(null)).toBe('—')
    expect(formatPercent(undefined)).toBe('—')
    expect(formatPercent(0.456)).toBe('46%')
  })
})
