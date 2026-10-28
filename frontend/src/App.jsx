import { useState } from 'react'
import './App.css'
import { AgentTrace } from './components/AgentTrace.jsx'
import { AnswerCard } from './components/AnswerCard.jsx'
import { EnrichmentPanel } from './components/EnrichmentPanel.jsx'
import { ErrorBanner } from './components/ErrorBanner.jsx'
import { ExampleQueries } from './components/ExampleQueries.jsx'
import { ExecutionDetails } from './components/ExecutionDetails.jsx'
import { HistoryPanel } from './components/HistoryPanel.jsx'
import { QueryForm } from './components/QueryForm.jsx'
import { ResultChart } from './components/ResultChart.jsx'
import { ResultsTable } from './components/ResultsTable.jsx'
import { StatsBar } from './components/StatsBar.jsx'
import { usePlatformData } from './hooks/usePlatformData.js'
import { useQueryRunner } from './hooks/useQueryRunner.js'

function QueryResult({ result }) {
  if (!result.success) {
    return (
      <>
        <ErrorBanner title="Query could not be answered" message={result.error} />
        <AgentTrace flow={result.agent_flow} trace={result.trace} />
      </>
    )
  }
  return (
    <>
      <AnswerCard
        answer={result.answer}
        summary={result.summary}
        insights={result.insights}
        degraded={result.agent_flow?.analysis === 'degraded'}
      />
      <ResultChart key={result.sql} rows={result.data} />
      <EnrichmentPanel data={result.enriched_data} />
      <div className="details-grid">
        <ExecutionDetails result={result} />
        <AgentTrace flow={result.agent_flow} trace={result.trace} />
      </div>
      <ResultsTable rows={result.data} />
    </>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
  const { stats, history, refresh } = usePlatformData()
  const { loading, result, error, run, cancel, reset } = useQueryRunner({ onSettled: refresh })

  const runQuery = (text) => {
    setQuery(text)
    run(text)
  }

  const startOver = () => {
    reset()
    setQuery('')
  }

  const idle = !result && !error

  return (
    <div className="app">
      <header className="header">
        <button type="button" className="brand" onClick={startOver}>
          <h1>RAG Financial Terminal</h1>
        </button>
      </header>

      <main className="main">
        {idle && (
          <div className="hero">
            <h2>Query intelligence</h2>
            <p>Ask questions about structured financial data in plain English.</p>
          </div>
        )}

        <div className="query-section">
          <QueryForm
            value={query}
            onChange={setQuery}
            onSubmit={runQuery}
            onCancel={cancel}
            loading={loading}
          />
          {idle && <ExampleQueries onSelect={runQuery} disabled={loading} />}
        </div>

        <div aria-live="polite" aria-busy={loading}>
          {loading && <p className="loading-text">Retrieving schema, generating SQL and analysing results…</p>}
          {error && (
            <ErrorBanner
              title="Request failed"
              message={error.message}
              requestId={error.requestId}
            />
          )}
          {result && (
            <div className="result-container">
              <QueryResult result={result} />
            </div>
          )}
        </div>

        <HistoryPanel items={history} onSelect={runQuery} disabled={loading} />
        {idle && <StatsBar stats={stats} />}
      </main>
    </div>
  )
}
