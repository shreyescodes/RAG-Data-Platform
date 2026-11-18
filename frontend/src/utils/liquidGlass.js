// Finds the glass surface under the pointer so its rim can catch the light.
const GLASS_SELECTOR = '.card, .stat-tile, .header, .input-wrapper'

/**
 * Turns on refraction where the browser can render it, and moves the rim glint
 * with the pointer. Returns a function that removes the listener.
 */
export function installLiquidGlass(win = window) {
  // backdrop-filter: url() only renders in Chromium; others keep the plain blur.
  if (win.navigator.userAgentData) win.document.documentElement.dataset.refraction = 'on'

  const canTrack = win.matchMedia?.('(hover: hover) and (pointer: fine)').matches
  const reducedMotion = win.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!canTrack || reducedMotion) return () => {}

  let frame = 0
  let latest = null

  const paint = () => {
    frame = 0
    const surface = latest.target.closest?.(GLASS_SELECTOR)
    if (!surface) return
    const box = surface.getBoundingClientRect()
    surface.style.setProperty('--glass-x', `${latest.clientX - box.left}px`)
    surface.style.setProperty('--glass-y', `${latest.clientY - box.top}px`)
  }

  const onMove = (event) => {
    latest = event
    if (!frame) frame = win.requestAnimationFrame(paint)
  }

  win.document.addEventListener('pointermove', onMove, { passive: true })
  return () => {
    win.document.removeEventListener('pointermove', onMove)
    if (frame) win.cancelAnimationFrame(frame)
  }
}
