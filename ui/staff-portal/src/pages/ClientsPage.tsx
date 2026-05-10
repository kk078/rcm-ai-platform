import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Building2, Search } from 'lucide-react';
import api from '../lib/api';

interface Client {
  id: string;
  name: string;
  contact_email: string;
  contract_start: string;
  contract_end: string;
  active_practice_count: number;
  status: string;
}

interface ClientsResponse {
  items: Client[];
  total: number;
  page: number;
  page_size: number;
}

export function ClientsPage() {
  const [search, setSearch] = useState('');
  const { data, isLoading } = useQuery<ClientsResponse>({
    queryKey: ['clients'],
    queryFn: () =>
      api
        .get('/clients/', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const filtered = data?.items.filter(
    (c) => !search || c.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Client Management</h1>
        <p className="mt-1 text-sm text-gray-500">{data?.total ?? 0} clients</p>
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
          {filtered?.map((client) => (
            <div key={client.id} className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-shadow">
              <div className="flex items-center gap-3 mb-3">
                <div className="h-10 w-10 rounded-lg bg-brand-50 flex items-center justify-center">
                  <Building2 className="h-5 w-5 text-brand-600" />
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">{client.name}</h3>
                  <p className="text-xs text-gray-500">{client.contact_email}</p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div>
                  <p className="text-gray-500">Practices</p>
                  <p className="font-medium text-gray-900">{client.active_practice_count}</p>
                </div>
                <div>
                  <p className="text-gray-500">Status</p>
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                    client.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
                  }`}>
                    {client.status}
                  </span>
                </div>
                <div>
                  <p className="text-gray-500">Contract Start</p>
                  <p className="text-gray-900">{client.contract_start}</p>
                </div>
                <div>
                  <p className="text-gray-500">Contract End</p>
                  <p className="text-gray-900">{client.contract_end}</p>
                </div>
              </div>
            </div>
          ))}
          {(!filtered?.length) && (
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