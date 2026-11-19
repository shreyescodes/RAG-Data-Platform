const STEPS = [
  ['retrieval', 'Finding the right tables'],
  ['sql_generation', 'Writing the SQL'],
  ['sql_execution', 'Running the query'],
  ['enrichment', 'Checking live market data'],
  ['analysis', 'Writing the answer'],
  ['verification', 'Fact-checking the answer'],
]

const LABEL = { started: 'in progress', completed: 'done' }

/** Live progress of a question, from the stages the server reports. */
export function ProgressSteps({ stages }) {
  return (
    <ol className="progress" aria-label="Progress">
      {STEPS.map(([stage, label]) => {
        const status = stages[stage] ?? 'waiting'
        return (
          <li key={stage} className={`progress-step is-${status}`}>
            <span className="progress-mark" aria-hidden="true" />
            {label}
            <span className="visually-hidden"> ({LABEL[status] ?? 'waiting'})</span>
          </li>
        )
      })}
    </ol>
  )
}
