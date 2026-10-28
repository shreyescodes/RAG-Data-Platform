function escape(value) {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** Serialise rows (array of flat objects) to RFC 4180 CSV. */
export function toCsv(rows) {
  if (!rows?.length) return ''
  const columns = Object.keys(rows[0])
  const lines = [columns.map(escape).join(',')]
  for (const row of rows) lines.push(columns.map((c) => escape(row[c])).join(','))
  return lines.join('\r\n')
}

export function downloadCsv(rows, filename = 'query-results.csv') {
  const blob = new Blob([toCsv(rows)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
