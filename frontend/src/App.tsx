import { Route, Routes } from 'react-router'
import ApplicationDetailPage from './pages/ApplicationDetailPage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import LandingPage from './pages/LandingPage.tsx'
import NotFoundPage from './pages/NotFoundPage.tsx'
import { ApiShell, DemoShell } from './pages/Shells.tsx'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/app" element={<ApiShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="applications/:id" element={<ApplicationDetailPage />} />
      </Route>
      <Route path="/demo" element={<DemoShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="applications/:id" element={<ApplicationDetailPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
