import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Receipt, Download } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber } from '../lib/apiHelpers';

interface Invoice {
  id: string;
  invoice_number: string;
  period_start: string;
  period_end: string;
  amount: number;
  status: string;
  due_date: string;
  created_at: string;
}

export function InvoicesPage() {
  const [page, setPage] = useState(1);

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['provider-invoices', page],
    queryFn: () =>
      api
        .get('/portal/invoices', { params: { page, page_size: 20 } })
        .then((r) => r.data),
  });

  const data = normalizeListResponse<Invoice>(rawData);

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      draft: 'bg-gray-100 text-gray-700',
      sent: 'bg-blue-100 text-blue-700',
      paid: 'bg-green-100 text-green-700',
      overdue: 'bg-red-100 text-red-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  const fmtAmount = (v: number) =>
    '$' + safeNumber(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Invoices</h1>
        <p className="mt-1 text-sm text-gray-500">View and download your billing invoices</p>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <table className="w-full">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Invoice #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Period</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Amount</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Due Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.items.map((inv) => (
                <tr key={inv.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-brand-600">{inv.invoice_number ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{inv.period_start ?? '—'} — {inv.period_end ?? '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{fmtAmount(inv.amount)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(inv.status ?? '')}`}>
                      {inv.status ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{inv.due_date ?? '—'}</td>
                  <td className="px-4 py-3">
                    <button className="inline-flex items-center gap-1 rounded-md text-sm text-brand-600 hover:text-brand-700">
                      <Download className="h-3.5 w-3.5" />
                      PDF
                    </button>
                  </td>
                </tr>
              ))}
              {data.items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                    <Receipt className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No invoices found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data.total > 20 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-gray-500">
            Showing {(page - 1) * 20 + 1}–{Math.min(page * 20, data.total)} of {data.total}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              Previous
            </button>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 20 >= data.total}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
