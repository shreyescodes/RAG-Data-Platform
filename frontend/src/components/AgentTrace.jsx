import { Card } from './Card.jsx'
import { DatabaseIcon } from './Icons.jsx'

const STAGES = ['retrieval', 'enrichment', 'analysis']

function formatDetail(detail) {
  if (detail === null || detail === undefined) return ''
  return typeof detail === 'string' ? detail : JSON.stringify(detail)
}

export function AgentTrace({ flow = {}, trace = [] }) {
  return (
    <Card icon={DatabaseIcon} title="Agent trace">
      <ol className="agent-flow">
        {STAGES.map((stage) => {
          const status = flow[stage] ?? 'skipped'
          return (
            <li key={stage} className={`agent-step ${status}`}>
              <span className="agent-name">{stage}</span>
              <span className="agent-status">{status}</span>
            </li>
          )
        })}
      </ol>
      {trace.length > 0 && (
        <details className="trace-details">
          <summary>Reasoning steps ({trace.length})</summary>
          <ol className="trace-steps">
            {trace.map((step, idx) => (
              <li key={`${step.timestamp}-${idx}`}>
                <span className="trace-step-name">
                  {step.agent}.{step.step}
                </span>
                {step.detail !== null && step.detail !== undefined && (
                  <code className="trace-step-detail">{formatDetail(step.detail)}</code>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
    </Card>
  )
}
