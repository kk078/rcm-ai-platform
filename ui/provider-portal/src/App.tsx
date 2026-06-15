import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { ClaimsPage } from './pages/ClaimsPage';
import { ChargesPage } from './pages/ChargesPage';
import { DenialsPage } from './pages/DenialsPage';
import { MessagesPage } from './pages/MessagesPage';
import { ReportsPage } from './pages/ReportsPage';
import { InvoicesPage } from './pages/InvoicesPage';
import { SettingsPage } from './pages/SettingsPage';
import { ForcePasswordChangePage } from './pages/ForcePasswordChangePage';
import { AnalyticsPage } from './pages/AnalyticsPage';
import { useAuth } from './hooks/useAuth';

function MustChangeGuard({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/change-password"
        element={
          <ProtectedRoute>
            <ForcePasswordChangePage />
          </ProtectedRoute>
        }
      />
      <Route
        element={
          <ProtectedRoute>
            <MustChangeGuard>
              <Layout />
            </MustChangeGuard>
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard"  element={<DashboardPage />} />
        <Route path="claims"     element={<ClaimsPage />} />
        <Route path="charges"    element={<ChargesPage />} />
        <Route path="denials"    element={<DenialsPage />} />
        <Route path="analytics"  element={<AnalyticsPage />} />
        <Route path="messages"   element={<MessagesPage />} />
        <Route path="reports"    element={<ReportsPage />} />
        <Route path="invoices"   element={<InvoicesPage />} />
        <Route path="settings"   element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
