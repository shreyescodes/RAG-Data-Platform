import { describe, expect, it } from 'vitest'
import { canRefract, installGlassLens, lensOffset } from './liquidGlass.js'

function fakeWindow({ chromium = false, reducedTransparency = false } = {}) {
  return {
    document,
    navigator: chromium ? { userAgentData: {} } : {},
    matchMedia: () => ({ matches: reducedTransparency }),
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
  }
}

describe('canRefract', () => {
  it('is on only in browsers that can render it', () => {
    expect(canRefract(fakeWindow())).toBe(false)
    expect(canRefract(fakeWindow({ chromium: true }))).toBe(true)
  })

  it('respects a preference for reduced transparency', () => {
    expect(canRefract(fakeWindow({ chromium: true, reducedTransparency: true }))).toBe(false)
  })
})

describe('lensOffset', () => {
  const offset = (x, y) => lensOffset(x, y, 400, 60, 30, 16)

  it('leaves the middle of the glass undistorted', () => {
    expect(offset(200, 30)).toEqual([0, 0])
  })

  it('pulls the rim towards the centre', () => {
    const [, top] = offset(200, 1)
    const [, bottom] = offset(200, 59)
    expect(top).toBeGreaterThan(0.8)
    expect(bottom).toBeLessThan(-0.8)
  })

  it('bends most at the edge and fades out across the bezel', () => {
    const strength = (y) => offset(200, y)[1]
    expect(strength(1)).toBeGreaterThan(strength(6))
    expect(strength(6)).toBeGreaterThan(strength(12))
  })

  it('pulls rounded ends inward along the curve', () => {
    const [x, y] = offset(12, 12)
    expect(x).toBeGreaterThan(0)
    expect(y).toBeGreaterThan(0)
  })

  it('ignores points outside the shape', () => {
    expect(offset(1, 1)).toEqual([0, 0])
  })
})

describe('installGlassLens', () => {
  it('adds nothing where refraction cannot render', () => {
    const element = document.createElement('div')
    const remove = installGlassLens(element, fakeWindow())

    expect(document.querySelector('filter')).toBeNull()
    expect(element.style.getPropertyValue('--glass-lens')).toBe('')
    remove()
  })

  it('removes its filter on cleanup', () => {
    const remove = installGlassLens(document.createElement('div'), fakeWindow({ chromium: true }))
    expect(document.querySelector('filter')).not.toBeNull()

    remove()
    expect(document.querySelector('filter')).toBeNull()
  })
})
