import { useEffect, useState } from 'react'
import './App.css'
import { AgentTrace } from './components/AgentTrace.jsx'
import { AnswerCard } from './components/AnswerCard.jsx'
import { CitationsPanel } from './components/CitationsPanel.jsx'
import { EnrichmentPanel } from './components/EnrichmentPanel.jsx'
import { ErrorBanner } from './components/ErrorBanner.jsx'
import { ExampleQueries } from './components/ExampleQueries.jsx'
import { ExecutionDetails } from './components/ExecutionDetails.jsx'
import { ComposeIcon, PanelIcon } from './components/Icons.jsx'
import { ObservabilityPage } from './components/ObservabilityPage.jsx'
import { QueryForm } from './components/QueryForm.jsx'
import { ResultChart } from './components/ResultChart.jsx'
import { ResultsTable } from './components/ResultsTable.jsx'
import { Sidebar } from './components/Sidebar.jsx'
import { VerificationPanel } from './components/VerificationPanel.jsx'
import { useGlassLens } from './hooks/useGlassLens.js'
import { usePlatformData } from './hooks/usePlatformData.js'
import { useQueryRunner } from './hooks/useQueryRunner.js'
import { isNarrowViewport, useSidebar } from './hooks/useSidebar.js'

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
      <VerificationPanel report={result.verification} />
      <ResultChart key={result.sql} rows={result.data} />
      <EnrichmentPanel data={result.enriched_data} />
      <CitationsPanel citations={result.citations} />
      <div className="details-grid">
        <ExecutionDetails result={result} />
        <AgentTrace flow={result.agent_flow} trace={result.trace} />
      </div>
      <ResultsTable rows={result.data} />
    </>
  )
}

const OBSERVABILITY_HASH = '#/observability'

/** The current section, from the URL hash so it can be linked and bookmarked. */
function useSection() {
  const [hash, setHash] = useState(() => window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash === OBSERVABILITY_HASH ? 'observability' : 'query'
}

export default function App() {
  const section = useSection()
  const headerRef = useGlassLens()
  const sidebar = useSidebar()
  const [query, setQuery] = useState('')
  const [asked, setAsked] = useState(null)
  const { history, refresh } = usePlatformData()
  const { loading, result, error, run, cancel, reset } = useQueryRunner({ onSettled: refresh })

  const showChat = () => {
    if (window.location.hash === OBSERVABILITY_HASH) window.location.hash = '#/'
    sidebar.closeDrawer()
  }

  const runQuery = (text) => {
    showChat()
    setAsked(text)
    setQuery('')
    run(text)
  }

  const startOver = () => {
    cancel()
    reset()
    setAsked(null)
    setQuery('')
    showChat()
    if (!isNarrowViewport()) {
      requestAnimationFrame(() => document.getElementById('query-input')?.focus())
    }
  }

  // Stopping a question hands it back, ready to edit.
  const stopQuery = () => {
    cancel()
    setQuery(asked ?? '')
    setAsked(null)
  }

  const idle = !asked

  return (
    <div className="app" data-sidebar={sidebar.open ? 'open' : 'closed'}>
      <h1 className="visually-hidden">RAG Financial Terminal</h1>
      <Sidebar
        history={history}
        activeQuery={asked}
        observabilityActive={section === 'observability'}
        disabled={loading}
        onNewChat={startOver}
        onSelect={runQuery}
        onNavigate={sidebar.closeDrawer}
        onClose={sidebar.toggle}
      />
      {sidebar.open && <div className="sidebar-scrim" aria-hidden="true" onClick={sidebar.closeDrawer} />}

      <div className="workspace">
      <header className="header" ref={headerRef}>
        <button
          type="button"
          id="sidebar-toggle"
          className="icon-btn"
          onClick={sidebar.toggle}
          aria-label="Open sidebar"
          aria-expanded={sidebar.open}
          aria-controls="sidebar"
        >
          <PanelIcon />
        </button>
        <span className="brand-name">RAG Financial Terminal</span>
        <button type="button" className="icon-btn" onClick={startOver} aria-label="Start a new chat">
          <ComposeIcon />
        </button>
      </header>

      {section === 'observability' ? (
        <main className="main">
          <ObservabilityPage />
        </main>
      ) : (
      <main className="main">
        {idle && (
          <div className="hero">
            <h2>Ask the data.</h2>
            <p>Plain-English answers from SEC filings and market data, with the SQL and evidence behind each one.</p>
          </div>
        )}

        <div className="query-section">
          <QueryForm
            value={query}
            onChange={setQuery}
            onSubmit={runQuery}
            onCancel={stopQuery}
            loading={loading}
          />
          {idle && <ExampleQueries onSelect={runQuery} disabled={loading} />}
        </div>

        {asked && (
          <div className="conversation">
            <p className="asked">{asked}</p>
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
          </div>
        )}

      </main>
      )}
      </div>
    </div>
  )
}
