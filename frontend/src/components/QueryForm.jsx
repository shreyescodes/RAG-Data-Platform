import { SearchIcon, SendIcon } from './Icons.jsx'

const MAX_LENGTH = 1000

export function QueryForm({ value, onChange, onSubmit, onCancel, loading }) {
  const canSubmit = !loading && value.trim().length >= 3

  const handleSubmit = (event) => {
    event.preventDefault()
    if (canSubmit) onSubmit(value.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="query-form">
      <div className="input-wrapper">
        <span className="search-icon">
          <SearchIcon />
        </span>
        <label htmlFor="query-input" className="visually-hidden">
          Ask a question about the financial data
        </label>
        <textarea
          id="query-input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Ask about revenue, ARR, churn, stock prices…"
          rows={1}
          maxLength={MAX_LENGTH}
          disabled={loading}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) handleSubmit(e)
          }}
        />
        {loading ? (
          <button type="button" className="submit-btn submit-btn--cancel" onClick={onCancel}>
            <span className="spinner" aria-hidden="true" />
            <span className="visually-hidden">Cancel query</span>
          </button>
        ) : (
          <button type="submit" className="submit-btn" disabled={!canSubmit} title="Run query (Enter)">
            <SendIcon />
            <span className="visually-hidden">Run query</span>
          </button>
        )}
      </div>
    </form>
  )
}
