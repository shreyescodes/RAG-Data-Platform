import { useState } from 'react'
import './App.css'

function App() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [stats, setStats] = useState(null)

  const API_URL = 'http://localhost:8000/api'

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!query.trim()) return

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await fetch(`${API_URL}/query`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || 'Query failed')
      }

      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const loadStats = async () => {
    try {
      const response = await fetch(`${API_URL}/stats`)
      const data = await response.json()
      setStats(data)
    } catch (err) {
      console.error('Failed to load stats:', err)
    }
  }

  useState(() => {
    loadStats()
  }, [])

  const exampleQueries = [
    "What are the total liabilities in Company X?",
    "What's the YoY revenue growth in 2024?",
    "Show me all portfolio companies with ARR over 1M",
    "What is the average churn rate across all companies?",
    "List companies in the technology sector"
  ]

  return (
    <div className="app">
      <header className="header">
        <h1>RAG Financial Platform</h1>
        <p>Ask questions about financial data using natural language</p>
      </header>

      <main className="main">
        <div className="query-section">
          <form onSubmit={handleSubmit}>
            <div className="input-group">
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Ask a question about financial data..."
                rows={3}
                disabled={loading}
              />
              <button type="submit" disabled={loading || !query.trim()}>
                {loading ? 'Processing...' : 'Ask Question'}
              </button>
            </div>
          </form>

          <div className="examples">
            <p>Example queries:</p>
            <div className="example-buttons">
              {exampleQueries.map((example, idx) => (
                <button
                  key={idx}
                  className="example-btn"
                  onClick={() => setQuery(example)}
                  disabled={loading}
                >
                  {example}
                </button>
              ))}
            </div>
          </div>
        </div>

        {error && (
          <div className="error">
            <h3>Error</h3>
            <p>{error}</p>
          </div>
        )}

        {result && (
          <div className="result">
            {result.success ? (
              <>
                <div className="answer-card">
                  <h2>Answer</h2>
                  <p className="answer-text">{result.answer}</p>

                  {result.summary && (
                    <div className="summary">
                      <h3>Summary</h3>
                      <p>{result.summary}</p>
                    </div>
                  )}

                  {result.insights && result.insights.length > 0 && (
                    <div className="insights">
                      <h3>Key Insights</h3>
                      <ul>
                        {result.insights.map((insight, idx) => (
                          <li key={idx}>{insight}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <div className="details">
                  <div className="detail-card">
                    <h3>Generated SQL</h3>
                    <pre className="sql-code">{result.sql}</pre>
                  </div>

                  <div className="detail-card">
                    <h3>Query Metadata</h3>
                    <div className="metadata">
                      <div className="meta-item">
                        <span className="meta-label">Rows Returned:</span>
                        <span className="meta-value">{result.row_count}</span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">Execution Time:</span>
                        <span className="meta-value">{result.execution_time_ms.toFixed(2)} ms</span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">Tables Used:</span>
                        <span className="meta-value">{result.relevant_tables.join(', ')}</span>
                      </div>
                    </div>
                  </div>

                  {result.data && result.data.length > 0 && (
                    <div className="detail-card">
                      <h3>Data Preview (first 10 rows)</h3>
                      <div className="table-wrapper">
                        <table>
                          <thead>
                            <tr>
                              {Object.keys(result.data[0]).map((key) => (
                                <th key={key}>{key}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {result.data.slice(0, 10).map((row, idx) => (
                              <tr key={idx}>
                                {Object.values(row).map((value, vIdx) => (
                                  <td key={vIdx}>
                                    {value !== null ? String(value) : 'null'}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  <div className="detail-card">
                    <h3>Agent Flow</h3>
                    <div className="agent-flow">
                      {Object.entries(result.agent_flow).map(([agent, status]) => (
                        <div key={agent} className={`agent-step ${status}`}>
                          <span className="agent-name">{agent}</span>
                          <span className="agent-status">{status}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="error">
                <h3>Query Failed</h3>
                <p>{result.error}</p>
              </div>
            )}
          </div>
        )}

        {stats && (
          <div className="stats">
            <h3>Platform Statistics</h3>
            <div className="stats-grid">
              <div className="stat-card">
                <span className="stat-value">{stats.database.companies}</span>
                <span className="stat-label">Companies</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{stats.database.financial_statements}</span>
                <span className="stat-label">Financial Statements</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{stats.database.performance_metrics}</span>
                <span className="stat-label">Performance Metrics</span>
              </div>
              <div className="stat-card">
                <span className="stat-value">{stats.database.market_data}</span>
                <span className="stat-label">Market Data Points</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
