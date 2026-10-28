import { useId, useMemo, useState } from 'react'
import { humanize, inferChart, niceTicks } from '../utils/chartSpec.js'
import { formatCell, formatCompact } from '../utils/format.js'
import { Card } from './Card.jsx'
import { TrendIcon } from './Icons.jsx'

const WIDTH = 720
const SERIES_VARS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']

const axisValue = (v) => (Math.abs(v) >= 1000 ? formatCompact(v) : formatCell(v))

function formatDate(ms, spanDays) {
  const opts =
    spanDays > 540
      ? { month: 'short', year: 'numeric' }
      : { month: 'short', day: 'numeric', ...(spanDays > 300 ? { year: '2-digit' } : {}) }
  return new Date(ms).toLocaleDateString('en-US', { timeZone: 'UTC', ...opts })
}

function Tooltip({ x, y, title, items }) {
  // Positioned in percentages of the SVG so it tracks the responsive viewBox.
  const flip = x > 0.6
  return (
    <div
      className="chart-tooltip"
      role="status"
      style={{
        left: `${x * 100}%`,
        top: `${y * 100}%`,
        transform: `translate(${flip ? 'calc(-100% - 12px)' : '12px'}, -50%)`,
      }}
    >
      <div className="chart-tooltip-title">{title}</div>
      {items.map((item) => (
        <div className="chart-tooltip-row" key={item.label}>
          {item.color && <span className="chart-swatch" style={{ background: item.color }} />}
          <span className="chart-tooltip-label">{item.label}</span>
          <span className="chart-tooltip-value">{formatCell(item.value)}</span>
        </div>
      ))}
    </div>
  )
}

