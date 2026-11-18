import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Sidebar } from './Sidebar.jsx'

const history = [
  { id: 3, query: 'Top holdings of Berkshire', success: true },
  { id: 2, query: 'Drop all tables', success: false },
  { id: 1, query: 'top holdings of berkshire', success: false },
]

function setup(props = {}) {
  const handlers = { onNewChat: vi.fn(), onSelect: vi.fn(), onNavigate: vi.fn(), onClose: vi.fn() }
  render(<Sidebar history={history} {...handlers} {...props} />)
  return { handlers, user: userEvent.setup() }
}

describe('Sidebar', () => {
  it('lists each question once, using its latest run', () => {
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

  it('opens a recent question', async () => {
    const { handlers, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Top holdings of Berkshire' }))
    expect(handlers.onSelect).toHaveBeenCalledWith('Top holdings of Berkshire')
  })

  it('marks the question on screen', () => {
    setup({ activeQuery: 'Top holdings of Berkshire' })
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
