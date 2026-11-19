import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'
import { randomId } from '../utils/visitor.js'

const savedTurn = (result, index) => ({
  key: `saved-${index}`,
  question: result.query,
  status: 'done',
  stages: {},
  result,
  error: null,
})

/** One chat: its questions, their progress and answers. Asks one question at a time. */
export function useConversation({ onSettled } = {}) {
  const [conversationId, setConversationId] = useState(randomId)
  const [turns, setTurns] = useState([])
  const [opening, setOpening] = useState(false)
  const [openError, setOpenError] = useState(null)
  const controllerRef = useRef(null)

  const abort = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  const updateTurn = useCallback((key, change) => {
    setTurns((all) => all.map((turn) => (turn.key === key ? { ...turn, ...change(turn) } : turn)))
  }, [])

  const ask = useCallback(
    async (question) => {
      abort()
      const controller = new AbortController()
      controllerRef.current = controller
      const key = randomId()
      setOpenError(null)
      setTurns((all) => [
        ...all,
        { key, question, status: 'running', stages: {}, result: null, error: null },
      ])
      try {
        const result = await api.query(question, {
          conversationId,
          signal: controller.signal,
          onStage: (stage, status) =>
            updateTurn(key, (turn) => ({ stages: { ...turn.stages, [stage]: status } })),
        })
        updateTurn(key, () => ({ status: 'done', result }))
      } catch (error) {
        if (error?.name === 'AbortError') return
        updateTurn(key, () => ({ status: 'done', error }))
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null
          onSettled?.()
        }
      }
    },
    [abort, conversationId, onSettled, updateTurn],
  )

  /** Stops the running question and removes it from the chat. */
  const stop = useCallback(() => {
    abort()
    setTurns((all) => all.slice(0, -1))
  }, [abort])

  const reset = useCallback(() => {
    abort()
    setConversationId(randomId())
    setTurns([])
    setOpenError(null)
    setOpening(false)
  }, [abort])

  /** Shows a saved chat without asking the model anything again. */
  const open = useCallback(
    async (id) => {
      abort()
      const controller = new AbortController()
      controllerRef.current = controller
      setConversationId(id)
      setTurns([])
      setOpenError(null)
      setOpening(true)
      try {
        const saved = await api.conversation(id, { signal: controller.signal })
        setTurns(saved.turns.map(savedTurn))
      } catch (error) {
        if (error?.name !== 'AbortError') setOpenError(error)
      } finally {
        if (controllerRef.current === controller) {
          controllerRef.current = null
          setOpening(false)
        }
      }
    },
    [abort],
  )

  useEffect(() => abort, [abort])

  const loading = turns.some((turn) => turn.status === 'running')
  return { conversationId, turns, loading, opening, openError, ask, stop, reset, open }
}
