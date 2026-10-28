import { formatCompact, formatFixed } from '../utils/format.js'
import { Card } from './Card.jsx'
import { TrendIcon } from './Icons.jsx'

export function EnrichmentPanel({ data }) {
  const quotes = data?.market_data ?? []
  const filings = data?.sec_filings ?? []
  if (!quotes.length && !filings.length) return null

  return (
    <Card icon={TrendIcon} title="Live market data">
      {quotes.length > 0 && (
        <div className="quote-grid">
          {quotes.map((q) => (
            <div key={q.ticker} className="quote">
              <div className="quote-ticker">{q.ticker}</div>
              <div className="quote-price">
                {formatFixed(q.current_price)} <span className="quote-currency">{q.currency}</span>
              </div>
              <dl className="quote-meta">
                <div>
                  <dt>Mkt cap</dt>
                  <dd>{formatCompact(q.market_cap)}</dd>
                </div>
                <div>
                  <dt>P/E</dt>
                  <dd>{formatFixed(q.pe_ratio)}</dd>
                </div>
                <div>
                  <dt>52w range</dt>
                  <dd>
                    {formatFixed(q.fifty_two_week_low)} – {formatFixed(q.fifty_two_week_high)}
                  </dd>
                </div>
              </dl>
            </div>
          ))}
        </div>
      )}
      {filings.length > 0 && (
        <>
          <div className="section-label">Recent SEC filings</div>
          <ul className="filing-list">
            {filings.map((f) => (
              <li key={f.url}>
                <a href={f.url} target="_blank" rel="noopener noreferrer">
                  {f.ticker} {f.form}
                </a>
                <span className="filing-date">filed {f.filing_date}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}
