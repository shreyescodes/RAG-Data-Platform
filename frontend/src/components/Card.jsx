export function Card({ title, actions, children, flush = false }) {
  return (
    <section className="card">
      <header className="card-header">
        <h3 className="card-title">{title}</h3>
        {actions && <div className="card-actions">{actions}</div>}
      </header>
      <div className={flush ? 'card-body card-body--flush' : 'card-body'}>{children}</div>
    </section>
  )
}
