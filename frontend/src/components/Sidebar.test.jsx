import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Sidebar } from './Sidebar.jsx'

const history = [
  { id: 4, conversation_id: 'chat-1', query: 'And its revenue?', success: true },
  { id: 3, conversation_id: 'chat-2', query: 'Drop all tables', success: false },
  { id: 2, conversation_id: 'chat-1', query: 'Top holdings of Berkshire', success: true },
  { id: 1, conversation_id: null, query: 'Asked outside a chat', success: true },
]

function setup(props = {}) {
  const handlers = { onNewChat: vi.fn(), onSelect: vi.fn(), onNavigate: vi.fn(), onClose: vi.fn() }
  render(<Sidebar history={history} {...handlers} {...props} />)
  return { handlers, user: userEvent.setup() }
}

describe('Sidebar', () => {
  it('lists each chat once, titled by its first question', () => {
    setup()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Top holdings of Berkshire' })).toBeInTheDocument()
    expect(screen.getAllByLabelText('failed')).toHaveLength(1)
  })

  it('starts a new chat', async () => {
    const { handlers, user } = setup()
    await user.click(screen.getByRole('button', { name: 'New chat' }))
    expect(handlers.onNewChat).toHaveBeenCalledOnce()
  })

  it('opens a saved chat', async () => {
    const { handlers, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Top holdings of Berkshire' }))
    expect(handlers.onSelect).toHaveBeenCalledWith('chat-1')
  })

  it('marks the chat on screen', () => {
    setup({ activeChat: 'chat-1' })
    expect(screen.getByRole('button', { name: 'Top holdings of Berkshire' })).toHaveAttribute(
      'aria-current',
      'true',
    )
  })

  it('explains the empty list', () => {
    setup({ history: [] })
    expect(screen.getByText('Your questions will appear here.')).toBeInTheDocument()
  })
})
