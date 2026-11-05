import { MAX_TABLE_ROWS } from '../constants.js'
import { Card } from './Card.jsx'
import { ShieldIcon } from './Icons.jsx'

const VERDICT_LABEL = {
  supported: 'Supported',
  partially_supported: 'Partially supported',
  unsupported: 'Unsupported',
  unverifiable: 'Not checkable',
}

const METHOD_LABEL = {
  deterministic: 'checked against the data',
  hybrid: 'data check + AI judge',
  llm: 'AI judge',
}

function headline(report) {
  const flagged = report.unsupported + report.partially_supported
  const checked = report.claims.length - report.unverifiable
  if (flagged) {
    return `${flagged} of ${report.claims.length} claims not fully supported by the data`
  }
  return `${report.supported} of ${checked} checkable claims supported by the data`
}

function EvidenceLink({ evidence }) {
  if (evidence.kind === 'row' && evidence.row_index < MAX_TABLE_ROWS) {
    return <a href={`#result-row-${evidence.row_index}`}>{evidence.label}</a>
  }
  return <span>{evidence.label}</span>
}

function ClaimItem({ claim }) {
  return (
    <li className={`claim claim--${claim.verdict}`}>
      <div className="claim-head">
        <span className={`verdict-chip verdict-${claim.verdict}`}>{VERDICT_LABEL[claim.verdict]}</span>
        <span className="claim-text">{claim.text}</span>
      </div>
      <div className="claim-meta">
        {claim.reason}
        {claim.verdict !== 'unverifiable' && ` · ${METHOD_LABEL[claim.method] ?? claim.method}`}
      </div>
      {claim.evidence?.length > 0 && (
        <ul className="claim-evidence" aria-label="Evidence">
          {claim.evidence.map((e) => (
            <li key={e.id}>
              <EvidenceLink evidence={e} />
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

export function VerificationPanel({ report }) {
  if (!report || report.status === 'skipped' || !report.claims?.length) return null
  const flagged = report.status === 'flagged'

  return (
    <Card icon={ShieldIcon} title="Fact check">
      <p className={`verification-headline ${flagged ? 'is-flagged' : 'is-verified'}`} role="status">
        {headline(report)}
      </p>
      {report.degraded && (
        <p className="notice">The AI judge was unavailable; only the data checks ran.</p>
      )}
      <details className="claims-details" open={flagged}>
        <summary>Claims ({report.claims.length})</summary>
        <ol className="claim-list">
          {report.claims.map((claim) => (
            <ClaimItem key={claim.id} claim={claim} />
          ))}
        </ol>
      </details>
    </Card>
  )
}
