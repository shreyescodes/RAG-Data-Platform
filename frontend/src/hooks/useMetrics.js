import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'

const RECENT_LIMIT = 25

/**
 * Dashboard data for one look-back window. Previous data stays on screen
 * while a refetch is in flight, so a refresh never blanks the page.
 */
export function useMetrics(range) {
  const [state, setState] = useState({
    summary: null,
    timeseries: null,
    recent: [],
    loading: true,
    error: null,
    updatedAt: null,
  })

  const load = useCallback(
    async (signal) => {
      setState((s) => ({ ...s, loading: true, error: null }))
      try {
        const [summary, timeseries, recent] = await Promise.all([
          api.metricsSummary(range, { signal }),
          api.metricsTimeseries(range, { signal }),
          api.metricsRecent(RECENT_LIMIT, { signal }),
        ])
        setState({
          summary,
          timeseries,
          recent: recent.requests,
          loading: false,
          error: null,
          updatedAt: new Date(),
        })
      } catch (error) {
        if (error?.name === 'AbortError') return
        setState((s) => ({ ...s, loading: false, error }))
      }
    },
    [range],
  )

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  return { ...state, refresh: () => load() }
}
