import { vi } from 'vitest'

export function jsonResponse(body, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

/** The server-sent events of one answered question. */
export function eventStream(result, stages = []) {
  const events = [
    ...stages.map((stage) => `event: stage\ndata: ${JSON.stringify(stage)}\n\n`),
    `event: result\ndata: ${JSON.stringify(result)}\n\n`,
  ]
  return new Response(events.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
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
