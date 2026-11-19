// Thin wrapper around fetch for the backend API.
//
// The API key is never shipped to the browser. In development the Vite dev
// server proxies /api and adds the X-API-Key header; in Docker, nginx does.
// Set VITE_API_URL only when the frontend must call a different origin.

import { getVisitorId } from '../utils/visitor.js'

const BASE_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
const DEFAULT_TIMEOUT_MS = 90_000
// One answer can take minutes on a CPU-only local model; the backend already
// bounds every LLM call (LLM_TIMEOUT_SECONDS), so the browser waits longer.
export const QUERY_TIMEOUT_MS = Number(import.meta.env.VITE_QUERY_TIMEOUT_MS) || 300_000

export class ApiError extends Error {
  constructor(message, { status, requestId } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.requestId = requestId
  }
}

function describe(status, body) {
  if (status === 401) return 'The API rejected the request: missing or invalid API key.'
  if (status === 429) {
    return typeof body?.detail === 'string'
      ? body.detail
      : 'Rate limit reached. Please wait a moment and try again.'
  }
  if (status === 422 && Array.isArray(body?.detail)) {
    return body.detail.map((d) => d.msg).join('; ')
  }
  if (typeof body?.detail === 'string') return body.detail
  if (typeof body?.error === 'string') return body.error
  return `Request failed with status ${status}.`
}

/** Reads `event:` / `data:` blocks from a server-sent event stream. */
async function readEvents(response, onEvent) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    let end = buffer.indexOf('\n\n')
    while (end >= 0) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const name = block.match(/^event: (.*)$/m)?.[1]
      const data = block.match(/^data: (.*)$/m)?.[1]
      if (name && data) onEvent(name, JSON.parse(data))
      end = buffer.indexOf('\n\n')
    }
  }
}

async function request(
  path,
  { method = 'GET', body, signal, timeoutMs = DEFAULT_TIMEOUT_MS, read } = {},
) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new DOMException('Timeout', 'TimeoutError')), timeoutMs)
  const onAbort = () => controller.abort(signal.reason)
  signal?.addEventListener('abort', onAbort, { once: true })

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: {
        'X-Visitor-Id': getVisitorId(),
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    const requestId = response.headers.get('X-Request-ID') ?? undefined
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new ApiError(describe(response.status, payload), { status: response.status, requestId })
    }
    if (read) return await read(response, requestId)
    return await response.json().catch(() => null)
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err?.name === 'TimeoutError' || controller.signal.reason?.name === 'TimeoutError') {
      throw new ApiError('The request timed out.')
    }
    if (err?.name === 'AbortError') throw err
    throw new ApiError('Could not reach the API. Is the backend running?')
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', onAbort)
  }
}

export const api = {
  /** Asks a question; `onStage(stage, status)` reports progress until the answer arrives. */
  query: (query, { conversationId, onStage, ...options } = {}) =>
    request('/query/stream', {
      method: 'POST',
      body: { query, conversation_id: conversationId },
      timeoutMs: QUERY_TIMEOUT_MS,
      read: async (response, requestId) => {
        let answer = null
        await readEvents(response, (name, data) => {
          if (name === 'stage') onStage?.(data.stage, data.status)
          if (name === 'result') answer = data
          if (name === 'error') throw new ApiError(data.detail, { requestId })
        })
        if (!answer) throw new ApiError('The answer stopped before it finished.', { requestId })
        return answer
      },
      ...options,
    }),
  conversation: (id, options) => request(`/conversations/${encodeURIComponent(id)}`, options),
  history: ({ limit = 10, offset = 0 } = {}, options) =>
    request(`/history?limit=${limit}&offset=${offset}`, options),
  metricsSummary: (window, options) => request(`/metrics/summary?window=${window}`, options),
  metricsTimeseries: (window, options) =>
    request(`/metrics/timeseries?window=${window}`, options),
  metricsRecent: (limit = 25, options) => request(`/metrics/recent?limit=${limit}`, options),
}
