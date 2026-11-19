import { render, screen } from '@testing-library/react'

import { App } from './App.tsx'

describe('App', () => {
  it('renders the product name', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: 'KaraForge' })).toBeInTheDocument()
  })
})
