import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { QueuesPage } from './pages/QueuesPage';
import { ClaimsPage } from './pages/ClaimsPage';
import { CodingPage } from './pages/CodingPage';
import { PaymentsPage } from './pages/PaymentsPage';
import { DenialsPage } from './pages/DenialsPage';
import { ClientsPage } from './pages/ClientsPage';
import { BillingPage } from './pages/BillingPage';
import { SettingsPage } from './pages/SettingsPage';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="queues" element={<QueuesPage />} />
        <Route path="claims" element={<ClaimsPage />} />
        <Route path="coding" element={<CodingPage />} />
        <Route path="payments" element={<PaymentsPage />} />
        <Route path="denials" element={<DenialsPage />} />
        <Route path="clients" element={<ClientsPage />} />
        <Route path="billing" element={<BillingPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}