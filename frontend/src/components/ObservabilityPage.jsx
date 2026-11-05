import { useState } from 'react'
import { useMetrics } from '../hooks/useMetrics.js'
import {
  formatCompact,
  formatDuration,
  formatRate,
  formatRelativeTime,
  formatUsd,
} from '../utils/format.js'
import { Card } from './Card.jsx'
import { ErrorBanner } from './ErrorBanner.jsx'
import { ActivityIcon, AlertIcon, ClockIcon, DatabaseIcon, GaugeIcon, TrendIcon } from './Icons.jsx'
import { TimeSeriesChart } from './TimeSeriesChart.jsx'

const WINDOWS = [
  ['1h', 'Last hour'],
  ['6h', '6 hours'],
  ['24h', '24 hours'],
  ['7d', '7 days'],
  ['30d', '30 days'],
]

// Series colors are the validated categorical slots; failures use the reserved
// status color because they mean "bad", never a categorical slot.
const REQUEST_SERIES = [
  { key: 'successes', label: 'Succeeded', color: 'var(--series-1)' },
  { key: 'failures', label: 'Failed', color: 'var(--status-critical)' },
]
const TOKEN_SERIES = [
  { key: 'prompt_tokens', label: 'Prompt', color: 'var(--series-1)' },
  { key: 'completion_tokens', label: 'Completion', color: 'var(--series-2)' },
]
const LATENCY_SERIES = [
  { key: 'latency_p50_ms', label: 'p50', color: 'var(--series-1)' },
  { key: 'latency_p95_ms', label: 'p95', color: 'var(--series-2)' },
]
const COST_SERIES = [{ key: 'cost_usd', label: 'Estimated cost', color: 'var(--series-1)' }]

const STAGE_LABELS = {
  retrieval: 'Schema retrieval',
  sql_generation: 'SQL generation',
  sql_execution: 'SQL execution',
  enrichment: 'Live data',
  analysis: 'Analysis',
  verification: 'Fact check',
}

const compactAxis = (v) => (Math.abs(v) >= 1000 ? formatCompact(v) : String(v))
const msAxis = (v) => (v >= 1000 ? `${v / 1000}s` : `${v}ms`)

function StatTile({ label, value, detail }) {
  return (
    <div className="stat-tile">
      <dt className="stat-label">{label}</dt>
      <dd className="stat-tile-value">{value}</dd>
      {detail && <dd className="stat-tile-detail">{detail}</dd>}
    </div>
  )
}

function KpiRow({ summary }) {
  const flagged = summary.verification
  return (
    <dl className="kpi-row" aria-label="Key metrics">
      <StatTile label="Requests" value={formatCompact(summary.requests)} detail={`${summary.failures} failed`} />
      <StatTile label="Error rate" value={formatRate(summary.error_rate)} />
      <StatTile label="Latency p50" value={formatDuration(summary.latency_ms.p50)} />
      <StatTile label="Latency p95" value={formatDuration(summary.latency_ms.p95)} />
      <StatTile
        label="Tokens"
        value={formatCompact(summary.tokens.total)}
        detail={`${formatCompact(summary.tokens.prompt)} prompt · ${formatCompact(summary.tokens.completion)} completion`}
      />
      <StatTile
        label="Estimated cost"
        value={formatUsd(summary.cost_usd)}
        detail={`${formatUsd(summary.avg_cost_per_request_usd)} per request`}
      />
      <StatTile
        label="Cache hit rate"
        value={formatRate(summary.cache_hit_rate)}
        detail={`${summary.cache_hits} of ${summary.llm_calls} LLM calls`}
      />
      <StatTile
        label="Answers flagged"
        value={`${flagged.flagged} of ${flagged.checked}`}
        detail={`${flagged.unsupported_claims} unsupported claims`}
      />
    </dl>
  )
}

function ShareBar({ value, max }) {
  const pct = max > 0 ? Math.max(1, (value / max) * 100) : 0
  return (
    <span className="share-track" aria-hidden="true">
      <span className="share-fill" style={{ width: `${pct}%` }} />
    </span>
  )
}

