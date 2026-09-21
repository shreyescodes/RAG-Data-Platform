import { useState, useEffect } from 'react'
import './App.css'

// Simple SVG Icons to replace external dependencies
const Icons = {
  Search: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"></circle>
      <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
    </svg>
  ),
  Send: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13"></line>
      <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
    </svg>
  ),
  Activity: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
    </svg>
  ),
  Database: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3"></ellipse>
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"></path>
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"></path>
    </svg>
  ),
  Terminal: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="4 17 10 11 4 5"></polyline>
      <line x1="12" y1="19" x2="20" y2="19"></line>
    </svg>
  ),
  Alert: () => (
    <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"></circle>
      <line x1="12" y1="8" x2="12" y2="12"></line>
      <line x1="12" y1="16" x2="12.01" y2="16"></line>
    </svg>
  )
}

function App() {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [stats, setStats] = useState(null)

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

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

  useEffect(() => {
    loadStats()
  }, [])

  const exampleQueries = [
    "What are the total liabilities in Company X?",
    "What's the YoY revenue growth in 2024?",
    "Show me all portfolio companies with ARR over 1M",
    "What is the average churn rate across all companies?"
  ]

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <h1>RAG Financial Terminal</h1>
        </div>
      </header>

      <main className="main">
        
        {!result && (
          <div className="hero">
            <h2>Query Intelligence</h2>
            <p>Access structured financial data using natural language</p>
          </div>
        )}

        <div className="query-section">
          <form onSubmit={handleSubmit}>
            <div className="input-wrapper">
              <div className="search-icon">
                <Icons.Search />
              </div>
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Enter a financial query..."
                rows={1}
                disabled={loading}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit(e);
                  }
                }}
              />
              <button 
                type="submit" 
                className="submit-btn"
                disabled={loading || !query.trim()}
                title="Send Query (Enter)"
              >
                <Icons.Send />
              </button>
            </div>
          </form>

          {!result && (
            <div className="examples">
              <div className="examples-label">Suggested Queries</div>
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
          )}
        </div>

        {error && (
          <div className="error-message">
            <Icons.Alert />
            <div>
              <strong>Error Processing Query</strong>
              <div style={{fontSize: '0.875rem', marginTop: '0.25rem', opacity: 0.8}}>{error}</div>
            </div>
          </div>
        )}

        {result && (
          <div className="result-container">
            {result.success ? (
              <>
                <div className="card">
                  <div className="card-header">
                    <div className="card-icon"><Icons.Activity /></div>
                    <h3 className="card-title">Analysis Result</h3>
                  </div>
                  <div className="card-body">
                    <div className="answer-text">{result.answer}</div>

                    {result.summary && (
                      <div className="summary-box">
                        <p>{result.summary}</p>
                      </div>
                    )}

                    {result.insights && result.insights.length > 0 && (
                      <ul className="insights-list">
                        {result.insights.map((insight, idx) => (
                          <li key={idx}>
                            <span className="insight-bullet">✦</span>
                            <span>{insight}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </div>

                <div className="details-grid">
                  <div className="card">
                    <div className="card-header">
                      <div className="card-icon"><Icons.Terminal /></div>
                      <h3 className="card-title">Execution Context</h3>
                    </div>
                    <div className="card-body">
                      <div className="meta-grid" style={{marginBottom: '1.5rem'}}>
                        <div className="meta-row">
                          <span className="meta-label">Execution Time</span>
                          <span className="meta-value">{result.execution_time_ms?.toFixed(2)} ms</span>
                        </div>
                        <div className="meta-row">
                          <span className="meta-label">Rows Returned</span>
                          <span className="meta-value">{result.row_count}</span>
                        </div>
                        <div className="meta-row">
                          <span className="meta-label">Sources</span>
                          <span className="meta-value">{result.relevant_tables?.join(', ')}</span>
                        </div>
                      </div>
                      
                      <div className="meta-label" style={{marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em'}}>Generated SQL</div>
                      <pre className="sql-block"><code>{result.sql}</code></pre>
                    </div>
                  </div>

                  <div className="card">
                    <div className="card-header">
                      <div className="card-icon"><Icons.Database /></div>
                      <h3 className="card-title">System Trace</h3>
                    </div>
                    <div className="card-body">
                      <div className="agent-flow">
                        {Object.entries(result.agent_flow || {}).map(([agent, status]) => (
                          <div key={agent} className={`agent-step ${status}`}>
                            <span className="agent-name">{agent}</span>
                            <span className="agent-status">{status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>

                {result.data && result.data.length > 0 && (
                  <div className="card">
                    <div className="card-header">
                      <div className="card-icon"><Icons.Database /></div>
                      <h3 className="card-title">Data Output (Top 10 rows)</h3>
                    </div>
                    <div className="card-body" style={{padding: '1px'}}>
                      <div className="table-container">
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
                  </div>
                )}
              </>
            ) : (
              <div className="error-message">
                <Icons.Alert />
                <div>
                  <strong>Query Failed</strong>
                  <div style={{fontSize: '0.875rem', marginTop: '0.25rem', opacity: 0.8}}>{result.error}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {stats && !result && (
          <div className="stats-container">
            <div className="stats-grid">
              <div className="stat-item">
                <span className="stat-label">Companies</span>
                <span className="stat-value">{stats.database?.companies || 0}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Statements</span>
                <span className="stat-value">{stats.database?.financial_statements || 0}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Metrics</span>
                <span className="stat-value">{stats.database?.performance_metrics || 0}</span>
              </div>
              <div className="stat-item">
                <span className="stat-label">Data Points</span>
                <span className="stat-value">{stats.database?.market_data || 0}</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

export default App
