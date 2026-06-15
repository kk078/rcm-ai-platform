import { Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { LoginPage } from './pages/LoginPage';
import { ForcePasswordChangePage } from './pages/ForcePasswordChangePage';
import { DashboardPage } from './pages/DashboardPage';
import { QueuesPage } from './pages/QueuesPage';
import { ClaimsPage } from './pages/ClaimsPage';
import { ClaimDetailPage } from './pages/ClaimDetailPage';
import { ClaimFormPage } from './pages/ClaimFormPage';
import { AiAgentsPage } from './pages/AiAgentsPage';
import { CodingPage } from './pages/CodingPage';
import { PaymentsPage } from './pages/PaymentsPage';
import { DenialsPage } from './pages/DenialsPage';
import { ClientsPage } from './pages/ClientsPage';
import { BillingPage } from './pages/BillingPage';
import { SettingsPage } from './pages/SettingsPage';
import { AiAssistantPage } from './pages/AiAssistantPage';
import { EligibilityPage } from './pages/EligibilityPage';
import { PriorAuthPage } from './pages/PriorAuthPage';
import { PatientBillingPage } from './pages/PatientBillingPage';
import { DocumentsPage } from './pages/DocumentsPage';
import { EHRConnectionsPage } from './pages/EHRConnectionsPage';
import { ErrorIntelligencePage } from './pages/ErrorIntelligencePage';
import { ProviderUsersPage } from './pages/ProviderUsersPage';
import { UsersPage } from './pages/UsersPage';
import { ReferencesPage } from './pages/ReferencesPage';
import { OnboardingPage } from './pages/OnboardingPage';
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
        <Route path="dashboard"          element={<DashboardPage />} />
        <Route path="queues"             element={<QueuesPage />} />
        <Route path="claims"             element={<ClaimsPage />} />
        <Route path="claims/:claimId"    element={<ClaimDetailPage />} />
        <Route path="claims/:claimId/form" element={<ClaimFormPage />} />
        <Route path="coding"             element={<CodingPage />} />
        <Route path="payments"           element={<PaymentsPage />} />
        <Route path="denials"            element={<DenialsPage />} />
        <Route path="clients"            element={<ClientsPage />} />
        <Route path="onboarding"         element={<OnboardingPage />} />
        <Route path="billing"            element={<BillingPage />} />
        <Route path="settings"           element={<SettingsPage />} />
        <Route path="ai-assistant"       element={<AiAssistantPage />} />
        <Route path="agent-monitor"      element={<AiAgentsPage />} />
        <Route path="users"              element={<UsersPage />} />
        <Route path="references"         element={<ReferencesPage />} />
        <Route path="eligibility"        element={<EligibilityPage />} />
        <Route path="prior-auth"         element={<PriorAuthPage />} />
        <Route path="patient-billing"    element={<PatientBillingPage />} />
        <Route path="documents"          element={<DocumentsPage />} />
        <Route path="ehr-connections"    element={<EHRConnectionsPage />} />
        <Route path="error-intelligence" element={<ErrorIntelligencePage />} />
        <Route path="provider-logins"    element={<ProviderUsersPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
