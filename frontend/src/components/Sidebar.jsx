import { ActivityIcon, ComposeIcon, PanelIcon } from './Icons.jsx'

/** One row per chat, newest first, titled by the question that started it. */
function chats(items) {
  const byId = new Map()
  for (const item of items) {
    if (!item.conversation_id) continue
    const chat = byId.get(item.conversation_id)
    if (chat) chat.title = item.query
    else byId.set(item.conversation_id, { id: item.conversation_id, title: item.query, failed: !item.success })
  }
  return [...byId.values()]
}

export function Sidebar({
  history,
  activeChat,
  observabilityActive,
  onNewChat,
  onSelect,
  onNavigate,
  onClose,
}) {
  const recent = chats(history)

  return (
    <aside id="sidebar" className="sidebar" aria-label="Chats">
      <div className="sidebar-top">
        <button type="button" className="brand" onClick={onNewChat}>
          <span className="brand-name">RAG Data Platform</span>
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
          {recent.map((chat) => (
            <li key={chat.id}>
              <button
                type="button"
                className="history-item"
                onClick={() => onSelect(chat.id)}
                title={chat.title}
                aria-current={!observabilityActive && chat.id === activeChat ? 'true' : undefined}
              >
                <span className="history-query">{chat.title}</span>
                {chat.failed && <span className="status-dot fail" role="img" aria-label="failed" />}
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
