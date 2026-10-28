import { vi } from 'vitest'

export function jsonResponse(body, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** Route fetch calls by URL path; unmatched paths return 404. */
export function mockFetch(routes) {
  const fn = vi.fn(async (url, init = {}) => {
    const path = new URL(url, 'http://localhost').pathname
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (!handler) return jsonResponse({ detail: 'Not Found' }, { status: 404 })
    return typeof handler === 'function' ? handler(url, init) : jsonResponse(handler)
  })
  vi.stubGlobal('fetch', fn)
  return fn
}
