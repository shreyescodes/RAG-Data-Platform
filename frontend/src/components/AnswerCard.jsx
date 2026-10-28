import { Card } from './Card.jsx'
import { ActivityIcon } from './Icons.jsx'

export function AnswerCard({ answer, summary, insights, degraded }) {
  return (
    <Card icon={ActivityIcon} title="Answer">
      <p className="answer-text">{answer}</p>
      {degraded && (
        <p className="notice">The AI summary is unavailable; showing the raw results instead.</p>
      )}
      {summary && (
        <div className="summary-box">
          <p>{summary}</p>
        </div>
      )}
      {insights?.length > 0 && (
        <ul className="insights-list">
          {insights.map((insight) => (
            <li key={insight}>
              <span className="insight-bullet" aria-hidden="true">
                ✦
              </span>
              <span>{insight}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}
