import { niceTicks } from './chartSpec.js'

// Geometry of the bucketed time charts on the Observability page.
export const TIME_CHART = { width: 720, height: 200, top: 12, right: 12, bottom: 26, left: 56 }
const MAX_BAR = 24
const X_LABELS = 6

/** The API returns naive UTC timestamps. */
export function parseUtc(iso) {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
}

export function formatBucket(iso, bucketSeconds) {
  const date = parseUtc(iso)
  if (bucketSeconds >= 86_400) {
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }
  if (bucketSeconds >= 21_600) {
    return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric' })
  }
  return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

/** A column whose top corners are rounded (the data end) and base square. */
export function barPath(x, y, width, height, radius = 4) {
  if (height <= 0) return ''
  const r = Math.min(radius, width / 2, height)
  return [
    `M${x},${y + height}`,
    `V${y + r}`,
    `Q${x},${y} ${x + r},${y}`,
    `H${x + width - r}`,
    `Q${x + width},${y} ${x + width},${y + r}`,
    `V${y + height}`,
    'Z',
  ].join(' ')
}

/**
 * Lay out `points` (API buckets) for `series` ([{ key }]).
 * `stacked` sums the series per bucket (columns); otherwise each is its own line.
 */
export function layoutTimeChart(points, series, { stacked }) {
  const { width, height, top, right, bottom, left } = TIME_CHART
  const plotW = width - left - right
  const plotH = height - top - bottom
  const totals = points.map((p) =>
    stacked
      ? series.reduce((sum, s) => sum + (p[s.key] ?? 0), 0)
      : Math.max(0, ...series.map((s) => p[s.key] ?? 0)),
  )
  const ticks = niceTicks(0, Math.max(...totals, 0) || 1, 4)
  const yMax = ticks[ticks.length - 1]
  const band = plotW / Math.max(points.length, 1)
  const y = (v) => top + plotH - (v / yMax) * plotH
  const xCenter = (i) => left + band * (i + 0.5)
  const step = Math.max(1, Math.ceil(points.length / X_LABELS))
  const xLabels = points.map((_, i) => i).filter((i) => i % step === 0)
  return {
    plotW,
    plotH,
    band,
    barWidth: Math.min(MAX_BAR, Math.max(2, band * 0.6)),
    ticks,
    y,
    xCenter,
    baseline: top + plotH,
    xLabels,
  }
}

/**
 * Runs of consecutive [x, y] points for one series, broken where a bucket has
 * no value. A run of one point has no line to draw and needs a marker instead.
 */
export function lineSegments(points, key, layout) {
  const segments = []
  let current = []
  points.forEach((p, i) => {
    const v = p[key]
    if (v === null || v === undefined) {
      if (current.length) segments.push(current)
      current = []
      return
    }
    current.push([layout.xCenter(i), layout.y(v)])
  })
  if (current.length) segments.push(current)
  return segments
}

export function segmentPath(segment) {
  return segment.map(([x, y], i) => `${i ? 'L' : 'M'}${x},${y}`).join(' ')
}
