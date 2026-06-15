import { useQuery } from '@tanstack/react-query';
import { Receipt, DollarSign, TrendingUp, AlertTriangle } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber, formatDate } from '../lib/apiHelpers';

interface RevenueDashboard {
  period: string;
  total_invoiced: number;
  total_collected: number;
  total_outstanding: number;
  total_overdue: number;
  client_count: number;
  avg_revenue_per_client: number;
  revenue_by_fee_model: Record<string, number>;
  top_clients: { practice_name: string; revenue: number }[];
}

interface Invoice {
  id: string;
  invoice_number: string;
  practice_name: string;
  total_due: number;
  status: string;
  due_date: string;
  created_at: string;
}

export function BillingPage() {
  const { data: dashboard, isLoading: dashLoading } = useQuery<RevenueDashboard>({
    queryKey: ['revenue-dashboard'],
    queryFn: () => api.get('/billing/revenue/dashboard').then((r) => r.data),
  });

  const { data: rawInvoices, isLoading: invLoading } = useQuery({
    queryKey: ['invoices'],
    queryFn: () => api.get('/billing/invoices', { params: { page_size: 10 } }).then((r) => r.data),
  });

  const invoicesData = normalizeListResponse<Invoice>(rawInvoices);
  const invoices = invoicesData.items;

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      draft: 'bg-gray-100 text-gray-700',
      sent: 'bg-blue-100 text-blue-700',
      paid: 'bg-green-100 text-green-700',
      overdue: 'bg-red-100 text-red-700',
      void: 'bg-gray-200 text-gray-500',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Billing & Invoicing</h1>
        <p className="mt-1 text-sm text-gray-500">Client revenue and invoice management</p>
      </div>

      {dashLoading ? (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-4 gap-4 mb-6">
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-emerald-50 p-2">
                <DollarSign className="h-4 w-4 text-emerald-600" />
              </div>
              <div>
                <p className="text-xs text-gray-500">Total Revenue</p>
                <p className="text-xl font-semibold text-gray-900">${safeNumber(dashboard?.total_invoiced).toLocaleString()}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-50 p-2">
                <TrendingUp className="h-4 w-4 text-blue-600" />
              </div>
              <div>
                <p className="text-xs text-gray-500">Collected This Month</p>
                <p className="text-xl font-semibold text-gray-900">${safeNumber(dashboard?.total_collected).toLocaleString()}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-amber-50 p-2">
                <Receipt className="h-4 w-4 text-amber-600" />
              </div>
              <div>
                <p className="text-xs text-gray-500">Outstanding</p>
                <p className="text-xl font-semibold text-gray-900">${safeNumber(dashboard?.total_outstanding).toLocaleString()}</p>
              </div>
            </div>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-red-50 p-2">
                <AlertTriangle className="h-4 w-4 text-red-600" />
              </div>
              <div>
                <p className="text-xs text-gray-500">Overdue</p>
                <p className="text-xl font-semibold text-gray-900">${safeNumber(dashboard?.total_overdue).toLocaleString()}</p>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mb-4">
        <h2 className="text-lg font-semibold text-gray-900">Recent Invoices</h2>
      </div>

      {invLoading ? (
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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Invoice #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Client</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Amount</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Due Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {invoices.map((inv) => (
                <tr key={inv.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-brand-600">{inv.invoice_number ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{inv.practice_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">${safeNumber(inv.total_due).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(inv.status ?? '')}`}>
                      {inv.status ?? '—'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatDate(inv.due_date)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatDate(inv.created_at)}</td>
                </tr>
              ))}
              {invoices.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                    No invoices found
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
