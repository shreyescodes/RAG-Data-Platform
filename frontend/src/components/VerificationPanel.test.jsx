import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { successResult } from '../test/fixtures.js'
import { VerificationPanel } from './VerificationPanel.jsx'

const report = successResult.verification

describe('VerificationPanel', () => {
  it('renders nothing when verification was skipped', () => {
    const { container } = render(<VerificationPanel report={{ ...report, status: 'skipped' }} />)
    expect(container).toBeEmptyDOMElement()
    const { container: none } = render(<VerificationPanel report={null} />)
    expect(none).toBeEmptyDOMElement()
  })

  it('summarises flagged claims and lists every verdict with its reason', () => {
    render(<VerificationPanel report={report} />)

    expect(screen.getByRole('status')).toHaveTextContent(
      '1 of 3 claims not fully supported by the data',
    )
    const claims = screen.getAllByRole('listitem').filter((li) => li.classList.contains('claim'))
    expect(claims).toHaveLength(3)
    expect(within(claims[1]).getByText('Unsupported')).toBeInTheDocument()
    expect(within(claims[1]).getByText(/\$1M matches no value/)).toBeInTheDocument()
    expect(within(claims[1]).getByText(/data check \+ AI judge/)).toBeInTheDocument()
    expect(within(claims[2]).getByText('Not checkable')).toBeInTheDocument()
    // Flagged reports open the claim list.
    expect(screen.getByText('Claims (3)').closest('details')).toHaveAttribute('open')
  })

  it('links row evidence to the results table', () => {
    render(<VerificationPanel report={report} />)
    expect(screen.getByRole('link', { name: 'Row 1 · name: Apple Inc.' })).toHaveAttribute(
      'href',
      '#result-row-0',
    )
    expect(screen.getByText('min of value_usd = 27,543,790,976').tagName).toBe('SPAN')
  })

  it('reports clean answers and a degraded judge', () => {
    render(
      <VerificationPanel
        report={{
          ...report,
          status: 'verified',
          degraded: true,
          supported: 1,
          unsupported: 0,
          claims: report.claims.filter((c) => c.verdict !== 'unsupported'),
        }}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('1 of 1 checkable claims supported')
    expect(screen.getByText(/AI judge was unavailable/)).toBeInTheDocument()
    expect(screen.getByText('Claims (2)').closest('details')).not.toHaveAttribute('open')
  })
})
