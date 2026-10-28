import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

/** Runs one query at a time; starting a new one or cancelling aborts the last. */
export function useQueryRunner({ onSettled } = {}) {
  const [state, setState] = useState({ loading: false, result: null, error: null })
  const controllerRef = useRef(null)

  const cancel = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setState((s) => ({ ...s, loading: false }))
  }, [])

  const run = useCallback(
    async (query) => {
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller
      setState({ loading: true, result: null, error: null })

      try {
        const result = await api.query(query, { signal: controller.signal })
        setState({ loading: false, result, error: null })
      } catch (error) {
        if (error?.name === 'AbortError') return
        setState({ loading: false, result: null, error })
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null
          onSettled?.()
        }
      }
    },
    [onSettled],
  )

  const reset = useCallback(() => setState({ loading: false, result: null, error: null }), [])

  useEffect(() => () => controllerRef.current?.abort(), [])

  return { ...state, run, cancel, reset }
}
