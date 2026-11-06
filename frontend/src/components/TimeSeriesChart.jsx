import { useId, useMemo, useState } from 'react'
import {
  barPath,
  formatBucket,
  layoutTimeChart,
  lineSegments,
  segmentPath,
  TIME_CHART,
} from '../utils/timeChart.js'
import { Card } from './Card.jsx'

const SURFACE_GAP = 2

function Legend({ series, kind }) {
  if (series.length < 2) return null
  return (
    <ul className="chart-legend">
      {series.map((s) => (
        <li key={s.key}>
          <span
            className={kind === 'line' ? 'chart-swatch chart-swatch--line' : 'chart-swatch'}
            style={{ background: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  )
}

function DataTable({ points, series, bucketSeconds, format, caption }) {
  return (
    <div className="table-container">
      <table>
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Period starting</th>
            {series.map((s) => (
              <th scope="col" key={s.key} className="num">
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {points.map((p) => (
            <tr key={p.start}>
              <td>{formatBucket(p.start, bucketSeconds)}</td>
              {series.map((s) => (
                <td key={s.key} className="num">
                  {p[s.key] === null || p[s.key] === undefined ? '—' : format(p[s.key])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/**
 * Bucketed time series: stacked columns (`kind="stack"`) or lines.
 * Hover or arrow keys select a bucket; the tooltip lists every series there.
 */
export function TimeSeriesChart({
  title,
  icon,
  points,
  series,
  kind,
  bucketSeconds,
  format,
  axisFormat,
  empty = false,
}) {
  const [active, setActive] = useState(null)
  const [showTable, setShowTable] = useState(false)
  const descId = useId()
  const stacked = kind === 'stack'
  const layout = useMemo(() => layoutTimeChart(points, series, { stacked }), [points, series, stacked])
  const { width, height, left, right, top } = TIME_CHART
  const tickFormat = axisFormat ?? format

  const toggle = (
    <button type="button" className="text-btn" onClick={() => setShowTable((v) => !v)}>
      {showTable ? 'Chart' : 'Table'}
    </button>
  )

  const onKeyDown = (event) => {
    const last = points.length - 1
    const moves = {
      ArrowRight: Math.min(last, (active ?? -1) + 1),
      ArrowLeft: Math.max(0, (active ?? last + 1) - 1),
      Home: 0,
      End: last,
    }
    if (event.key in moves) {
      event.preventDefault()
      setActive(moves[event.key])
    } else if (event.key === 'Escape') {
      setActive(null)
    }
  }

  const onPointerMove = (event) => {
    const box = event.currentTarget.getBoundingClientRect()
    const x = ((event.clientX - box.left) / box.width) * width - left
    const index = Math.floor(x / layout.band)
    setActive(index >= 0 && index < points.length ? index : null)
  }

  const activePoint = active === null ? null : points[active]

  return (
    <Card icon={icon} title={title} actions={toggle}>
      {empty ? (
        <p className="empty-note">No data in this window.</p>
      ) : showTable ? (
        <DataTable points={points} series={series} bucketSeconds={bucketSeconds} format={format} caption={title} />
      ) : (
        <>
          <Legend series={series} kind={kind} />
          <div className="chart-frame">
            <svg
              className="chart-svg"
              viewBox={`0 0 ${width} ${height}`}
              role="img"
              aria-label={`${title}. Use the arrow keys to read each period; the table view lists every value.`}
              aria-describedby={descId}
              tabIndex={0}
              onKeyDown={onKeyDown}
              onPointerMove={onPointerMove}
              onPointerLeave={() => setActive(null)}
              onBlur={() => setActive(null)}
            >
              {layout.ticks.map((t) => (
                <g key={t}>
                  <line
                    className="chart-grid"
                    x1={left}
                    x2={width - right}
                    y1={layout.y(t)}
                    y2={layout.y(t)}
                  />
                  <text className="chart-axis" x={left - 8} y={layout.y(t)} dy="0.32em" textAnchor="end">
                    {tickFormat(t)}
                  </text>
                </g>
              ))}
              {layout.xLabels.map((i) => (
                <text
                  key={points[i].start}
                  className="chart-axis"
                  x={layout.xCenter(i)}
                  y={height - 6}
                  textAnchor="middle"
                >
                  {formatBucket(points[i].start, bucketSeconds)}
                </text>
              ))}

              {stacked &&
                points.map((p, i) => {
                  let base = 0
                  const visible = series.filter((s) => p[s.key] > 0)
                  return (
                    <g key={p.start} opacity={active === null || active === i ? 1 : 0.45}>
                      {visible.map((s, n) => {
                        const value = p[s.key]
                        const yTop = layout.y(base + value)
                        const yBottom = layout.y(base)
                        base += value
                        const gap = n > 0 ? SURFACE_GAP : 0
                        const h = Math.max(0, yBottom - yTop - gap)
                        const x = layout.xCenter(i) - layout.barWidth / 2
                        const isTop = n === visible.length - 1
                        return isTop ? (
                          <path key={s.key} d={barPath(x, yTop, layout.barWidth, h)} fill={s.color} />
                        ) : (
                          <rect key={s.key} x={x} y={yTop} width={layout.barWidth} height={h} fill={s.color} />
                        )
                      })}
                    </g>
                  )
                })}

              {!stacked &&
                series.map((s) =>
                  lineSegments(points, s.key, layout).map((segment) =>
                    segment.length > 1 ? (
                      <path
                        key={`${s.key}-${segment[0][0]}`}
                        className="chart-line"
                        d={segmentPath(segment)}
                        stroke={s.color}
                      />
                    ) : (
                      <circle
                        key={`${s.key}-${segment[0][0]}`}
                        className="chart-dot"
                        cx={segment[0][0]}
                        cy={segment[0][1]}
                        r={4}
                        fill={s.color}
                      />
                    ),
                  ),
                )}

              {activePoint && (
                <>
                  {!stacked && (
                    <line
                      className="chart-crosshair"
                      x1={layout.xCenter(active)}
                      x2={layout.xCenter(active)}
                      y1={top}
                      y2={layout.baseline}
                    />
                  )}
                  {!stacked &&
                    series.map((s) =>
                      activePoint[s.key] === null || activePoint[s.key] === undefined ? null : (
                        <circle
                          key={s.key}
                          className="chart-dot"
                          cx={layout.xCenter(active)}
                          cy={layout.y(activePoint[s.key])}
                          r={4}
                          fill={s.color}
                        />
                      ),
                    )}
                </>
              )}
            </svg>
            <p id={descId} className="visually-hidden">
              {series.map((s) => s.label).join(', ')} per period.
            </p>
            {activePoint && (
              <div
                className="chart-tooltip"
                role="status"
                style={{
                  left: `${(layout.xCenter(active) / width) * 100}%`,
                  top: '10%',
                  transform: `translate(${active > points.length * 0.6 ? 'calc(-100% - 12px)' : '12px'}, 0)`,
                }}
              >
                <div className="chart-tooltip-title">{formatBucket(activePoint.start, bucketSeconds)}</div>
                {series.map((s) => (
                  <div className="chart-tooltip-row" key={s.key}>
                    <span className="chart-swatch chart-swatch--line" style={{ background: s.color }} />
                    <span className="chart-tooltip-label">{s.label}</span>
                    <span className="chart-tooltip-value">
                      {activePoint[s.key] === null || activePoint[s.key] === undefined
                        ? '—'
                        : format(activePoint[s.key])}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Card>
  )
}
