// An anonymous ID kept in this browser, so each visitor only sees their own chats.
const STORAGE_KEY = 'rag-visitor-id'

let sessionId = null

export function randomId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function getVisitorId() {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored) return stored
    const created = randomId()
    window.localStorage.setItem(STORAGE_KEY, created)
    return created
  } catch {
    // Private windows may block storage: the ID then lasts until the page closes.
    sessionId ??= randomId()
    return sessionId
  }
}
