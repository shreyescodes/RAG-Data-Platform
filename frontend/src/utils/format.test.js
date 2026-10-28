import { describe, expect, it } from 'vitest'
import { toCsv } from './csv.js'
import { formatCell, formatCompact, formatDuration, formatRelativeTime } from './format.js'

describe('formatCell', () => {
  it.each([
    [null, '—'],
    [undefined, '—'],
    [12000000, '12,000,000'],
    [1500000.567, '1,500,001'],
    [0.01234567, '0.0123'],
    [true, 'true'],
    ['text', 'text'],
    [{ a: 1 }, '{"a":1}'],
  ])('formats %j as %s', (value, expected) => {
    expect(formatCell(value)).toBe(expected)
  })
})

describe('formatDuration', () => {
  it('uses ms below one second and s above', () => {
    expect(formatDuration(245.6)).toBe('246 ms')
    expect(formatDuration(1834.2)).toBe('1.83 s')
    expect(formatDuration(undefined)).toBe('—')
  })
})

describe('formatCompact', () => {
  it('abbreviates large values', () => {
    expect(formatCompact(3.8e12)).toBe('3.8T')
    expect(formatCompact(null)).toBe('—')
  })
})

describe('formatRelativeTime', () => {
  const now = Date.parse('2026-10-28T12:00:00Z')
  it('treats naive timestamps as UTC', () => {
    expect(formatRelativeTime('2026-10-28T11:59:30', now)).toBe('just now')
    expect(formatRelativeTime('2026-10-28T11:15:00', now)).toBe('45m ago')
    expect(formatRelativeTime('2026-10-28T09:00:00Z', now)).toBe('3h ago')
    expect(formatRelativeTime('2026-10-25T12:00:00', now)).toBe('3d ago')
    expect(formatRelativeTime('garbage', now)).toBe('')
  })
})

describe('toCsv', () => {
  it('quotes values containing delimiters', () => {
    const csv = toCsv([
      { name: 'Acme, Inc.', note: 'say "hi"', value: 1 },
      { name: 'Plain', note: null, value: 2 },
    ])
    expect(csv).toBe('name,note,value\r\n"Acme, Inc.","say ""hi""",1\r\nPlain,,2')
  })

  it('returns an empty string for no rows', () => {
    expect(toCsv([])).toBe('')
  })
})
