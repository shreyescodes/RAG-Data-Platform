import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'

const HISTORY_SIZE = 40

/** Recent query history. Failures are non-fatal. */
export function usePlatformData() {
  const [history, setHistory] = useState([])

  const refresh = useCallback(async (signal) => {
    try {
      const result = await api.history({ limit: HISTORY_SIZE }, { signal })
      if (!signal?.aborted) setHistory(result.history)
    } catch {
      // The sidebar keeps the last list it loaded.
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  return { history, refresh }
}
