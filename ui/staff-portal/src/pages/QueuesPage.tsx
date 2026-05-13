import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ListTodo, Filter, UserPlus, CheckCircle2 } from 'lucide-react';
import api from '../lib/api';

interface QueueItem {
  id: string;
  item_type: string;
  priority: number;
  priority_label: string;
  status: string;
  practice_name: string;
  patient_name: string | null;
  claim_id: string | null;
  assigned_to: string | null;
  assigned_to_name: string | null;
  created_at: string;
  due_date: string | null;
}

interface QueueResponse {
  items: QueueItem[];
  total: number;
  page: number;
  page_size: number;
}

const PRIORITIES = ['all', 'critical', 'high', 'medium', 'low'] as const;
const STATUSES = ['all', 'pending', 'in_progress', 'completed', 'escalated'] as const;

export function QueuesPage() {
  const queryClient = useQueryClient();
  const [priority, setPriority] = useState<string>('all');
  const [status, setStatus] = useState<string>('all');
  const [page, setPage] = useState(1);

  const { data, isLoading } = useQuery<QueueResponse>({
    queryKey: ['queue-items', priority, status, page],
    queryFn: () =>
      api
        .get('/queues/my-queue', {
          params: { priority: priority !== 'all' ? priority : undefined, status: status !== 'all' ? status : undefined, page, page_size: 20, include_unassigned: true },
        })
        .then((r) => r.data),
  });

  const claimMutation = useMutation({
    mutationFn: (itemId: string) => api.post(`/queues/${itemId}/claim`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['queue-items'] }),
  });

  const completeMutation = useMutation({
    mutationFn: (itemId: string) => api.post(`/queues/${itemId}/complete`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['queue-items'] }),
  });

  const priorityBadge = (p: string) => {
    const colors: Record<string, string> = {
      critical: 'bg-red-100 text-red-700',
      high: 'bg-orange-100 text-orange-700',
      medium: 'bg-yellow-100 text-yellow-700',
      low: 'bg-gray-100 text-gray-700',
    };
    return colors[p] || 'bg-gray-100 text-gray-700';
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Work Queue</h1>
          <p className="mt-1 text-sm text-gray-500">{data?.total ?? 0} items</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-gray-400" />
            <select
              value={priority}
              onChange={(e) => { setPriority(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm"
            >
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{p === 'all' ? 'All Priorities' : p}</option>
              ))}
            </select>
            <select
              value={status}
              onChange={(e) => { setStatus(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>{s === 'all' ? 'All Statuses' : s}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

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
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Type</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Patient</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Practice</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Priority</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">SLA</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data?.items.map((item) => (
                <tr key={item.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">{item.item_type}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.patient_name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.practice_name}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${priorityBadge(item.priority_label)}`}>
                      {item.priority_label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.status.replace('_', ' ')}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{item.due_date ? new Date(item.due_date).toLocaleDateString() : '—'}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {!item.assigned_to && item.status === 'pending' && (
                        <button
                          onClick={() => claimMutation.mutate(item.id)}
                          className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-100"
                        >
                          <UserPlus className="h-3 w-3" /> Claim
                        </button>
                      )}
                      {item.assigned_to && item.status === 'in_progress' && (
                        <button
                          onClick={() => completeMutation.mutate(item.id)}
                          className="inline-flex items-center gap-1 rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700 hover:bg-green-100"
                        >
                          <CheckCircle2 className="h-3 w-3" /> Complete
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {(!data?.items.length) && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-500">
                    <ListTodo className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No items in queue
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > 20 && (
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