// Infers a chart for a query result, or null when a chart would not help.
//
//   date column + numeric column(s)          -> line (change over time)
//   date + 2-3 category values + one measure -> line, one series per category
//   text label column + numeric column       -> horizontal bar (magnitude)
//
// Series are capped at three: the categorical palette is validated for three
// slots on the dark surface, and more than that belongs in the table.

const DATE_RE = /^\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+)?(?:Z|[+-]\d\d:?\d\d)?$/
const MAX_SERIES = 3
const MAX_BARS = 25
const MIN_POINTS = 3
// Measures plotted together on one axis must share a scale (no dual axes).
const SAME_SCALE_RATIO = 3

const isIdColumn = (name) => name === 'id' || name.endsWith('_id')

function classify(rows, col) {
  let seen = 0
  let numbers = 0
  let dates = 0
  for (const row of rows) {
    const v = row[col]
    if (v === null || v === undefined) continue
    seen += 1
    if (typeof v === 'number' && Number.isFinite(v)) numbers += 1
    else if (typeof v === 'string' && DATE_RE.test(v)) dates += 1
  }
  if (seen === 0) return 'empty'
  if (numbers === seen) return 'number'
  if (dates === seen) return 'date'
  return 'text'
}

const ACRONYMS = new Set(['arr', 'mrr', 'cac', 'ltv', 'eps', 'ebitda', 'ma', 'pe', 'id'])

export function humanize(column) {
  const words = column
    .split('_')
    .filter(Boolean)
    .map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w))
    .join(' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

function maxAbs(rows, col) {
  return rows.reduce((m, r) => (typeof r[col] === 'number' ? Math.max(m, Math.abs(r[col])) : m), 0)
}

function lineSpec(rows, dateCol, measures, groupCol, measure) {
  const sorted = [...rows].sort((a, b) => Date.parse(a[dateCol]) - Date.parse(b[dateCol]))
  const point = (r, key) => ({ x: Date.parse(r[dateCol]), y: r[key], row: r })

  let series
  if (groupCol) {
    const groups = [...new Set(sorted.map((r) => r[groupCol]))]
    series = groups.map((g) => ({
      key: String(g),
      label: String(g),
      points: sorted.filter((r) => r[groupCol] === g && typeof r[measure] === 'number').map((r) => point(r, measure)),
    }))
  } else {
    const base = maxAbs(rows, measure) || 1
    const companions = measures.filter((m) => {
      const ratio = (maxAbs(rows, m) || 1) / base
      return m !== measure && ratio <= SAME_SCALE_RATIO && ratio >= 1 / SAME_SCALE_RATIO
    })
    series = [measure, ...companions].slice(0, MAX_SERIES).map((m) => ({
      key: m,
      label: humanize(m),
      points: sorted.filter((r) => typeof r[m] === 'number').map((r) => point(r, m)),
    }))
  }

  series = series.filter((s) => s.points.length >= MIN_POINTS)
  if (!series.length) return null
  return { type: 'line', x: dateCol, measure, measures, series, title: humanize(measure) }
}

function barSpec(rows, labelCol, measures, measure) {
  const labels = rows.map((r) => r[labelCol])
  if (new Set(labels).size !== labels.length) return null // not one bar per label
  const bars = rows
    .filter((r) => typeof r[measure] === 'number')
    .map((r) => ({ label: String(r[labelCol] ?? '—'), value: r[measure], row: r }))
  if (bars.length < 2) return null
  return { type: 'bar', label: labelCol, measure, measures, bars, title: humanize(measure) }
}

/**
 * @param {object[]} rows   query result rows
 * @param {string} [measure] numeric column to plot; defaults to a sensible pick
 */
export function inferChart(rows, measure) {
  if (!Array.isArray(rows) || rows.length < 2) return null
  const columns = Object.keys(rows[0])
  const kinds = Object.fromEntries(columns.map((c) => [c, classify(rows, c)]))
  const measures = columns.filter((c) => kinds[c] === 'number' && !isIdColumn(c))
  if (!measures.length) return null

  // A date shared by (almost) every row is context, not an x-axis.
  const dateCol = columns.find(
    (c) => kinds[c] === 'date' && new Set(rows.map((r) => r[c])).size >= MIN_POINTS,
  )
  const textCols = columns.filter((c) => kinds[c] === 'text')

  if (dateCol) {
    const chosen = measures.includes(measure) ? measure : measures[0]
    const groupCol = textCols.find((c) => {
      const distinct = new Set(rows.map((r) => r[c])).size
      return distinct >= 2 && distinct <= MAX_SERIES
    })
    const singleSeriesPerDate = new Set(rows.map((r) => r[dateCol])).size === rows.length
    if (singleSeriesPerDate) return lineSpec(rows, dateCol, measures, null, chosen)
    if (groupCol) return lineSpec(rows, dateCol, measures, groupCol, chosen)
    return null
  }

  if (textCols.length && rows.length <= MAX_BARS) {
    // Aggregates usually come last: `SELECT name, AVG(x) AS avg_x ...`.
    const chosen = measures.includes(measure) ? measure : measures[measures.length - 1]
    return barSpec(rows, textCols[0], measures, chosen)
  }
  return null
}

/** Round, human-friendly axis ticks covering [min, max]. */
export function niceTicks(min, max, count = 5) {
  if (min === max) {
    const pad = Math.abs(min) || 1
    return niceTicks(min - pad, max + pad, count)
  }
  const span = max - min
  const rawStep = span / Math.max(1, count - 1)
  const magnitude = 10 ** Math.floor(Math.log10(rawStep))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep)
  const start = Math.floor(min / step) * step
  const ticks = []
  for (let v = start; v <= max + step * 0.5; v += step) ticks.push(Number(v.toPrecision(12)))
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step)
  return ticks
}
