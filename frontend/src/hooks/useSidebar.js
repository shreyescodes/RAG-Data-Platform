import { useCallback, useEffect, useState } from 'react'

const NARROW_VIEWPORT = '(max-width: 768px)'
const COLLAPSED_KEY = 'sidebar-collapsed'

export function isNarrowViewport() {
  return window.matchMedia?.(NARROW_VIEWPORT).matches ?? false
}

function readCollapsed() {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === 'true'
  } catch {
    return false
  }
}

function saveCollapsed(collapsed) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, String(collapsed))
  } catch {
    // Without storage the sidebar simply opens again on the next visit.
  }
}

const startsOpen = () => !isNarrowViewport() && !readCollapsed()

/** A docked sidebar on wide screens and a drawer on narrow ones. */
export function useSidebar() {
  const [open, setOpen] = useState(startsOpen)

  const closeDrawer = useCallback(() => {
    if (!isNarrowViewport()) return
    setOpen(false)
    document.getElementById('sidebar-toggle')?.focus()
  }, [])

  const toggle = useCallback(() => {
    const next = !open
    setOpen(next)
    if (!isNarrowViewport()) saveCollapsed(!next)
    else if (next) requestAnimationFrame(() => document.getElementById('new-chat')?.focus())
    else document.getElementById('sidebar-toggle')?.focus()
  }, [open])

  useEffect(() => {
    const viewport = window.matchMedia?.(NARROW_VIEWPORT)
    if (!viewport) return undefined
    const onChange = () => setOpen(startsOpen())
    viewport.addEventListener('change', onChange)
    return () => viewport.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (!open) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') closeDrawer()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, closeDrawer])

  return { open, toggle, closeDrawer }
}
