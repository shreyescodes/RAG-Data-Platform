// Thin wrapper around fetch for the backend API.
//
// The API key is never shipped to the browser. In development the Vite dev
// server proxies /api and adds the X-API-Key header; in Docker, nginx does.
// Set VITE_API_URL only when the frontend must call a different origin.

const BASE_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '')
const DEFAULT_TIMEOUT_MS = 90_000

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
  if (status === 429) return 'Rate limit reached. Please wait a moment and try again.'
  if (status === 422 && Array.isArray(body?.detail)) {
    return body.detail.map((d) => d.msg).join('; ')
  }
  if (typeof body?.detail === 'string') return body.detail
  if (typeof body?.error === 'string') return body.error
  return `Request failed with status ${status}.`
}

async function request(path, { method = 'GET', body, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(new DOMException('Timeout', 'TimeoutError')), timeoutMs)
  const onAbort = () => controller.abort(signal.reason)
  signal?.addEventListener('abort', onAbort, { once: true })

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    })
    const requestId = response.headers.get('X-Request-ID') ?? undefined
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      throw new ApiError(describe(response.status, payload), { status: response.status, requestId })
    }
    return payload
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
  query: (query, options) => request('/query', { method: 'POST', body: { query }, ...options }),
  stats: (options) => request('/stats', options),
  history: ({ limit = 10, offset = 0 } = {}, options) =>
    request(`/history?limit=${limit}&offset=${offset}`, options),
}
