import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Wallet, Loader2, CheckCircle2, Hand, Sparkles } from 'lucide-react';
import api from '../lib/api';

const BUCKETS = ['>120', '91-120', '61-90', '31-60', '0-30'];

interface ArItem {
  id: string; status: string; priority_label: string; assigned_to: string | null;
  claim_no: string; payer: string; patient: string; balance: number;
  charges: number; bucket: string; aging_days: string; service_date: string;
  is_credit: boolean; action: string;
  recommendation?: string | null; rec_reasoning?: string | null; rec_confidence?: number | null;
}

const REC_LABEL: Record<string, string> = {
  rebill: 'Rebill', corrected_claim: 'Corrected claim', appeal: 'Appeal',
  call_payer: 'Call payer', secondary_billing: 'Bill secondary',
  patient_balance: 'Patient balance', adjust_writeoff: 'Adjust / write-off',
  resolve_credit: 'Resolve credit',
};
interface ArResponse {
  summary: { open_ar_total: number; claim_count: number; buckets: Record<string, { count: number; balance: number }> };
  items: ArItem[]; total: number;
}

const money = (n: number) => `$${(n ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export function OpenArPage() {
  const qc = useQueryClient();
  const [bucket, setBucket] = useState<string | null>(null);
  const [status, setStatus] = useState<string>('pending');

  const { data, isLoading } = useQuery<ArResponse>({
    queryKey: ['open-ar', bucket, status],
    queryFn: () =>
      api.get('/queues/open-ar', { params: { bucket: bucket || undefined, status: status || undefined } }).then((r) => r.data),
  });

  const claim = useMutation({
    mutationFn: (id: string) => api.post(`/queues/queue/${id}/claim`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['open-ar'] }),
  });
  const complete = useMutation({
    mutationFn: (id: string) => api.post(`/queues/queue/${id}/complete`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['open-ar'] }),
  });
  const triageNow = useMutation({
    mutationFn: () => api.post('/queues/open-ar/triage', null, { params: { limit: 25 } }).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['open-ar'] }),
  });

  const s = data?.summary;
  const items = data?.items ?? [];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Wallet className="w-6 h-6 text-blue-600" />
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Open AR</h1>
            <p className="text-sm text-gray-500">Outstanding claims imported from the provider's aging file — work the oldest, highest-value first.</p>
          </div>
        </div>
        <button onClick={() => triageNow.mutate()} disabled={triageNow.isPending}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-xl px-4 py-2 text-sm font-medium flex items-center gap-2">
          {triageNow.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Triage now
        </button>
      </div>
      {triageNow.isSuccess && <div className="mb-3 text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-4 py-2">AI triaged {(triageNow.data as any)?.triaged ?? 0} claim(s). Recommendations updated below.</div>}

      {/* Summary */}
      <div className="grid grid-cols-6 gap-3 mb-5">
        <div className="col-span-1 bg-white border border-gray-200 rounded-xl p-4">
          <div className="text-xs text-gray-500">Open AR</div>
          <div className="text-xl font-bold text-gray-900">{money(s?.open_ar_total ?? 0)}</div>
          <div className="text-xs text-gray-400">{s?.claim_count ?? 0} claims</div>
        </div>
        {BUCKETS.map((b) => {
          const v = s?.buckets?.[b];
          const active = bucket === b;
          return (
            <button key={b} onClick={() => setBucket(active ? null : b)}
              className={`text-left rounded-xl p-4 border transition ${active ? 'border-blue-500 ring-2 ring-blue-200 bg-blue-50' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
              <div className={`text-xs ${b === '>120' ? 'text-red-600 font-semibold' : 'text-gray-500'}`}>{b} days</div>
              <div className="text-lg font-bold text-gray-900">{money(v?.balance ?? 0)}</div>
              <div className="text-xs text-gray-400">{v?.count ?? 0} claims</div>
            </button>
          );
        })}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-3 text-sm">
        {bucket && <button onClick={() => setBucket(null)} className="text-blue-600 hover:text-blue-700">Clear bucket filter ({bucket})</button>}
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="border border-gray-300 rounded-lg px-2 py-1 text-sm">
          <option value="pending">Pending</option>
          <option value="in_progress">In progress</option>
          <option value="completed">Completed</option>
          <option value="">All statuses</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400"><Loader2 className="w-5 h-5 animate-spin inline" /> Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs text-gray-500">
              <tr>
                <th className="px-4 py-3">Priority</th><th className="px-4 py-3">Payer</th>
                <th className="px-4 py-3">Patient</th><th className="px-4 py-3">Claim #</th>
                <th className="px-4 py-3">Bucket</th><th className="px-4 py-3">Days</th>
                <th className="px-4 py-3 text-right">Balance</th>
                <th className="px-4 py-3">AI recommendation</th><th className="px-4 py-3">Status</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {items.length === 0 ? (
                <tr><td colSpan={10} className="px-4 py-10 text-center text-gray-400">No open AR. Import a provider's aging file from the Onboard Provider screen.</td></tr>
              ) : items.map((it) => (
                <tr key={it.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3"><span className={`text-xs font-medium px-2 py-0.5 rounded-full ${it.priority_label === 'critical' ? 'bg-red-100 text-red-700' : it.priority_label === 'high' ? 'bg-orange-100 text-orange-700' : 'bg-gray-100 text-gray-600'}`}>{it.priority_label}</span></td>
                  <td className="px-4 py-3 text-gray-700">{it.payer}</td>
                  <td className="px-4 py-3 text-gray-700">{it.patient}</td>
                  <td className="px-4 py-3 text-gray-500">{it.claim_no}</td>
                  <td className="px-4 py-3"><span className={it.bucket === '>120' ? 'text-red-600 font-medium' : 'text-gray-600'}>{it.bucket}</span></td>
                  <td className="px-4 py-3 text-gray-500">{it.aging_days}</td>
                  <td className={`px-4 py-3 text-right font-medium ${it.is_credit ? 'text-amber-600' : 'text-gray-900'}`}>{money(it.balance)}{it.is_credit && <span className="ml-1 text-xs">(credit)</span>}</td>
                  <td className="px-4 py-3">{it.recommendation ? <span title={it.rec_reasoning || ''} className="inline-flex items-center text-xs font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">{REC_LABEL[it.recommendation] || it.recommendation}</span> : <span className="text-xs text-gray-300">pending triage</span>}</td>
                  <td className="px-4 py-3"><span className="text-xs text-gray-500">{it.status}</span></td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    {it.status === 'pending' && <button onClick={() => claim.mutate(it.id)} className="text-xs text-blue-600 hover:text-blue-700 inline-flex items-center gap-1"><Hand className="w-3 h-3" /> Claim</button>}
                    {it.status === 'in_progress' && <button onClick={() => complete.mutate(it.id)} className="text-xs text-green-600 hover:text-green-700 inline-flex items-center gap-1"><CheckCircle2 className="w-3 h-3" /> Resolve</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && <div className="text-xs text-gray-400 mt-2">{data.total} item(s){bucket ? ` in ${bucket}` : ''}.</div>}
    </div>
  );
}
