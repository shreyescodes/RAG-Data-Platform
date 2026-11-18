import { ActivityIcon, ComposeIcon, PanelIcon } from './Icons.jsx'

/** The latest run of each question, keeping the newest-first order. */
function latestRuns(items) {
  const seen = new Set()
  return items.filter((item) => {
    const question = item.query.trim().toLowerCase()
    if (seen.has(question)) return false
    seen.add(question)
    return true
  })
}

export function Sidebar({
  history,
  activeQuery,
  observabilityActive,
  disabled,
  onNewChat,
  onSelect,
  onNavigate,
  onClose,
}) {
  const recent = latestRuns(history)

  return (
    <aside id="sidebar" className="sidebar" aria-label="Chats">
      <div className="sidebar-top">
        <button type="button" className="brand" onClick={onNewChat}>
          <span className="brand-name">RAG Financial Terminal</span>
        </button>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close sidebar">
          <PanelIcon />
        </button>
      </div>

      <button type="button" id="new-chat" className="new-chat" onClick={onNewChat}>
        <ComposeIcon />
        New chat
      </button>
      <a
        className="sidebar-link"
        href="#/observability"
        onClick={onNavigate}
        aria-current={observabilityActive ? 'page' : undefined}
      >
        <ActivityIcon />
        Observability
      </a>

      <h2 className="sidebar-label">Recent</h2>
      {recent.length > 0 ? (
        <ul className="history-list">
          {recent.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className="history-item"
                onClick={() => onSelect(item.query)}
                disabled={disabled}
                title={item.query}
                aria-current={!observabilityActive && item.query === activeQuery ? 'true' : undefined}
              >
                <span className="history-query">{item.query}</span>
                {!item.success && <span className="status-dot fail" role="img" aria-label="failed" />}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="sidebar-empty">Your questions will appear here.</p>
      )}
    </aside>
  )
}
