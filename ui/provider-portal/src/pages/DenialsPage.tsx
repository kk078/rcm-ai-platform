import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Search } from 'lucide-react';
import api from '../lib/api';

interface Denial {
  id: string;
  claim_number: string;
  patient_name: string;
  denial_code: string;
  denial_reason: string;
  amount_denied: number;
  appeal_status: string;
  days_remaining: number | null;
}

interface DenialsResponse {
  items: Denial[];
  total: number;
  page: number;
  page_size: number;
}

export function DenialsPage() {
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery<DenialsResponse>({
    queryKey: ['provider-denials'],
    queryFn: () =>
      api
        .get('/portal/denials/', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const filtered = data?.items.filter(
    (d) =>
      !search ||
      d.claim_number.toLowerCase().includes(search.toLowerCase()) ||
      d.denial_code.toLowerCase().includes(search.toLowerCase()),
  );

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      not_started: 'bg-gray-100 text-gray-700',
      in_progress: 'bg-blue-100 text-blue-700',
      appealed: 'bg-purple-100 text-purple-700',
      won: 'bg-green-100 text-green-700',
      lost: 'bg-red-100 text-red-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Denials</h1>
        <p className="mt-1 text-sm text-gray-500">{data?.total ?? 0} denials requiring attention</p>
      </div>

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search denials..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered?.map((denial) => (
            <div key={denial.id} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900">{denial.claim_number}</span>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(denial.appeal_status)}`}>
                      {denial.appeal_status.replace('_', ' ')}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-gray-600">{denial.patient_name}</p>
                  <p className="text-sm text-gray-500">
                    Code: {denial.denial_code} · {denial.denial_reason}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-semibold text-red-600">${denial.amount_denied.toLocaleString()}</p>
                  {denial.days_remaining !== null && (
                    <p className={`text-sm ${denial.days_remaining <= 5 ? 'font-semibold text-red-600' : 'text-gray-500'}`}>
                      {denial.days_remaining}d to appeal
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))}
          {(!filtered?.length) && (
            <div className="py-12 text-center text-sm text-gray-500">
              <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              No denials found
            </div>
          )}
        </div>
      )}
    </div>
  );
}