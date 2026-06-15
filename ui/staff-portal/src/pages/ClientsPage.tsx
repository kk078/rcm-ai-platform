import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Building2, Search } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse } from '../lib/apiHelpers';

interface Practice {
  id: string;
  practice_name: string;
  legal_name: string | null;
  group_npi: string | null;
  specialty_primary: string | null;
  status: string;
  intake_method: string;
  go_live_date: string | null;
  provider_count: number | null;
  active_claims_count: number | null;
}

export function ClientsPage() {
  const [search, setSearch] = useState('');
  const { data: rawData, isLoading } = useQuery({
    queryKey: ['clients'],
    queryFn: () =>
      api
        .get('/clients/practices')
        .then((r) => r.data),
  });

  const data = normalizeListResponse<Practice>(rawData);
  const items = data.items;

  const filtered = items.filter(
    (c) => !search || (c.practice_name ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Client Management</h1>
        <p className="mt-1 text-sm text-gray-500">{filtered.length} practices</p>
      </div>

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search clients..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((practice) => (
            <div key={practice.id} className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-shadow">
              <div className="flex items-center gap-3 mb-3">
                <div className="h-10 w-10 rounded-lg bg-brand-50 flex items-center justify-center">
                  <Building2 className="h-5 w-5 text-brand-600" />
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">{practice.practice_name}</h3>
                  <p className="text-xs text-gray-500">{practice.specialty_primary || 'N/A'}</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <p className="text-gray-500">NPI</p>
                  <p className="font-medium text-gray-900">{practice.group_npi || 'N/A'}</p>
                </div>
                <div>
                  <p className="text-gray-500">Status</p>
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    practice.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
                  }`}>
                    {practice.status}
                  </span>
                </div>
                <div>
                  <p className="text-gray-500">Go-Live</p>
                  <p className="text-gray-900">{practice.go_live_date || 'TBD'}</p>
                </div>
                <div>
                  <p className="text-gray-500">Intake</p>
                  <p className="text-gray-900">{practice.intake_method}</p>
                </div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="col-span-3 py-12 text-center text-sm text-gray-500">
              <Building2 className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              No clients found
            </div>
          )}
        </div>
      )}
    </div>
  );
}