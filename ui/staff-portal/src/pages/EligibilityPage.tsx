import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldCheck, Search, X, Plus, ChevronDown, ChevronUp } from 'lucide-react';
import React from 'react';
import api from '../lib/api';
import { normalizeListResponse, formatDate } from '../lib/apiHelpers';

interface EligibilityCheck {
  id: string;
  patient_name: string;
  payer_name: string;
  plan_name: string | null;
  status: string;
  network_status: string | null;
  check_date: string;
  deductible_individual: number | null;
  deductible_met: number | null;
  oop_individual: number | null;
  oop_met: number | null;
  service_date: string | null;
}

const STATUS_TABS = ['all', 'active', 'inactive', 'error'] as const;

function statusBadge(s: string) {
  const map: Record<string, string> = {
    active: 'bg-green-100 text-green-700',
    inactive: 'bg-red-100 text-red-700',
    pending: 'bg-yellow-100 text-yellow-700',
    error: 'bg-red-100 text-red-700',
  };
  return map[s] || 'bg-gray-100 text-gray-700';
}

export function EligibilityPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<string>('all');
  const [search, setSearch] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [form, setForm] = useState({ patient_id: '', payer_id: '', service_date: '' });

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['eligibility', tab],
    queryFn: () =>
      api.get('/eligibility/', { params: { status: tab !== 'all' ? tab : undefined } }).then((r) => r.data),
  });
  const data = normalizeListResponse<EligibilityCheck>(rawData);

  const runCheck = useMutation({
    mutationFn: (payload: typeof form) => api.post('/eligibility/check', payload).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['eligibility'] }); setShowModal(false); setForm({ patient_id: '', payer_id: '', service_date: '' }); },
  });

  const filtered = data.items.filter((c) =>
    !search ||
    (c.patient_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
    (c.payer_name ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Eligibility Verification</h1>
          <p className="mt-1 text-sm text-gray-500">{data.total} checks on record</p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 transition-colors"
        >
          <Plus className="h-4 w-4" /> Run Check
        </button>
      </div>

      <div className="mb-4 flex gap-1 rounded-lg bg-gray-100 p-1 w-fit">
        {STATUS_TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
              tab === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="mb-4 flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search by patient or payer..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Patient</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Payer</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Check Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Network</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Plan Name</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((chk) => (
                <React.Fragment key={chk.id}>
                  <tr className="hover:bg-gray-50 cursor-pointer">
                    <td className="px-4 py-3 text-sm font-medium text-gray-900">{chk.patient_name ?? '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{chk.payer_name ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusBadge(chk.status ?? '')}`}>
                        {chk.status ?? '—'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-600">{chk.check_date ? formatDate(chk.check_date) : '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600 capitalize">{chk.network_status ?? '—'}</td>
                    <td className="px-4 py-3 text-sm text-gray-600">{chk.plan_name ?? '—'}</td>
                    <td className="px-4 py-3">
                      <button
                        onClick={() => setExpandedId(expandedId === chk.id ? null : chk.id)}
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-aethera-600 hover:bg-aethera-50"
                      >
                        {expandedId === chk.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                        Details
                      </button>
                    </td>
                  </tr>
                  {expandedId === chk.id && (
                    <tr className="bg-blue-50">
                      <td colSpan={7} className="px-6 py-4">
                        <div className="grid grid-cols-4 gap-4 text-sm">
                          <div>
                            <p className="text-xs font-medium text-gray-500">Deductible (Ind.)</p>
                            <p className="font-semibold text-gray-900">${(chk.deductible_individual ?? 0).toLocaleString()}</p>
                            <p className="text-xs text-gray-500">Met: ${(chk.deductible_met ?? 0).toLocaleString()}</p>
                          </div>
                          <div>
                            <p className="text-xs font-medium text-gray-500">OOP Max (Ind.)</p>
                            <p className="font-semibold text-gray-900">${(chk.oop_individual ?? 0).toLocaleString()}</p>
                            <p className="text-xs text-gray-500">Met: ${(chk.oop_met ?? 0).toLocaleString()}</p>
                          </div>
                          <div>
                            <p className="text-xs font-medium text-gray-500">Service Date</p>
                            <p className="font-semibold text-gray-900">{chk.service_date ? formatDate(chk.service_date) : '—'}</p>
                          </div>
                          <div>
                            <p className="text-xs font-medium text-gray-500">Check Date</p>
                            <p className="font-semibold text-gray-900">{chk.check_date ? formatDate(chk.check_date) : '—'}</p>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    <ShieldCheck className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No eligibility checks found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Run Eligibility Check</h2>
              <button onClick={() => setShowModal(false)} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X className="h-4 w-4 text-gray-500" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Patient ID</label>
                <input
                  type="text"
                  value={form.patient_id}
                  onChange={(e) => setForm((f) => ({ ...f, patient_id: e.target.value }))}
                  placeholder="Patient ID or search..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Payer ID / Name</label>
                <input
                  type="text"
                  value={form.payer_id}
                  onChange={(e) => setForm((f) => ({ ...f, payer_id: e.target.value }))}
                  placeholder="Payer..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Service Date</label>
                <input
                  type="date"
                  value={form.service_date}
                  onChange={(e) => setForm((f) => ({ ...f, service_date: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
              {runCheck.isError && (
                <p className="text-xs text-red-600">Error running check. Please try again.</p>
              )}
              <div className="flex justify-end gap-3 pt-2">
                <button onClick={() => setShowModal(false)} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">Cancel</button>
                <button
                  onClick={() => runCheck.mutate(form)}
                  disabled={runCheck.isPending}
                  className="rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 disabled:opacity-50"
                >
                  {runCheck.isPending ? 'Running...' : 'Run Check'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
