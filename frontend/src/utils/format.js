const integer = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })
const decimal = new Intl.NumberFormat('en-US', { maximumFractionDigits: 4 })

/** Render a result cell for display. Large numbers get separators. */
export function formatCell(value) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    return Number.isInteger(value) || Math.abs(value) >= 1000
      ? integer.format(value)
      : decimal.format(value)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function formatFixed(value, digits = 2) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function formatDuration(ms) {
  if (typeof ms !== 'number') return '—'
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)} s` : `${Math.round(ms)} ms`
}

export function formatCompact(value) {
  if (typeof value !== 'number') return '—'
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

export function formatRelativeTime(iso, now = Date.now()) {
  if (!iso) return ''
  // The API returns naive UTC timestamps.
  const then = Date.parse(/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`)
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

/** A score with fixed decimals, or a dash when absent. */
export function formatScore(value, digits = 2) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

/** A 0-1 fraction as a whole percentage, or a dash when absent. */
export function formatPercent(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '—'
}

/** US dollars, with enough precision for fractions of a cent. */
export function formatUsd(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (value === 0) return '$0'
  // Per-request LLM costs are fractions of a cent: keep two significant figures.
  if (Math.abs(value) < 1) return `$${value.toPrecision(2)}`
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

/** A 0-1 rate as a percentage with one decimal. */
export function formatRate(value) {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'
}
