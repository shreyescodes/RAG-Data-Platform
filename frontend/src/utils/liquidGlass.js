// Liquid glass bends what is behind it only near the rim, like the curved edge of a lens.
const BEZEL_PX = 16
const REFRACTION_PX = 30
const SVG_NS = 'http://www.w3.org/2000/svg'

let lensCount = 0

/** backdrop-filter: url() only renders in Chromium; other browsers keep the plain blur. */
export function canRefract(win = window) {
  const reduced = win.matchMedia?.('(prefers-reduced-transparency: reduce)').matches
  return Boolean(win.navigator.userAgentData) && !reduced
}

/**
 * How far the point (x, y) of a rounded rectangle looks towards the centre,
 * from -1 to 1 on each axis. Zero everywhere except inside the bezel.
 */
export function lensOffset(x, y, width, height, radius, bezel = BEZEL_PX) {
  const r = Math.min(radius, width / 2, height / 2)
  const fromCentreX = x - width / 2
  const fromCentreY = y - height / 2
  const qx = Math.abs(fromCentreX) - (width / 2 - r)
  const qy = Math.abs(fromCentreY) - (height / 2 - r)
  const inCorner = qx > 0 && qy > 0
  const depth = r - (inCorner ? Math.hypot(qx, qy) : Math.max(qx, qy))
  if (depth < 0 || depth >= bezel) return [0, 0]

  const strength = (1 - depth / bezel) ** 2
  const length = inCorner ? Math.hypot(qx, qy) : 1
  const normalX = inCorner ? qx / length : Number(qx > qy)
  const normalY = inCorner ? qy / length : Number(qx <= qy)
  return [
    -Math.sign(fromCentreX) * normalX * strength,
    -Math.sign(fromCentreY) * normalY * strength,
  ]
}

function lensMapUrl(doc, width, height, radius) {
  const canvas = doc.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  const image = context.createImageData(width, height)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const [dx, dy] = lensOffset(x + 0.5, y + 0.5, width, height, radius)
      const pixel = (y * width + x) * 4
      image.data[pixel] = 128 + dx * 127
      image.data[pixel + 1] = 128 + dy * 127
      image.data[pixel + 2] = 128
      image.data[pixel + 3] = 255
    }
  }
  context.putImageData(image, 0, 0)
  return canvas.toDataURL()
}

/** Refracts the page behind `element`, resizing with it. Returns a cleanup function. */
export function installGlassLens(element, win = window) {
  if (!element || !win.ResizeObserver || !canRefract(win)) return () => {}

  lensCount += 1
  const id = `glass-lens-${lensCount}`
  const doc = win.document
  const svg = doc.createElementNS(SVG_NS, 'svg')
  svg.setAttribute('aria-hidden', 'true')
  svg.setAttribute('style', 'position:absolute;width:0;height:0')
  svg.innerHTML = `
    <filter id="${id}" filterUnits="userSpaceOnUse" x="0" y="0" color-interpolation-filters="sRGB">
      <feImage result="map" x="0" y="0" preserveAspectRatio="none" />
      <feDisplacementMap in="SourceGraphic" in2="map" scale="${REFRACTION_PX}"
        xChannelSelector="R" yChannelSelector="G" />
    </filter>`
  doc.body.append(svg)
  const filter = svg.querySelector('filter')
  const map = svg.querySelector('feImage')

  const paint = () => {
    const width = element.offsetWidth
    const height = element.offsetHeight
    if (!width || !height) return
    const radius = Number.parseFloat(win.getComputedStyle(element).borderTopLeftRadius) || 0
    for (const node of [filter, map]) {
      node.setAttribute('width', width)
      node.setAttribute('height', height)
    }
    map.setAttribute('href', lensMapUrl(doc, width, height, radius))
    element.style.setProperty('--glass-lens', `url(#${id})`)
  }

  const observer = new win.ResizeObserver(paint)
  observer.observe(element)
  return () => {
    observer.disconnect()
    element.style.removeProperty('--glass-lens')
    svg.remove()
  }
}
