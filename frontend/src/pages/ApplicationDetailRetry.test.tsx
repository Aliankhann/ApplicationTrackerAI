import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { expect, test } from 'vitest'
import { ApiError, type DataSource } from '../data/dataSource'
import { createDemoDataSource } from '../data/demoDataSource'
import { renderWithSource } from '../test/render'
import userEvent from '../test/user'
import ApplicationDetailPage from './ApplicationDetailPage'

const ID = '00000000-0000-4000-8000-000000000009'

test('failed edit keeps form and values; retry succeeds', async () => {
  const demo = createDemoDataSource()
  let fail = true
  const source: DataSource = {
    ...demo,
    updateApplication: async (id, patch) => {
      if (fail) throw new ApiError(500, 'boom')
      return demo.updateApplication(id, patch)
    },
  }
  const user = userEvent.setup()
  renderWithSource(
    source,
    <Routes>
      <Route path="/demo/applications/:id" element={<ApplicationDetailPage />} />
    </Routes>,
    `/demo/applications/${ID}`,
  )
  await user.click(await screen.findByRole('button', { name: /Edit company/ }))
  await user.clear(screen.getByLabelText('Company'))
  await user.type(screen.getByLabelText('Company'), 'NewCo')
  await user.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(screen.getByLabelText('Company')).toHaveValue('NewCo')
  fail = false
  await user.click(screen.getByRole('button', { name: 'Save' }))
  await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('NewCo'))
  expect(screen.queryByRole('alert')).toBeNull()
})
