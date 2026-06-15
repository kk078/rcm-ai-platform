import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Search, Filter } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber } from '../lib/apiHelpers';

interface Denial {
  id: string;
  claim_id: string;
  claim_number: string;
  patient_name: string;
  payer_name: string;
  denial_code: string;
  denial_reason: string;
  appeal_status: string;
  appeal_deadline: string | null;
  days_remaining: number | null;
  amount_denied: number;
  created_at: string;
}

const APPEAL_STATUSES = ['all', 'not_started', 'in_progress', 'appealed', 'won', 'lost', 'expired'] as const;

export function DenialsPage() {
  const [appealStatus, setAppealStatus] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['denials', appealStatus, page],
    queryFn: () =>
      api
        .get('/denials/', {
          params: { appeal_status: appealStatus !== 'all' ? appealStatus : undefined, page, page_size: 20 },
        })
        .then((r) => r.data),
  });

  const data = normalizeListResponse<Denial>(rawData);

  const fmtCurrency = (v: number) =>
    '$' + safeNumber(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      not_started: 'bg-gray-100 text-gray-700',
      in_progress: 'bg-blue-100 text-blue-700',
      appealed: 'bg-purple-100 text-purple-700',
      won: 'bg-green-100 text-green-700',
      lost: 'bg-red-100 text-red-700',
      expired: 'bg-orange-100 text-orange-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  const filtered = data.items.filter(
    (d) =>
      !search ||
      (d.claim_number ?? '').toLowerCase().includes(search.toLowerCase()) ||
      (d.denial_code ?? '').toLowerCase().includes(search.toLowerCase()) ||
      (d.patient_name ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Denial Management</h1>
        <p className="mt-1 text-sm text-gray-500">{data.total} denials</p>
      </div>

      <div className="mb-4 flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search denials..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <select
            value={appealStatus}
            onChange={(e) => { setAppealStatus(e.target.value); setPage(1); }}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {APPEAL_STATUSES.map((s) => (
              <option key={s} value={s}>{s === 'all' ? 'All Appeal Statuses' : s.replace('_', ' ')}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Claim #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Patient</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Payer</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Code</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Amount</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Appeal Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Days Left</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((denial) => (
                <tr key={denial.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-brand-600">{denial.claim_number ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{denial.patient_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{denial.payer_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{denial.denial_code ?? '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium text-red-600">{fmtCurrency(denial.amount_denied)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(denial.appeal_status ?? '')}`}>
                      {(denial.appeal_status ?? '').replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">
                    {denial.days_remaining != null ? (
                      <span className={denial.days_remaining <= 5 ? 'font-semibold text-red-600' : ''}>
                        {denial.days_remaining}d
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No denials found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