function StageTable({ stages }) {
  const entries = Object.entries(stages)
  if (!entries.length) return <p className="empty-note">No stage timings yet.</p>
  const max = Math.max(...entries.map(([, s]) => s.p95 ?? 0))
  return (
    <div className="table-container">
      <table>
        <caption className="visually-hidden">Latency by pipeline stage</caption>
        <thead>
          <tr>
            <th scope="col">Stage</th>
            <th scope="col" className="num">p50</th>
            <th scope="col" className="num">p95</th>
            <th scope="col" className="share-col">
              <span className="visually-hidden">p95 relative to the slowest stage</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([stage, s]) => (
            <tr key={stage}>
              <th scope="row">{STAGE_LABELS[stage] ?? stage}</th>
              <td className="num">{formatDuration(s.p50)}</td>
              <td className="num">{formatDuration(s.p95)}</td>
              <td className="share-col">
                <ShareBar value={s.p95 ?? 0} max={max} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModelTable({ models }) {
  if (!models.length) return <p className="empty-note">No LLM calls yet.</p>
  return (
    <div className="table-container">
      <table>
        <caption className="visually-hidden">Usage by model</caption>
        <thead>
          <tr>
            <th scope="col">Model</th>
            <th scope="col" className="num">Requests</th>
            <th scope="col" className="num">LLM calls</th>
            <th scope="col" className="num">Failed</th>
            <th scope="col" className="num">Cached</th>
            <th scope="col" className="num">Tokens</th>
            <th scope="col" className="num">Cost</th>
            <th scope="col" className="num">Avg latency</th>
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model}>
              <th scope="row">
                <code>{m.model}</code>
              </th>
              <td className="num">{m.requests}</td>
              <td className="num">{m.llm_calls}</td>
              <td className="num">{m.failed_calls}</td>
              <td className="num">{m.cache_hits}</td>
              <td className="num">{formatCompact(m.prompt_tokens + m.completion_tokens)}</td>
              <td className="num">{formatUsd(m.cost_usd)}</td>
              <td className="num">{formatDuration(m.avg_latency_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PurposeTable({ purposes }) {
  if (!purposes.length) return null
  const total = (p) => p.prompt_tokens + p.completion_tokens
  const max = Math.max(...purposes.map(total))
  return (
    <div className="table-container">
      <table>
        <caption className="visually-hidden">Tokens by pipeline step</caption>
        <thead>
          <tr>
            <th scope="col">Step</th>
            <th scope="col" className="num">Calls</th>
            <th scope="col" className="num">Tokens</th>
            <th scope="col" className="num">Cost</th>
            <th scope="col" className="share-col">
              <span className="visually-hidden">Tokens relative to the largest step</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {purposes.map((p) => (
            <tr key={p.purpose}>
              <th scope="row">{p.purpose.replace('_', ' ')}</th>
              <td className="num">{p.llm_calls}</td>
              <td className="num">{formatCompact(total(p))}</td>
              <td className="num">{formatUsd(p.cost_usd)}</td>
              <td className="share-col">
                <ShareBar value={total(p)} max={max} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function QueryList({ rows, empty, columns }) {
  if (!rows.length) return <p className="empty-note">{empty}</p>
  return (
    <div className="table-container">
      <table>
        <thead>
          <tr>
            <th scope="col">Query</th>
            {columns.map(([label]) => (
              <th scope="col" key={label} className="num">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row.query}-${i}`}>
              <th scope="row" className="query-cell">
                {row.query}
              </th>
              {columns.map(([label, render]) => (
                <td key={label} className="num">
                  {render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RecentTable({ requests }) {
  if (!requests.length) return <p className="empty-note">No requests recorded yet.</p>
  return (
    <div className="table-container">
      <table>
        <caption className="visually-hidden">Most recent requests</caption>
        <thead>
          <tr>
            <th scope="col">When</th>
            <th scope="col">Query</th>
            <th scope="col">Outcome</th>
            <th scope="col" className="num">Latency</th>
            <th scope="col" className="num">Tokens</th>
            <th scope="col" className="num">Cost</th>
            <th scope="col">Model</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((r) => (
            <tr key={r.id}>
              <td>{formatRelativeTime(r.created_at)}</td>
              <th scope="row" className="query-cell">
                {r.query}
              </th>
              <td>
                <span className={`outcome ${r.success ? 'outcome-ok' : 'outcome-failed'}`}>
                  {r.success ? 'ok' : (r.error_type ?? 'failed')}
                </span>
                {r.verification_status === 'flagged' && <span className="outcome outcome-flagged">flagged</span>}
                {r.cache_hits > 0 && <span className="outcome">cache ×{r.cache_hits}</span>}
              </td>
              <td className="num">{formatDuration(r.latency_ms)}</td>
              <td className="num">{formatCompact(r.prompt_tokens + r.completion_tokens)}</td>
              <td className="num">{formatUsd(r.cost_usd)}</td>
              <td>
                <code>{r.model}</code> <span className="endpoint-tag">{r.llm_endpoint}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ObservabilityPage() {
  const [range, setRange] = useState('24h')
  const { summary, timeseries, recent, loading, error, updatedAt, refresh } = useMetrics(range)
  const points = (timeseries?.points ?? []).map((p) => ({ ...p, successes: p.requests - p.failures }))
  // Empty means no traffic: a free local model still has a (zero) cost line.
  const noRequests = points.every((p) => p.requests === 0)

  return (
    <div className="observability">
      <div className="obs-toolbar" role="toolbar" aria-label="Dashboard filters">
        <div className="segmented" role="group" aria-label="Time window">
          {WINDOWS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={range === value}
              className={range === value ? 'segment is-active' : 'segment'}
              onClick={() => setRange(value)}
            >
              {label}
            </button>
          ))}
        </div>
        <button type="button" className="text-btn" onClick={refresh} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
        {updatedAt && (
          <span className="obs-updated">
            Updated {updatedAt.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {error && <ErrorBanner title="Metrics unavailable" message={error.message} requestId={error.requestId} />}

      {summary && (
        <div className={loading ? 'obs-body is-refreshing' : 'obs-body'} aria-busy={loading}>
          <KpiRow summary={summary} />

          <div className="obs-grid">
            <TimeSeriesChart
              title="Requests"
              icon={ActivityIcon}
              kind="stack"
              points={points}
              series={REQUEST_SERIES}
              bucketSeconds={timeseries.bucket_seconds}
              empty={noRequests}
              format={(v) => String(v)}
            />
            <TimeSeriesChart
              title="Latency"
              icon={ClockIcon}
              kind="line"
              points={points}
              series={LATENCY_SERIES}
              bucketSeconds={timeseries.bucket_seconds}
              empty={noRequests}
              format={formatDuration}
              axisFormat={msAxis}
            />
            <TimeSeriesChart
              title="Tokens"
              icon={DatabaseIcon}
              kind="stack"
              points={points}
              series={TOKEN_SERIES}
              bucketSeconds={timeseries.bucket_seconds}
              empty={noRequests}
              format={(v) => v.toLocaleString('en-US')}
              axisFormat={compactAxis}
            />
            <TimeSeriesChart
              title="Estimated cost"
              icon={TrendIcon}
              kind="line"
              points={points}
              series={COST_SERIES}
              bucketSeconds={timeseries.bucket_seconds}
              empty={noRequests}
              format={formatUsd}
            />
          </div>

          <div className="obs-grid">
            <Card icon={ClockIcon} title="Latency by stage">
              <StageTable stages={summary.stage_latency_ms} />
            </Card>
            <Card icon={GaugeIcon} title="Tokens by step">
              <PurposeTable purposes={summary.purposes} />
            </Card>
          </div>

          <Card icon={DatabaseIcon} title="Models">
            <ModelTable models={summary.models} />
          </Card>

          <div className="obs-grid">
            <Card icon={AlertIcon} title="Top failing queries">
              <QueryList
                rows={summary.top_failing_queries}
                empty="No failures in this window."
                columns={[
                  ['Failures', (r) => r.failures],
                  ['Last error', (r) => r.last_error ?? '—'],
                ]}
              />
            </Card>
            <Card icon={TrendIcon} title="Most expensive queries">
              <QueryList
                rows={summary.most_expensive_queries}
                empty="No LLM usage in this window."
                columns={[
                  ['Cost', (r) => formatUsd(r.cost_usd)],
                  ['Tokens', (r) => formatCompact(r.total_tokens)],
                ]}
              />
            </Card>
          </div>

          <Card icon={ActivityIcon} title="Recent requests">
            <RecentTable requests={recent} />
          </Card>
        </div>
      )}
    </div>
  )
}
