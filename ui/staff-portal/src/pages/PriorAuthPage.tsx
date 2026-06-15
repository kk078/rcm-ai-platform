import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, Plus, X, AlertTriangle, Clock } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse } from '../lib/apiHelpers';

interface PriorAuth {
  id: string;
  patient_name: string;
  auth_number: string | null;
  payer_name: string;
  procedure_codes: string[];
  status: string;
  valid_from: string | null;
  valid_to: string | null;
  days_remaining: number | null;
}

interface ExpiringAlert { count_7: number; count_30: number; }

const STATUS_TABS = ['all', 'pending', 'approved', 'denied', 'expired'] as const;

function statusBadge(s: string) {
  const map: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-700',
    approved: 'bg-green-100 text-green-700',
    denied: 'bg-red-100 text-red-700',
    expired: 'bg-gray-200 text-gray-500',
  };
  return map[s] || 'bg-gray-100 text-gray-700';
}

const emptyForm = {
  patient_id: '', payer: '', procedure_codes: '', diagnosis_codes: '',
  requested_date: '', valid_from: '', valid_to: '', notes: '',
};

export function PriorAuthPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState('all');
  const [expiringSoon, setExpiringSoon] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editTarget, setEditTarget] = useState<PriorAuth | null>(null);
  const [form, setForm] = useState(emptyForm);

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['prior-auth', tab, expiringSoon],
    queryFn: () => {
      if (expiringSoon) return api.get('/prior-auth/expiring/soon', { params: { days: 7 } }).then((r) => r.data);
      return api.get('/prior-auth/', { params: { status: tab !== 'all' ? tab : undefined } }).then((r) => r.data);
    },
  });
  const data = normalizeListResponse<PriorAuth>(rawData);

  const { data: alertData } = useQuery<ExpiringAlert>({
    queryKey: ['prior-auth-expiring'],
    queryFn: () => api.get('/prior-auth/expiring/soon', { params: { days: 30 } }).then((r) => r.data),
  });

  const create = useMutation({
    mutationFn: (payload: typeof form) =>
      api.post('/prior-auth/', {
        ...payload,
        procedure_codes: payload.procedure_codes.split(',').map((s) => s.trim()).filter(Boolean),
        diagnosis_codes: payload.diagnosis_codes.split(',').map((s) => s.trim()).filter(Boolean),
      }).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['prior-auth'] }); setShowModal(false); setForm(emptyForm); },
  });

  const update = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.patch(`/prior-auth/${id}`, { status }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['prior-auth'] }),
  });

  const count7 = (alertData as any)?.count_7 ?? (alertData as any)?.total ?? 0;
  const count30 = (alertData as any)?.count_30 ?? 0;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Prior Authorization</h1>
          <p className="mt-1 text-sm text-gray-500">{data.total} authorizations</p>
        </div>
        <button
          onClick={() => { setShowModal(true); setForm(emptyForm); }}
          className="inline-flex items-center gap-2 rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 transition-colors"
        >
          <Plus className="h-4 w-4" /> New PA Request
        </button>
      </div>

      {/* Expiry alerts */}
      {count7 > 0 && (
        <div className="mb-3 flex items-center gap-3 rounded-lg bg-red-50 border border-red-200 px-4 py-3">
          <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
          <p className="text-sm text-red-700 font-medium">{count7} authorization{count7 !== 1 ? 's' : ''} expiring within 7 days — action required.</p>
        </div>
      )}
      {count30 > 0 && count7 === 0 && (
        <div className="mb-3 flex items-center gap-3 rounded-lg bg-orange-50 border border-orange-200 px-4 py-3">
          <Clock className="h-4 w-4 text-orange-600 shrink-0" />
          <p className="text-sm text-orange-700 font-medium">{count30} authorization{count30 !== 1 ? 's' : ''} expiring within 30 days.</p>
        </div>
      )}

      {/* Filter controls */}
      <div className="mb-4 flex items-center gap-3 flex-wrap">
        <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
          {STATUS_TABS.map((t) => (
            <button
              key={t}
              onClick={() => { setTab(t); setExpiringSoon(false); }}
              className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                tab === t && !expiringSoon ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        <button
          onClick={() => setExpiringSoon((v) => !v)}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
            expiringSoon ? 'border-red-400 bg-red-50 text-red-700' : 'border-gray-300 text-gray-600 hover:bg-gray-50'
          }`}
        >
          <Clock className="h-3.5 w-3.5" /> Expiring Soon
        </button>
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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Auth #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Procedure Codes</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Valid From</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Valid To</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Days Left</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((pa) => (
                <tr key={pa.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900">{pa.patient_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium text-aethera-600">{pa.auth_number ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{(pa.procedure_codes ?? []).join(', ') || '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusBadge(pa.status ?? '')}`}>
                      {pa.status ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{pa.valid_from ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{pa.valid_to ?? '—'}</td>
                  <td className="px-4 py-3 text-sm">
                    {pa.days_remaining != null ? (
                      <span className={pa.days_remaining <= 7 ? 'font-semibold text-red-600' : pa.days_remaining <= 30 ? 'font-semibold text-orange-600' : 'text-gray-600'}>
                        {pa.days_remaining}d
                      </span>
                    ) : '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => { setEditTarget(pa); setShowModal(true); }}
                        className="rounded px-2 py-1 text-xs font-medium text-gray-600 hover:bg-gray-100"
                      >
                        Edit
                      </button>
                      {pa.status === 'pending' && (
                        <button
                          onClick={() => update.mutate({ id: pa.id, status: 'approved' })}
                          className="rounded px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-50"
                        >
                          Approve
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {data.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">
                    <ShieldAlert className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No prior authorizations found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && !editTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">New PA Request</h2>
              <button onClick={() => { setShowModal(false); setEditTarget(null); }} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X className="h-4 w-4 text-gray-500" />
              </button>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {[
                { key: 'patient_id', label: 'Patient ID', placeholder: 'Patient ID' },
                { key: 'payer', label: 'Payer', placeholder: 'Payer name' },
                { key: 'procedure_codes', label: 'Procedure Codes (comma-separated)', placeholder: '99213, 99214' },
                { key: 'diagnosis_codes', label: 'Diagnosis Codes (comma-separated)', placeholder: 'Z00.00, M54.5' },
              ].map(({ key, label, placeholder }) => (
                <div key={key} className="col-span-2">
                  <label className="mb-1 block text-xs font-medium text-gray-700">{label}</label>
                  <input
                    type="text"
                    value={form[key as keyof typeof form]}
                    onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                    placeholder={placeholder}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  />
                </div>
              ))}
              {[
                { key: 'requested_date', label: 'Requested Date' },
                { key: 'valid_from', label: 'Valid From' },
                { key: 'valid_to', label: 'Valid To' },
              ].map(({ key, label }) => (
                <div key={key}>
                  <label className="mb-1 block text-xs font-medium text-gray-700">{label}</label>
                  <input
                    type="date"
                    value={form[key as keyof typeof form]}
                    onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  />
                </div>
              ))}
              <div className="col-span-2">
                <label className="mb-1 block text-xs font-medium text-gray-700">Notes</label>
                <textarea
                  rows={2}
                  value={form.notes}
                  onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
            </div>
            {create.isError && <p className="mt-2 text-xs text-red-600">Error submitting request. Please try again.</p>}
            <div className="mt-4 flex justify-end gap-3">
              <button onClick={() => { setShowModal(false); setEditTarget(null); }} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">Cancel</button>
              <button
                onClick={() => create.mutate(form)}
                disabled={create.isPending}
                className="rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 disabled:opacity-50"
              >
                {create.isPending ? 'Submitting...' : 'Submit Request'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
