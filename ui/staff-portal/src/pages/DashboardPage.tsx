import { useQuery } from '@tanstack/react-query';
import {
  LayoutDashboard,
  FileText,
  DollarSign,
  AlertTriangle,
  TrendingUp,
  Clock,
} from 'lucide-react';
import api from '../lib/api';

interface KpiData {
  total_claims: number;
  claims_submitted_today: number;
  total_payments: number;
  payments_posted_today: number;
  open_denials: number;
  denial_rate: number;
  avg_days_in_ar: number;
  clean_claim_rate: number;
}

interface QueueSummary {
  my_queue_count: number;
  team_queue_count: number;
  unassigned_count: number;
}

export function DashboardPage() {
  const { data: kpi, isLoading: kpiLoading } = useQuery<KpiData>({
    queryKey: ['dashboard-kpi'],
    queryFn: () => api.get('/queues/dashboard').then((r) => r.data),
  });

  const { data: queues } = useQuery<QueueSummary>({
    queryKey: ['queue-summary'],
    queryFn: () => api.get('/queues/my-queue').then((r) => r.data),
  });

  const kpiCards = kpi
    ? [
        { label: 'Total Claims', value: kpi.total_claims.toLocaleString(), icon: FileText, color: 'text-blue-600 bg-blue-50' },
        { label: 'Submitted Today', value: kpi.claims_submitted_today.toLocaleString(), icon: TrendingUp, color: 'text-green-600 bg-green-50' },
        { label: 'Payments Posted', value: `$${kpi.total_payments.toLocaleString()}`, icon: DollarSign, color: 'text-emerald-600 bg-emerald-50' },
        { label: 'Posted Today', value: `$${kpi.payments_posted_today.toLocaleString()}`, icon: DollarSign, color: 'text-emerald-600 bg-emerald-50' },
        { label: 'Open Denials', value: kpi.open_denials.toLocaleString(), icon: AlertTriangle, color: 'text-amber-600 bg-amber-50' },
        { label: 'Denial Rate', value: `${(kpi.denial_rate * 100).toFixed(1)}%`, icon: AlertTriangle, color: 'text-red-600 bg-red-50' },
        { label: 'Avg Days in AR', value: kpi.avg_days_in_ar.toString(), icon: Clock, color: 'text-purple-600 bg-purple-50' },
        { label: 'Clean Claim Rate', value: `${(kpi.clean_claim_rate * 100).toFixed(1)}%`, icon: LayoutDashboard, color: 'text-brand-600 bg-brand-50' },
      ]
    : [];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          {queues ? `${queues.my_queue_count} items in your queue` : 'Loading...'}
        </p>
      </div>

      {kpiLoading ? (
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-4">
          {kpiCards.map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className={`rounded-lg p-2 ${color}`}>
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">{label}</p>
                  <p className="text-xl font-semibold text-gray-900">{value}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}