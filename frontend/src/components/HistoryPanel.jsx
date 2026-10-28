import { formatRelativeTime } from '../utils/format.js'
import { Card } from './Card.jsx'
import { ClockIcon } from './Icons.jsx'

export function HistoryPanel({ items, onSelect, disabled }) {
  if (!items?.length) return null
  return (
    <Card icon={ClockIcon} title="Recent queries">
      <ul className="history-list">
        {items.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              className="history-item"
              onClick={() => onSelect(item.query)}
              disabled={disabled}
              title={item.success ? 'Run again' : (item.error ?? 'Failed')}
            >
              <span
                className={`status-dot ${item.success ? 'ok' : 'fail'}`}
                aria-label={item.success ? 'succeeded' : 'failed'}
              />
              <span className="history-query">{item.query}</span>
              <span className="history-time">{formatRelativeTime(item.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
