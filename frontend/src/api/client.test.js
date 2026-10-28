import { afterEach, describe, expect, it, vi } from 'vitest'
import { jsonResponse, mockFetch } from '../test/mockFetch.js'
import { ApiError, api } from './client.js'

afterEach(() => vi.unstubAllGlobals())

describe('api client', () => {
  it('posts the query as JSON to the relative API path', async () => {
    const fetch = mockFetch({ 'POST /api/query': { success: true } })

    await expect(api.query('top companies')).resolves.toEqual({ success: true })

    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('/api/query')
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(init.body)).toEqual({ query: 'top companies' })
  })

  it('never sends an API key from the browser', async () => {
    const fetch = mockFetch({ 'GET /api/stats': {} })
    await api.stats()
    expect(JSON.stringify(fetch.mock.calls[0][1])).not.toMatch(/api-key/i)
  })

  it.each([
    [401, {}, /missing or invalid API key/],
    [429, {}, /Rate limit/],
    [422, { detail: [{ msg: 'String should have at least 3 characters' }] }, /at least 3/],
    [500, { detail: 'An internal error occurred.' }, /internal error/],
  ])('maps HTTP %i to a readable error', async (status, body, message) => {
    mockFetch({
      'GET /api/stats': () => jsonResponse(body, { status, headers: { 'X-Request-ID': 'req-1' } }),
    })
    const error = await api.stats().catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(status)
    expect(error.requestId).toBe('req-1')
    expect(error.message).toMatch(message)
  })

  it('reports network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.stats()).rejects.toThrow(/Could not reach the API/)
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
