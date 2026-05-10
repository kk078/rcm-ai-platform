import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText, Search } from 'lucide-react';
import api from '../lib/api';

interface Claim {
  id: string;
  claim_number: string;
  patient_name: string;
  date_of_service: string;
  total_charge: number;
  status: string;
  payer_name: string;
  timeline: { status: string; timestamp: string; note?: string }[];
}

interface ClaimsResponse {
  items: Claim[];
  total: number;
  page: number;
  page_size: number;
}

const STATUS_FLOW = ['draft', 'submitted', 'accepted', 'in_process', 'paid', 'denied'];

export function ClaimsPage() {
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery<ClaimsResponse>({
    queryKey: ['provider-claims'],
    queryFn: () =>
      api
        .get('/portal/claims/', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const filtered = data?.items.filter(
    (c) =>
      !search ||
      c.claim_number.toLowerCase().includes(search.toLowerCase()) ||
      c.patient_name.toLowerCase().includes(search.toLowerCase()),
  );

  const statusStep = (status: string) => {
    const idx = STATUS_FLOW.indexOf(status);
    return idx >= 0 ? idx : STATUS_FLOW.length - 1;
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">My Claims</h1>
        <p className="mt-1 text-sm text-gray-500">Track the status of your claims</p>
      </div>

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search claims..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-40 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="space-y-4">
          {filtered?.map((claim) => {
            const currentStep = statusStep(claim.status);
            return (
              <div key={claim.id} className="rounded-xl border border-gray-200 bg-white p-5">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <h3 className="font-medium text-gray-900">{claim.claim_number}</h3>
                    <p className="text-sm text-gray-500">
                      {claim.patient_name} · {claim.date_of_service} · {claim.payer_name}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-lg font-semibold text-gray-900">${claim.total_charge.toLocaleString()}</p>
                    <p className="text-xs text-gray-500">Total Charge</p>
                  </div>
                </div>

                {/* Visual timeline */}
                <div className="flex items-center gap-1">
                  {STATUS_FLOW.map((step, i) => {
                    const isComplete = i <= currentStep && currentStep < STATUS_FLOW.indexOf('denied');
                    const isDenied = claim.status === 'denied' && i === STATUS_FLOW.indexOf('denied');
                    return (
                      <div key={step} className="flex-1 flex flex-col items-center">
                        <div className={`h-2 w-full rounded-full ${isComplete ? 'bg-brand-500' : isDenied ? 'bg-red-500' : 'bg-gray-200'}`} />
                        <span className="mt-1 text-xs text-gray-500 capitalize">{step.replace('_', ' ')}</span>
                      </div>
                    );
                  })}
                </div>

                {/* Timeline events */}
                {claim.timeline && claim.timeline.length > 0 && (
                  <div className="mt-4 space-y-2">
                    {claim.timeline.slice(-3).map((event, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm text-gray-600">
                        <div className="h-1.5 w-1.5 rounded-full bg-brand-400" />
                        <span>{event.status.replace('_', ' ')}</span>
                        <span className="text-gray-400">·</span>
                        <span className="text-gray-400">{event.timestamp}</span>
                        {event.note && <span className="text-gray-400">— {event.note}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {(!filtered?.length) && (
            <div className="py-12 text-center text-sm text-gray-500">
              <FileText className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              No claims found
            </div>
          )}
        </div>
      )}
    </div>
  );
}