function Legend({ series }) {
  if (series.length < 2) return null
  return (
    <ul className="chart-legend">
      {series.map((s, i) => (
        <li key={s.key}>
          <span className="chart-swatch chart-swatch--line" style={{ background: SERIES_VARS[i] }} />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

function LineChart({ spec }) {
  const [hover, setHover] = useState(null)
  const margin = { top: 12, right: 112, bottom: 30, left: 56 }
  const height = 300
  const innerW = WIDTH - margin.left - margin.right
  const innerH = height - margin.top - margin.bottom

  const allPoints = spec.series.flatMap((s) => s.points)
  const xs = [...new Set(allPoints.map((p) => p.x))].sort((a, b) => a - b)
  const [xMin, xMax] = [xs[0], xs[xs.length - 1]]
  const ticks = niceTicks(Math.min(...allPoints.map((p) => p.y)), Math.max(...allPoints.map((p) => p.y)))
  const [yMin, yMax] = [ticks[0], ticks[ticks.length - 1]]
  const spanDays = (xMax - xMin) / 86_400_000

  const sx = (x) => margin.left + (xMax === xMin ? innerW / 2 : ((x - xMin) / (xMax - xMin)) * innerW)
  const sy = (y) => margin.top + innerH - ((y - yMin) / (yMax - yMin)) * innerH
  const xTicks = Array.from({ length: 5 }, (_, i) => xMin + ((xMax - xMin) * i) / 4)

  // End labels, nudged apart so they never overlap.
  const ends = spec.series
    .map((s, i) => ({ s, i, y: sy(s.points[s.points.length - 1].y) }))
    .sort((a, b) => a.y - b.y)
  for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 15)

  const nearest = (clientX, rect) => {
    const x = xMin + ((((clientX - rect.left) / rect.width) * WIDTH - margin.left) / innerW) * (xMax - xMin)
    return xs.reduce((best, v) => (Math.abs(v - x) < Math.abs(best - x) ? v : best), xs[0])
  }
  const step = (dir) => {
    const idx = hover === null ? (dir > 0 ? -1 : xs.length) : xs.indexOf(hover)
    setHover(xs[Math.min(xs.length - 1, Math.max(0, idx + dir))])
  }

  const hoverItems =
    hover === null
      ? []
      : spec.series
          .map((s, i) => ({ s, i, p: s.points.find((p) => p.x === hover) }))
          .filter((h) => h.p)

  return (
    <div className="chart-frame">
      <Legend series={spec.series} />
      <svg
        viewBox={`0 0 ${WIDTH} ${height}`}
        className="chart-svg"
        role="img"
        aria-label={`${spec.title} over time`}
        tabIndex={0}
        onMouseMove={(e) => setHover(nearest(e.clientX, e.currentTarget.getBoundingClientRect()))}
        onMouseLeave={() => setHover(null)}
        onBlur={() => setHover(null)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') step(1)
          else if (e.key === 'ArrowLeft') step(-1)
          else return
          e.preventDefault()
        }}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={margin.left} x2={margin.left + innerW} y1={sy(t)} y2={sy(t)} />
            <text className="chart-axis" x={margin.left - 8} y={sy(t)} dy="0.32em" textAnchor="end">
              {axisValue(t)}
            </text>
          </g>
        ))}
        {xTicks.map((t, i) => (
          <text
            key={t}
            className="chart-axis"
            x={sx(t)}
            y={height - 8}
            textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}
          >
            {formatDate(t, spanDays)}
          </text>
        ))}

        {spec.series.map((s, i) => (
          <path
            key={s.key}
            className="chart-line"
            stroke={SERIES_VARS[i]}
            d={s.points.map((p, k) => `${k ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join('')}
          />
        ))}

        {ends.map(({ s, i, y }) => {
          const last = s.points[s.points.length - 1]
          return (
            <g key={s.key}>
              <circle className="chart-dot" cx={sx(last.x)} cy={sy(last.y)} r={4} fill={SERIES_VARS[i]} />
              <text className="chart-end-label" x={sx(last.x) + 10} y={y} dy="0.32em">
                {spec.series.length > 1 ? s.label : axisValue(last.y)}
              </text>
            </g>
          )
        })}

        {hover !== null && (
          <g>
            <line className="chart-crosshair" x1={sx(hover)} x2={sx(hover)} y1={margin.top} y2={margin.top + innerH} />
            {hoverItems.map(({ s, i, p }) => (
              <circle key={s.key} className="chart-dot" cx={sx(p.x)} cy={sy(p.y)} r={4.5} fill={SERIES_VARS[i]} />
            ))}
          </g>
        )}
      </svg>
      {hover !== null && hoverItems.length > 0 && (
        <Tooltip
          x={sx(hover) / WIDTH}
          y={sy(hoverItems[0].p.y) / height}
          title={formatDate(hover, 0) + (spanDays > 300 ? `, ${new Date(hover).getUTCFullYear()}` : '')}
          items={hoverItems.map(({ s, i, p }) => ({ label: s.label, value: p.y, color: SERIES_VARS[i] }))}
        />
      )}
    </div>
  )
}

function BarChart({ spec }) {
  const [hover, setHover] = useState(null)
  const band = 30
  const thickness = 18
  const labelWidth = 170
  const margin = { top: 8, right: 72, bottom: 26, left: labelWidth }
  const height = margin.top + margin.bottom + band * spec.bars.length
  const innerW = WIDTH - margin.left - margin.right

  const values = spec.bars.map((b) => b.value)
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values), 5)
  const [lo, hi] = [ticks[0], ticks[ticks.length - 1]]
  const sx = (v) => margin.left + ((v - lo) / (hi - lo)) * innerW
  const zero = sx(0)

  // Rounded at the data end, square at the baseline.
  const barPath = (value, y) => {
    const end = sx(value)
    const r = Math.min(4, Math.abs(end - zero) / 2, thickness / 2)
    const dir = value >= 0 ? 1 : -1
    const tip = end - dir * r
    return [
      `M${zero},${y}`,
      `H${tip}`,
      `A${r},${r} 0 0 ${dir > 0 ? 1 : 0} ${end},${y + r}`,
      `V${y + thickness - r}`,
      `A${r},${r} 0 0 ${dir > 0 ? 1 : 0} ${tip},${y + thickness}`,
      `H${zero}`,
      'Z',
    ].join('')
  }
  const truncate = (s) => (s.length > 24 ? `${s.slice(0, 23)}…` : s)

  return (
    <div className="chart-frame">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="chart-svg" role="img" aria-label={`${spec.title} by ${humanize(spec.label)}`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={sx(t)} x2={sx(t)} y1={margin.top} y2={height - margin.bottom} />
            <text className="chart-axis" x={sx(t)} y={height - 8} textAnchor="middle">
              {axisValue(t)}
            </text>
          </g>
        ))}
        {spec.bars.map((b, i) => {
          const y = margin.top + i * band + (band - thickness) / 2
          const active = hover === i
          return (
            <g
              key={b.label}
              className="chart-bar-row"
              tabIndex={0}
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
            >
              <rect x={0} y={margin.top + i * band} width={WIDTH} height={band} fill="transparent" />
              <text className="chart-category" x={labelWidth - 12} y={y + thickness / 2} dy="0.32em" textAnchor="end">
                {truncate(b.label)}
              </text>
              <path d={barPath(b.value, y)} fill="var(--series-1)" opacity={hover === null || active ? 1 : 0.55} />
              <text
                className="chart-value"
                x={sx(b.value) + (b.value >= 0 ? 6 : -6)}
                y={y + thickness / 2}
                dy="0.32em"
                textAnchor={b.value >= 0 ? 'start' : 'end'}
              >
                {axisValue(b.value)}
              </text>
            </g>
          )
        })}
      </svg>
      {hover !== null && (
        <Tooltip
          x={sx(spec.bars[hover].value) / WIDTH}
          y={(margin.top + hover * band + band / 2) / height}
          title={spec.bars[hover].label}
          items={[{ label: spec.title, value: spec.bars[hover].value, color: 'var(--series-1)' }]}
        />
      )}
    </div>
  )
}

export function ResultChart({ rows }) {
  const [measure, setMeasure] = useState()
  const selectId = useId()
  const spec = useMemo(() => inferChart(rows, measure), [rows, measure])
  if (!spec) return null

  const picker =
    spec.measures.length > 1 ? (
      <label className="chart-picker" htmlFor={selectId}>
        <span className="visually-hidden">Measure</span>
        <select id={selectId} value={spec.measure} onChange={(e) => setMeasure(e.target.value)}>
          {spec.measures.map((m) => (
            <option key={m} value={m}>
              {humanize(m)}
            </option>
          ))}
        </select>
      </label>
    ) : null

  const title = spec.type === 'line' ? `${spec.title} over time` : `${spec.title} by ${humanize(spec.label)}`
  return (
    <Card icon={TrendIcon} title={title} actions={picker}>
      {spec.type === 'line' ? <LineChart spec={spec} /> : <BarChart spec={spec} />}
    </Card>
  )
}
