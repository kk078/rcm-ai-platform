import { useQuery } from '@tanstack/react-query';
import { FileText, DollarSign, AlertTriangle, TrendingUp } from 'lucide-react';
import api from '../lib/api';

interface DashboardData {
  practice_name: string;
  total_claims: number;
  claims_submitted_this_month: number;
  total_collected: number;
  collection_rate: number;
  open_denials: number;
  denial_rate: number;
  avg_days_in_ar: number;
  recent_claims: { id: string; claim_number: string; patient_name: string; status: string; amount: number }[];
}

export function DashboardPage() {
  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ['provider-dashboard'],
    queryFn: () => api.get('/portal/dashboard').then((r) => r.data),
  });

  const statusColor = (s: string) => {
    const colors: Record<string, string> = {
      submitted: 'bg-blue-100 text-blue-700',
      accepted: 'bg-green-100 text-green-700',
      paid: 'bg-emerald-100 text-emerald-700',
      denied: 'bg-red-100 text-red-700',
      in_process: 'bg-yellow-100 text-yellow-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">{data?.practice_name ?? 'Loading...'}</p>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-4 mb-8">
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-blue-50 p-2">
                  <FileText className="h-4 w-4 text-blue-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">Total Claims</p>
                  <p className="text-xl font-semibold text-gray-900">{data?.total_claims.toLocaleString()}</p>
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-emerald-50 p-2">
                  <DollarSign className="h-4 w-4 text-emerald-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">Total Collected</p>
                  <p className="text-xl font-semibold text-gray-900">${data?.total_collected.toLocaleString()}</p>
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-amber-50 p-2">
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">Open Denials</p>
                  <p className="text-xl font-semibold text-gray-900">{data?.open_denials}</p>
                </div>
              </div>
            </div>
            <div className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className="rounded-lg bg-brand-50 p-2">
                  <TrendingUp className="h-4 w-4 text-brand-600" />
                </div>
                <div>
                  <p className="text-xs text-gray-500">Collection Rate</p>
                  <p className="text-xl font-semibold text-gray-900">{((data?.collection_rate ?? 0) * 100).toFixed(1)}%</p>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-lg font-semibold text-gray-900">Recent Claims</h2>
            <table className="w-full">
              <thead className="text-left">
                <tr className="border-b border-gray-100">
                  <th className="pb-2 text-xs font-medium text-gray-500">Claim #</th>
                  <th className="pb-2 text-xs font-medium text-gray-500">Patient</th>
                  <th className="pb-2 text-xs font-medium text-gray-500">Amount</th>
                  <th className="pb-2 text-xs font-medium text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data?.recent_claims.map((claim) => (
                  <tr key={claim.id} className="hover:bg-gray-50">
                    <td className="py-2 text-sm font-medium text-brand-600">{claim.claim_number}</td>
                    <td className="py-2 text-sm text-gray-900">{claim.patient_name}</td>
                    <td className="py-2 text-sm text-gray-900">${claim.amount.toLocaleString()}</td>
                    <td className="py-2">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(claim.status)}`}>
                        {claim.status.replace('_', ' ')}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}