import { MAX_TABLE_ROWS } from '../constants.js'
import { downloadCsv } from '../utils/csv.js'
import { formatCell } from '../utils/format.js'
import { Card } from './Card.jsx'
import { DatabaseIcon } from './Icons.jsx'

export function ResultsTable({ rows }) {
  if (!rows?.length) return null
  const columns = Object.keys(rows[0])
  const visible = rows.slice(0, MAX_TABLE_ROWS)
  const title =
    rows.length > visible.length
      ? `Data (${visible.length} of ${rows.length} rows)`
      : `Data (${rows.length} ${rows.length === 1 ? 'row' : 'rows'})`

  return (
    <Card
      icon={DatabaseIcon}
      title={title}
      flush
      actions={
        <button type="button" className="text-btn" onClick={() => downloadCsv(rows)}>
          Download CSV
        </button>
      }
    >
      <div className="table-container">
        <table>
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col} scope="col" className={typeof rows[0][col] === 'number' ? 'num' : undefined}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, idx) => (
              <tr key={idx}>
                {columns.map((col) => (
                  <td key={col} className={typeof row[col] === 'number' ? 'num' : undefined}>
                    {formatCell(row[col])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
