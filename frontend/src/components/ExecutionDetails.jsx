import { formatCompact, formatDuration, formatUsd } from '../utils/format.js'
import { Card } from './Card.jsx'
import { TerminalIcon } from './Icons.jsx'

function Row({ label, children }) {
  return (
    <div className="meta-row">
      <dt className="meta-label">{label}</dt>
      <dd className="meta-value">{children}</dd>
    </div>
  )
}

export function ExecutionDetails({ result }) {
  const usage = result.usage
  return (
    <Card icon={TerminalIcon} title="Execution">
      <dl className="meta-grid">
        <Row label="Execution time">{formatDuration(result.execution_time_ms)}</Row>
        <Row label="Rows returned">{result.row_count}</Row>
        <Row label="Tables">{result.relevant_tables?.join(', ') || '—'}</Row>
        {usage && (
          <>
            <Row label="LLM">
              {usage.model} ({usage.llm_endpoint})
            </Row>
            <Row label="Tokens">
              {formatCompact(usage.prompt_tokens + usage.completion_tokens)} ·{' '}
              {formatUsd(usage.cost_usd)}
            </Row>
            <Row label="LLM calls">
              {usage.llm_calls}
              {usage.cache_hits > 0 && ` (${usage.cache_hits} from cache)`}
            </Row>
          </>
        )}
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
