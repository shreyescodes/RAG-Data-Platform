import { describe, expect, it } from 'vitest'
import { humanize, inferChart, niceTicks } from './chartSpec.js'

const prices = [
  { date: '2026-10-03', close_price: 180.2, ma_50: 175.1, volume: 2.1e8 },
  { date: '2026-10-01', close_price: 178.0, ma_50: 174.6, volume: 1.9e8 },
  { date: '2026-10-02', close_price: 181.4, ma_50: 174.9, volume: 2.4e8 },
]

describe('inferChart', () => {
  it('draws a time series, sorted, with same-scale measures together', () => {
    const spec = inferChart(prices)
    expect(spec.type).toBe('line')
    expect(spec.series.map((s) => s.key)).toEqual(['close_price', 'ma_50'])
    // volume is ~1e6x larger, so it is never put on the same axis
    expect(spec.measures).toContain('volume')
    expect(spec.series[0].points.map((p) => p.y)).toEqual([178.0, 181.4, 180.2])
  })

  it('switches measure on request', () => {
    const spec = inferChart(prices, 'volume')
    expect(spec.series.map((s) => s.key)).toEqual(['volume'])
  })

  it('splits long-format data into one series per category', () => {
    const rows = ['AAPL', 'MSFT'].flatMap((ticker) =>
      ['2026-10-01', '2026-10-02', '2026-10-03'].map((date, i) => ({ ticker, date, close: 100 + i })),
    )
    const spec = inferChart(rows)
    expect(spec.type).toBe('line')
    expect(spec.series.map((s) => s.label)).toEqual(['AAPL', 'MSFT'])
  })

  it('draws bars for labelled magnitudes, defaulting to the last measure', () => {
    const rows = [
      { name: 'Atlas', company_id: 1, customers: 10, latest_arr: 12e6 },
      { name: 'Beacon', company_id: 2, customers: 20, latest_arr: 9e6 },
    ]
    const spec = inferChart(rows)
    expect(spec.type).toBe('bar')
    expect(spec.measure).toBe('latest_arr')
    expect(spec.measures).toEqual(['customers', 'latest_arr']) // ids are not measures
    expect(spec.bars.map((b) => b.label)).toEqual(['Atlas', 'Beacon'])
  })

  it('uses bars when every row shares the same date', () => {
    const rows = ['Apple', 'Microsoft', 'Alphabet'].map((name, i) => ({
      name,
      statement_date: '2026-06-30',
      revenue: 100 + i,
      net_income: 30 + i,
    }))
    const spec = inferChart(rows)
    expect(spec.type).toBe('bar')
    expect(spec.measure).toBe('net_income')
    expect(spec.bars.map((b) => b.label)).toEqual(['Apple', 'Microsoft', 'Alphabet'])
  })

  it.each([
    ['a single row', [{ name: 'a', v: 1 }]],
    ['no numeric column', [{ a: 'x' }, { a: 'y' }]],
    ['duplicate labels', [{ n: 'a', v: 1 }, { n: 'a', v: 2 }]],
    ['too few points', [{ d: '2026-01-01', v: 1 }, { d: '2026-01-02', v: 2 }]],
    ['too many bars', Array.from({ length: 30 }, (_, i) => ({ n: `c${i}`, v: i }))],
  ])('returns null for %s', (_, rows) => {
    expect(inferChart(rows)).toBeNull()
  })
})

describe('niceTicks', () => {
  it('produces round steps covering the range', () => {
    expect(niceTicks(0, 97)).toEqual([0, 25, 50, 75, 100])
    expect(niceTicks(172.3, 183.9)).toEqual([170, 175, 180, 185])
  })

  it('handles a flat range', () => {
    const ticks = niceTicks(5, 5)
    expect(ticks[0]).toBeLessThan(5)
    expect(ticks[ticks.length - 1]).toBeGreaterThan(5)
  })
})

describe('humanize', () => {
  it('turns column names into labels', () => {
    expect(humanize('latest_arr')).toBe('Latest ARR')
    expect(humanize('ma_50')).toBe('MA 50')
    expect(humanize('close_price')).toBe('Close price')
  })
})
