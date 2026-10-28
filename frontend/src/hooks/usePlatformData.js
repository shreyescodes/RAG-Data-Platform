import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'

const HISTORY_SIZE = 8

/** Dataset stats and recent query history. Failures are non-fatal. */
export function usePlatformData() {
  const [stats, setStats] = useState(null)
  const [history, setHistory] = useState([])

  const refresh = useCallback(async (signal) => {
    const [statsResult, historyResult] = await Promise.allSettled([
      api.stats({ signal }),
      api.history({ limit: HISTORY_SIZE }, { signal }),
    ])
    if (signal?.aborted) return
    if (statsResult.status === 'fulfilled') setStats(statsResult.value)
    if (historyResult.status === 'fulfilled') setHistory(historyResult.value.history)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  return { stats, history, refresh }
}
