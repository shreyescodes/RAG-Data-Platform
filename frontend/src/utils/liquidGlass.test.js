import { afterEach, describe, expect, it, vi } from 'vitest'
import { installLiquidGlass } from './liquidGlass.js'

function fakeWindow({ chromium = false, fine = true, reduced = false } = {}) {
  return {
    document,
    navigator: chromium ? { userAgentData: {} } : {},
    matchMedia: (query) => ({ matches: query.includes('reduced-motion') ? reduced : fine }),
    requestAnimationFrame: (callback) => {
      callback()
      return 0
    },
    cancelAnimationFrame: vi.fn(),
  }
}

describe('installLiquidGlass', () => {
  let remove = () => {}

  afterEach(() => {
    remove()
    delete document.documentElement.dataset.refraction
    document.body.innerHTML = ''
  })

  it('enables refraction only in browsers that can render it', () => {
    remove = installLiquidGlass(fakeWindow())
    expect(document.documentElement.dataset.refraction).toBeUndefined()

    remove()
    remove = installLiquidGlass(fakeWindow({ chromium: true }))
    expect(document.documentElement.dataset.refraction).toBe('on')
  })

  it('moves the glint to the pointer position on the surface under it', () => {
    document.body.innerHTML = '<section class="card"><p id="inner">text</p></section>'
    const card = document.querySelector('.card')
    card.getBoundingClientRect = () => ({ left: 10, top: 20 })
    remove = installLiquidGlass(fakeWindow())

    document
      .getElementById('inner')
      .dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 110, clientY: 70 }))

    expect(card.style.getPropertyValue('--glass-x')).toBe('100px')
    expect(card.style.getPropertyValue('--glass-y')).toBe('50px')
  })

  it('does not track the pointer when the user prefers reduced motion', () => {
    document.body.innerHTML = '<section class="card"></section>'
    const card = document.querySelector('.card')
    remove = installLiquidGlass(fakeWindow({ reduced: true }))

    card.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 5, clientY: 5 }))

    expect(card.style.getPropertyValue('--glass-x')).toBe('')
  })
})
