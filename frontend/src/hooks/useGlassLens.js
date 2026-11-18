import { useEffect, useRef } from 'react'
import { installGlassLens } from '../utils/liquidGlass.js'

/** A ref that turns the element it is attached to into refracting glass. */
export function useGlassLens() {
  const ref = useRef(null)
  useEffect(() => installGlassLens(ref.current), [])
  return ref
}
