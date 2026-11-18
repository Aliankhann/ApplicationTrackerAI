import { Route, Routes } from 'react-router'
import ApplicationDetailPage from './pages/ApplicationDetailPage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import FollowUpSettingsPage from './pages/FollowUpSettingsPage.tsx'
import FollowUpsPage from './pages/FollowUpsPage.tsx'
import LandingPage from './pages/LandingPage.tsx'
import GoodbyePage from './pages/GoodbyePage.tsx'
import NotFoundPage from './pages/NotFoundPage.tsx'
import SettingsPage from './pages/SettingsPage.tsx'
import { ApiShell, DemoShell } from './pages/Shells.tsx'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/app" element={<ApiShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="applications/:id" element={<ApplicationDetailPage />} />
        <Route path="follow-ups" element={<FollowUpsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/follow-ups" element={<FollowUpSettingsPage />} />
      </Route>
      <Route path="/demo" element={<DemoShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="applications/:id" element={<ApplicationDetailPage />} />
        <Route path="follow-ups" element={<FollowUpsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="settings/follow-ups" element={<FollowUpSettingsPage />} />
      </Route>
      <Route path="/goodbye" element={<GoodbyePage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
