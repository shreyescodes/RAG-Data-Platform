import { formatPercent, formatScore } from '../utils/format.js'
import { Card } from './Card.jsx'
import { BookIcon } from './Icons.jsx'

const VIA_LABEL = {
  retrieved: 'retrieved',
  foreign_key: 'join',
  sql_only: 'not retrieved',
}

const DERIVATION_LABEL = {
  column: '',
  aggregate: 'aggregate of',
  expression: 'computed from',
  literal: 'constant',
  unknown: 'unknown origin',
}

function RowIdentity({ citations }) {
  const keys = citations.key_columns ?? []
  if (!keys.length) return null
  const list = keys.join(', ')
  return (
    <p className="citation-note">
      {citations.aggregated
        ? `Each row is a group, keyed by ${list}.`
        : `Each row is identified by ${list}.`}
    </p>
  )
}

export function CitationsPanel({ citations }) {
  if (!citations) return null
  const tables = citations.tables ?? []
  const outputs = citations.output_columns ?? []
  const live = citations.live_sources ?? []

  return (
    <Card icon={BookIcon} title="Sources">
      <dl className="citation-summary">
        {citations.retrieval_mode && (
          <div>
            <dt>Retrieval</dt>
            <dd>{citations.retrieval_mode}</dd>
          </div>
        )}
        {citations.retrieval_confidence != null && (
          <div>
            <dt>Schema match</dt>
            <dd>{formatPercent(citations.retrieval_confidence)}</dd>
          </div>
        )}
        {citations.generation_confidence != null && (
          <div>
            <dt>SQL confidence</dt>
            <dd>{formatPercent(citations.generation_confidence)}</dd>
          </div>
        )}
        <div>
          <dt>Rows</dt>
          <dd>{citations.row_count}</dd>
        </div>
      </dl>

      {tables.length > 0 && (
        <div className="table-scroll">
          <table className="citation-table">
            <caption className="section-label">Tables shown to the SQL generator</caption>
            <thead>
              <tr>
                <th scope="col">Table</th>
                <th scope="col">How</th>
                <th scope="col" className="num" title="Cross-encoder relevance">
                  Rerank
                </th>
                <th scope="col" className="num" title="Cosine similarity">
                  Dense
                </th>
                <th scope="col" className="num" title="BM25 keyword score">
                  BM25
                </th>
                <th scope="col" className="num" title="Reciprocal rank fusion, 0-1">
                  Fused
                </th>
                <th scope="col">In SQL</th>
              </tr>
            </thead>
            <tbody>
              {tables.map((t) => (
                <tr key={t.table}>
                  <th scope="row">
                    <code>{t.table}</code>
                    {t.matched_columns?.length > 0 && (
                      <span className="citation-columns">{t.matched_columns.join(', ')}</span>
                    )}
                  </th>
                  <td>
                    <span className={`via-badge via-${t.via}`}>{VIA_LABEL[t.via] ?? t.via}</span>
                  </td>
                  <td className="num">{formatPercent(t.rerank_score)}</td>
                  <td className="num">{formatScore(t.dense_score)}</td>
                  <td className="num">{formatScore(t.sparse_score, 1)}</td>
                  <td className="num">{formatScore(t.fused_score)}</td>
                  <td>{t.used_in_sql ? 'yes' : 'no'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {outputs.length > 0 && (
        <>
          <div className="section-label">Result columns</div>
          <ul className="lineage-list">
            {outputs.map((o) => (
              <li key={o.output_column}>
                <code>{o.output_column}</code>
                <span className="lineage-arrow" aria-hidden="true">
                  ←
                </span>
                <span className="lineage-source">
                  {DERIVATION_LABEL[o.derivation] && (
                    <span className="lineage-kind">{DERIVATION_LABEL[o.derivation]} </span>
                  )}
                  {o.sources.length ? o.sources.join(', ') : ''}
                </span>
              </li>
            ))}
          </ul>
          <RowIdentity citations={citations} />
        </>
      )}

      {live.length > 0 && (
        <>
          <div className="section-label">Live sources</div>
          <ul className="filing-list">
            {live.map((s) => (
              <li key={`${s.kind}-${s.label}`}>
                {s.url ? (
                  <a href={s.url} target="_blank" rel="noopener noreferrer">
                    {s.label}
                  </a>
                ) : (
                  s.label
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}
