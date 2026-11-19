import { afterEach, describe, expect, it, vi } from 'vitest'
import { eventStream, jsonResponse, mockFetch } from '../test/mockFetch.js'
import { ApiError, api } from './client.js'

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('posts the query as JSON to the relative API path', async () => {
    const fetch = mockFetch({ 'POST /api/query/stream': () => eventStream({ success: true }) })

    await expect(api.query('top companies', { conversationId: 'chat-1' })).resolves.toEqual({
      success: true,
    })

    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/query/stream')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.headers['X-Visitor-Id']).toMatch(/^[a-f0-9]{32}$/)
    expect(JSON.parse(init.body)).toEqual({ query: 'top companies', conversation_id: 'chat-1' })
  })

  it('reports each stage while the answer is prepared', async () => {
    mockFetch({
      'POST /api/query/stream': () =>
        eventStream({ success: true }, [
          { stage: 'retrieval', status: 'started' },
          { stage: 'retrieval', status: 'completed' },
        ]),
    })
    const seen = []

    await api.query('top companies', { onStage: (...args) => seen.push(args) })

    expect(seen).toEqual([
      ['retrieval', 'started'],
      ['retrieval', 'completed'],
    ])
  })

  it('reports an answer that never arrives', async () => {
    mockFetch({ 'POST /api/query/stream': () => new Response(': keep-alive\n\n') })
    await expect(api.query('top companies')).rejects.toThrow(/stopped before it finished/)
  })

  it('shows the daily limit message from the server', async () => {
    mockFetch({
      'GET /api/history': () => jsonResponse({ detail: 'Come back tomorrow.' }, { status: 429 }),
    })
    await expect(api.history()).rejects.toThrow('Come back tomorrow.')
  })

  it('never sends an API key from the browser', async () => {
    const fetch = mockFetch({ 'GET /api/history': {} })
    await api.history()
    expect(JSON.stringify(fetch.mock.calls[0][1])).not.toMatch(/api-key/i)
  })

  it.each([
    [401, {}, /missing or invalid API key/],
    [429, {}, /Rate limit/],
    [422, { detail: [{ msg: 'String should have at least 3 characters' }] }, /at least 3/],
    [500, { detail: 'An internal error occurred.' }, /internal error/],
  ])('maps HTTP %i to a readable error', async (status, body, message) => {
    mockFetch({
      'GET /api/history': () => jsonResponse(body, { status, headers: { 'X-Request-ID': 'req-1' } }),
    })
    const error = await api.history().catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(status)
    expect(error.requestId).toBe('req-1')
    expect(error.message).toMatch(message)
  })

  it('reports network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.history()).rejects.toThrow(/Could not reach the API/)
  })

  it('propagates caller aborts', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((_url, { signal }) => new Promise((_, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })),
    )
    const controller = new AbortController()
    const pending = api.query('slow', { signal: controller.signal })
    controller.abort()
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('builds history pagination parameters', async () => {
    const fetch = mockFetch({ 'GET /api/history': { history: [] } })
    await api.history({ limit: 5, offset: 10 })
    expect(fetch.mock.calls[0][0]).toBe('/api/history?limit=5&offset=10')
  })
})
