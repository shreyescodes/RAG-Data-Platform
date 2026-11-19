import { useEffect, useRef, useState } from 'react'
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
import { ProgressSteps } from './components/ProgressSteps.jsx'
import { QueryForm } from './components/QueryForm.jsx'
import { ResultChart } from './components/ResultChart.jsx'
import { ResultsTable } from './components/ResultsTable.jsx'
import { Sidebar } from './components/Sidebar.jsx'
import { VerificationPanel } from './components/VerificationPanel.jsx'
import { useConversation } from './hooks/useConversation.js'
import { useGlassLens } from './hooks/useGlassLens.js'
import { usePlatformData } from './hooks/usePlatformData.js'
import { isNarrowViewport, useSidebar } from './hooks/useSidebar.js'

function QueryResult({ result, rowPrefix }) {
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
      <VerificationPanel report={result.verification} rowPrefix={rowPrefix} />
      <ResultChart key={result.sql} rows={result.data} />
      <EnrichmentPanel data={result.enriched_data} />
      <CitationsPanel citations={result.citations} />
      <div className="details-grid">
        <ExecutionDetails result={result} />
        <AgentTrace flow={result.agent_flow} trace={result.trace} />
      </div>
      <ResultsTable rows={result.data} rowPrefix={rowPrefix} />
    </>
  )
}

function Turn({ turn, rowPrefix }) {
  const running = turn.status === 'running'
  return (
    <article className="turn">
      <p className="asked">{turn.question}</p>
      <div aria-live="polite" aria-busy={running}>
        {running && <ProgressSteps stages={turn.stages} />}
        {turn.error && (
          <ErrorBanner
            title="Request failed"
            message={turn.error.message}
            requestId={turn.error.requestId}
          />
        )}
        {turn.result && (
          <div className="result-container">
            <QueryResult result={turn.result} rowPrefix={rowPrefix} />
          </div>
        )}
      </div>
    </article>
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
  const { history, refresh } = usePlatformData()
  const chat = useConversation({ onSettled: refresh })
  const latestTurnRef = useRef(null)
  const turnCount = chat.turns.length

  useEffect(() => {
    if (turnCount > 1) latestTurnRef.current?.scrollIntoView?.({ block: 'start' })
  }, [turnCount])

  const showChat = () => {
    if (window.location.hash === OBSERVABILITY_HASH) window.location.hash = '#/'
    sidebar.closeDrawer()
  }

  const askQuestion = (text) => {
    showChat()
    setQuery('')
    chat.ask(text)
  }

  const openChat = (id) => {
    showChat()
    setQuery('')
    chat.open(id)
  }

  const startOver = () => {
    chat.reset()
    setQuery('')
    showChat()
    if (!isNarrowViewport()) {
      requestAnimationFrame(() => document.getElementById('query-input')?.focus())
    }
  }

  // Stopping a question hands it back, ready to edit.
  const stopQuestion = () => {
    const question = chat.turns.at(-1)?.question ?? ''
    chat.stop()
    setQuery(question)
  }

  const idle = turnCount === 0 && !chat.opening && !chat.openError

  return (
    <div className="app" data-sidebar={sidebar.open ? 'open' : 'closed'}>
      <h1 className="visually-hidden">RAG Data Platform</h1>
      <Sidebar
        history={history}
        activeChat={chat.conversationId}
        observabilityActive={section === 'observability'}
        onNewChat={startOver}
        onSelect={openChat}
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
        <span className="brand-name">RAG Data Platform</span>
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
            onSubmit={askQuestion}
            onCancel={stopQuestion}
            loading={chat.loading}
          />
          {idle && <ExampleQueries onSelect={askQuestion} disabled={chat.loading} />}
        </div>

        {!idle && (
          <div className="conversation">
            {chat.opening && <p className="opening-text">Opening this chat…</p>}
            {chat.openError && (
              <ErrorBanner
                title="This chat could not be opened"
                message={chat.openError.message}
                requestId={chat.openError.requestId}
              />
            )}
            {chat.turns.map((turn, index) => (
              <div key={turn.key} ref={index === turnCount - 1 ? latestTurnRef : null}>
                <Turn turn={turn} rowPrefix={index ? `turn-${index}-` : ''} />
              </div>
            ))}
          </div>
        )}
      </main>
      )}
      </div>
    </div>
  )
}
