import { formatDuration } from '../utils/format.js'
import { Card } from './Card.jsx'
import { TerminalIcon } from './Icons.jsx'

export function ExecutionDetails({ result }) {
  return (
    <Card icon={TerminalIcon} title="Execution">
      <dl className="meta-grid">
        <div className="meta-row">
          <dt className="meta-label">Execution time</dt>
          <dd className="meta-value">{formatDuration(result.execution_time_ms)}</dd>
        </div>
        <div className="meta-row">
          <dt className="meta-label">Rows returned</dt>
          <dd className="meta-value">{result.row_count}</dd>
        </div>
        <div className="meta-row">
          <dt className="meta-label">Tables</dt>
          <dd className="meta-value">{result.relevant_tables?.join(', ') || '—'}</dd>
        </div>
      </dl>
      {result.sql && (
        <>
          <div className="section-label">Generated SQL</div>
          <pre className="sql-block">
            <code>{result.sql}</code>
          </pre>
        </>
      )}
    </Card>
  )
}
