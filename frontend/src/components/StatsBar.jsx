import { formatCell } from '../utils/format.js'

const ITEMS = [
  ['Companies', (s) => s.database?.companies],
  ['Statements', (s) => s.database?.financial_statements],
  ['Portfolio metrics', (s) => s.database?.performance_metrics],
  ['Price points', (s) => s.database?.market_data],
]

export function StatsBar({ stats }) {
  if (!stats) return null
  return (
    <div className="stats-container" aria-label="Dataset statistics">
      <dl className="stats-grid">
        {ITEMS.map(([label, pick]) => (
          <div className="stat-item" key={label}>
            <dt className="stat-label">{label}</dt>
            <dd className="stat-value">{formatCell(pick(stats) ?? 0)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
