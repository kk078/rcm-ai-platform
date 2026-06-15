import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Receipt, DollarSign, Clock, AlertTriangle, X } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber, formatDate } from '../lib/apiHelpers';

interface Statement {
  id: string;
  patient_id: string;
  patient_name?: string;
  statement_number: string;
  statement_date: string;
  due_date: string;
  total_charges: number;
  total_insurance_paid: number;
  total_patient_paid: number;
  amount_billed?: number;
  amount_paid?: number;
  balance_due: number;
  status: string;
}

interface ARSummary {
  total_ar: number;
  current_0_30: number;
  ar_31_60: number;
  ar_90_plus: number;
}

const STATUS_TABS = ['all', 'open', 'partial', 'paid'] as const;

function statusBadge(s: string) {
  const map: Record<string, string> = {
    open: 'bg-blue-100 text-blue-700',
    partial: 'bg-yellow-100 text-yellow-700',
    paid: 'bg-green-100 text-green-700',
    overdue: 'bg-red-100 text-red-700',
    collections: 'bg-purple-100 text-purple-700',
  };
  return map[s] || 'bg-gray-100 text-gray-700';
}

export function PatientBillingPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState('all');
  const [payTarget, setPayTarget] = useState<Statement | null>(null);
  const [payForm, setPayForm] = useState({ amount: '', reference: '' });

  const { data: arData, isLoading: arLoading } = useQuery<ARSummary>({
    queryKey: ['patient-billing-ar'],
    queryFn: () => api.get('/patient-billing/ar-summary').then((r) => r.data),
  });

  const { data: rawStatements, isLoading: stmtLoading } = useQuery({
    queryKey: ['patient-billing-statements', tab],
    queryFn: () =>
      api.get('/patient-billing/statements', { params: { status: tab !== 'all' ? tab : undefined } }).then((r) => r.data),
  });
  const stmts = normalizeListResponse<Statement>(rawStatements);

  const postPayment = useMutation({
    mutationFn: ({ id, amount, reference }: { id: string; amount: number; reference: string }) =>
      api.post('/patient-billing/payments', { statement_id: id, amount, reference_number: reference }).then((r) => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['patient-billing-statements'] });
      qc.invalidateQueries({ queryKey: ['patient-billing-ar'] });
      setPayTarget(null);
      setPayForm({ amount: '', reference: '' });
    },
  });

  const fmtCurrency = (v: number) =>
    '$' + safeNumber(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const statCards = [
    { label: 'Total A/R', value: safeNumber(arData?.total_ar), icon: DollarSign, iconBg: 'bg-blue-50', iconColor: 'text-blue-600' },
    { label: 'Current (0–30d)', value: safeNumber(arData?.current_0_30), icon: Clock, iconBg: 'bg-green-50', iconColor: 'text-green-600' },
    { label: '31–60 Days', value: safeNumber(arData?.ar_31_60), icon: Receipt, iconBg: 'bg-yellow-50', iconColor: 'text-yellow-600' },
    { label: '90+ Days', value: safeNumber(arData?.ar_90_plus), icon: AlertTriangle, iconBg: 'bg-red-50', iconColor: 'text-red-600' },
  ];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Patient Billing</h1>
        <p className="mt-1 text-sm text-gray-500">Patient accounts receivable and statement management</p>
      </div>

      {arLoading ? (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {statCards.map(({ label, value, icon: Icon, iconBg, iconColor }) => (
            <div key={label} className="rounded-xl border border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <div className={`rounded-lg ${iconBg} p-2`}>
                  <Icon className={`h-4 w-4 ${iconColor}`} />
                </div>
                <div>
                  <p className="text-xs text-gray-500">{label}</p>
                  <p className="text-xl font-semibold text-gray-900">{fmtCurrency(value)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mb-4 flex items-center gap-1 rounded-lg bg-gray-100 p-1 w-fit">
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

      {stmtLoading ? (
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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Statement #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Due Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Billed</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Paid</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Balance Due</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {stmts.items.map((stmt) => (
                <tr key={stmt.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{stmt.patient_name ?? `ID: ${stmt.patient_id?.slice(0,8) ?? '—'}`}</td>
                  <td className="px-4 py-3 text-sm text-aethera-600 font-medium">{stmt.statement_number ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">{formatDate(stmt.statement_date)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 whitespace-nowrap">{formatDate(stmt.due_date)}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{fmtCurrency(stmt.amount_billed ?? stmt.total_charges)}</td>
                  <td className="px-4 py-3 text-sm text-emerald-600">{fmtCurrency(stmt.amount_paid ?? stmt.total_patient_paid)}</td>
                  <td className="px-4 py-3 text-sm font-semibold text-gray-900">{fmtCurrency(stmt.balance_due)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${statusBadge(stmt.status ?? '')}`}>
                      {stmt.status ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {stmt.status !== 'paid' && (
                      <button
                        onClick={() => { setPayTarget(stmt); setPayForm({ amount: String(safeNumber(stmt.balance_due)), reference: '' }); }}
                        className="rounded px-2 py-1 text-xs font-medium text-aethera-600 hover:bg-aethera-50"
                      >
                        Post Payment
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {stmts.items.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-500">
                    <Receipt className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No statements found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {payTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Post Payment</h2>
              <button onClick={() => setPayTarget(null)} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X className="h-4 w-4 text-gray-500" />
              </button>
            </div>
            <p className="mb-4 text-sm text-gray-600">
              Statement <span className="font-semibold">{payTarget.statement_number}</span>{' '}
              — Balance due: <span className="font-semibold text-gray-900">{fmtCurrency(payTarget.balance_due)}</span>
            </p>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Payment Amount ($)</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={payForm.amount}
                  onChange={(e) => setPayForm((f) => ({ ...f, amount: e.target.value }))}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">Reference Number</label>
                <input
                  type="text"
                  value={payForm.reference}
                  onChange={(e) => setPayForm((f) => ({ ...f, reference: e.target.value }))}
                  placeholder="Check #, Transaction ID..."
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                />
              </div>
              {postPayment.isError && <p className="text-xs text-red-600">Error posting payment. Please try again.</p>}
              <div className="flex justify-end gap-3 pt-2">
                <button onClick={() => setPayTarget(null)} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">Cancel</button>
                <button
                  disabled={postPayment.isPending || !payForm.amount}
                  className="rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 disabled:opacity-50"
                >
                  {postPayment.isPending ? 'Posting...' : 'Post Payment'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
