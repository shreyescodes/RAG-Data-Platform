import { describe, expect, it } from 'vitest'
import {
  barPath,
  formatBucket,
  layoutTimeChart,
  lineSegments,
  parseUtc,
  segmentPath,
} from './timeChart.js'

const points = [
  { start: '2026-11-05T09:00:00', a: 2, b: 1 },
  { start: '2026-11-05T10:00:00', a: null, b: 4 },
  { start: '2026-11-05T11:00:00', a: 3, b: 0 },
]
const series = [{ key: 'a' }, { key: 'b' }]

describe('timeChart', () => {
  it('parses naive timestamps as UTC', () => {
    expect(parseUtc('2026-11-05T09:00:00').toISOString()).toBe('2026-11-05T09:00:00.000Z')
    expect(parseUtc('2026-11-05T09:00:00+00:00').toISOString()).toBe('2026-11-05T09:00:00.000Z')
  })

  it('formats buckets by their size', () => {
    expect(formatBucket('2026-11-05T09:00:00', 86_400)).toMatch(/Nov \d/)
    expect(formatBucket('2026-11-05T09:30:00', 300)).toMatch(/^\d\d:\d\d$/)
  })

  it('scales stacked charts to the tallest stack and lines to the largest value', () => {
    expect(layoutTimeChart(points, series, { stacked: true }).ticks.at(-1)).toBeGreaterThanOrEqual(4)
    const stacked = layoutTimeChart(points, series, { stacked: true })
    const lines = layoutTimeChart(points, series, { stacked: false })
    expect(stacked.y(0)).toBe(stacked.baseline)
    expect(lines.ticks.at(-1)).toBeGreaterThanOrEqual(4)
    expect(stacked.barWidth).toBeLessThanOrEqual(24)
  })

  it('handles an all-zero window', () => {
    const layout = layoutTimeChart([{ start: 's', a: 0 }], [{ key: 'a' }], { stacked: true })
    expect(layout.ticks.at(-1)).toBeGreaterThan(0)
  })

  it('breaks lines where a bucket has no value', () => {
    const layout = layoutTimeChart(points, series, { stacked: false })
    const segments = lineSegments(points, 'a', layout)
    // [2, null, 3]: two isolated points, each drawn as a marker, not a line.
    expect(segments.map((s) => s.length)).toEqual([1, 1])
    expect(segmentPath([[0, 1], [2, 3]])).toBe('M0,1 L2,3')
  })

  it('rounds only the top of a column', () => {
    const d = barPath(0, 10, 20, 50)
    expect(d.startsWith('M0,60 V14')).toBe(true)
    expect(d).toContain('Q20,10 20,14')
    expect(barPath(0, 0, 10, 0)).toBe('')
  })
})
