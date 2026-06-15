import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { FileText, Search, Filter } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber } from '../lib/apiHelpers';

interface Claim {
  id: string;
  claim_number: string;
  patient_name: string;
  practice_name: string;
  payer_name: string;
  status: string;
  total_charge: number;
  date_of_service: string;
  submitted_at: string | null;
}

const STATUSES = ['all', 'draft', 'submitted', 'accepted', 'denied', 'paid', 'partially_paid'] as const;

export function ClaimsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['claims', status, page],
    queryFn: () =>
      api
        .get('/claims/', {
          params: { status: status !== 'all' ? status : undefined, page, page_size: 20 },
        })
        .then((r) => r.data),
  });

  const data = normalizeListResponse<Claim>(rawData);
  const total = data.total;

  const statusColor = (s: string) => {
    const colors: Record<string, string> = {
      draft: 'bg-gray-100 text-gray-700',
      submitted: 'bg-blue-100 text-blue-700',
      accepted: 'bg-green-100 text-green-700',
      denied: 'bg-red-100 text-red-700',
      paid: 'bg-emerald-100 text-emerald-700',
      partially_paid: 'bg-yellow-100 text-yellow-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  const filtered = data.items.filter(
    (c) =>
      !search ||
      c.claim_number.toLowerCase().includes(search.toLowerCase()) ||
      (c.patient_name ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Claims</h1>
        <p className="mt-1 text-sm text-gray-500">{total} total claims</p>
      </div>

      <div className="mb-4 flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search claims..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <select
            value={status}
            onChange={(e) => { setStatus(e.target.value); setPage(1); }}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm"
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s === 'all' ? 'All Statuses' : s.replace('_', ' ')}</option>
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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Practice</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Payer</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Charge</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">DOS</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((claim) => (
                <tr
                  key={claim.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/claims/${claim.id}`)}
                >
                  <td className="px-4 py-3 text-sm font-medium text-brand-600">{claim.claim_number}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{claim.patient_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{claim.practice_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{claim.payer_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">${safeNumber(claim.total_charge).toLocaleString()}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{claim.date_of_service ?? '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusColor(claim.status)}`}>
                      {claim.status.replace('_', ' ')}
                    </span>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    <FileText className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No claims found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {total > 20 && (
        <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
          <span>Page {page} of {Math.ceil(total / 20)}</span>
          <div className="flex gap-2">
            <button
              disabled={page === 1}
              onClick={() => setPage(p => p - 1)}
              className="rounded border border-gray-300 px-3 py-1 disabled:opacity-40 hover:bg-gray-50"
            >Prev</button>
            <button
              disabled={page * 20 >= total}
              onClick={() => setPage(p => p + 1)}
              className="rounded border border-gray-300 px-3 py-1 disabled:opacity-40 hover:bg-gray-50"
            >Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
