import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CreditCard, Upload, Search } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse, safeNumber, formatDate } from '../lib/apiHelpers';

interface PaymentBatch {
  id: string;
  batch_id: string;
  payer_name: string;
  total_amount: number;
  check_number: string | null;
  status: string;
  created_at: string;
  processed_at: string | null;
  claim_count: number;
}

export function PaymentsPage() {
  const queryClient = useQueryClient();
  const [search, setSearch] = useState('');

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['payment-batches'],
    queryFn: () =>
      api
        .get('/payments/batches', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const data = normalizeListResponse<PaymentBatch>(rawData);

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      return api.post('/payments/era/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['payment-batches'] }),
  });

  const fmtCurrency = (v: number) =>
    '$' + safeNumber(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-700',
      processing: 'bg-blue-100 text-blue-700',
      posted: 'bg-green-100 text-green-700',
      error: 'bg-red-100 text-red-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  const filtered = data.items.filter(
    (b) => !search || (b.payer_name ?? '').toLowerCase().includes(search.toLowerCase()) || (b.batch_id ?? '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Payment Posting</h1>
          <p className="mt-1 text-sm text-gray-500">ERA batches and payment reconciliation</p>
        </div>
        <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 transition-colors">
          <Upload className="h-4 w-4" />
          Upload ERA
          <input
            type="file"
            accept=".835,.txt,.csv"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadMutation.mutate(file);
            }}
          />
        </label>
      </div>

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search batches..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      {uploadMutation.isError && (
        <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">
          Upload failed. Please check the file format and try again.
        </div>
      )}
      {uploadMutation.isSuccess && (
        <div className="mb-4 rounded-lg bg-green-50 p-3 text-sm text-green-700">
          ERA file uploaded and processing.
        </div>
      )}

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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Batch ID</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Payer</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Amount</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Claims</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Check #</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((batch) => (
                <tr key={batch.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-brand-600">{batch.batch_id ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{batch.payer_name ?? '—'}</td>
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{fmtCurrency(batch.total_amount)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{safeNumber(batch.claim_count)}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{batch.check_number ?? '—'}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(batch.status)}`}>
                      {batch.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatDate(batch.created_at)}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    <CreditCard className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No payment batches found
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
