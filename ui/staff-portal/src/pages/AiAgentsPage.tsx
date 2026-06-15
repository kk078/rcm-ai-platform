import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Activity, AlertTriangle, CheckCircle2, CircleDot, XCircle, MinusCircle, Bot } from 'lucide-react';
import api from '../lib/api';

interface AgentHealth {
  agent_type: string; processed: number; completed: number; escalated: number; failed: number;
  auto_rate: number; escalation_rate: number; avg_confidence: number | null;
  avg_duration_ms: number | null; error_codes: Record<string, number>;
}
interface HealthResp { totals: Record<string, number>; agents: AgentHealth[] }
interface AttnItem { id: string; queue_type: string; status: string; priority: number; sla_breached: boolean; agent_type: string | null; confidence: number | null; reason: string | null }
interface TraceStep { seq: number; label: string; status: string; detail: string }
interface Detail { id: string; queue_type: string; status: string; agent_type: string | null; confidence: number | null; message: string | null; agent_trace: TraceStep[] }

const stepIcon: Record<string, JSX.Element> = {
  done: <CheckCircle2 className="h-4 w-4 text-green-600" />,
  warning: <AlertTriangle className="h-4 w-4 text-yellow-500" />,
  error: <XCircle className="h-4 w-4 text-red-500" />,
  skipped: <MinusCircle className="h-4 w-4 text-gray-400" />,
};

export function AiAgentsPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openItem, setOpenItem] = useState<string | null>(null);

  const health = useQuery<HealthResp>({ queryKey: ['agent-health'], queryFn: () => api.get('/admin/agent-health').then((r) => r.data) });
  const attn = useQuery<{ total: number; items: AttnItem[] }>({ queryKey: ['needs-attention'], queryFn: () => api.get('/queues/needs-attention').then((r) => r.data) });
  const detail = useQuery<Detail>({ queryKey: ['wq-detail', openItem], queryFn: () => api.get(`/queues/queue/${openItem}/detail`).then((r) => r.data), enabled: !!openItem });

  const bulk = useMutation({
    mutationFn: () => api.post('/queues/queue/bulk-complete', { item_ids: Array.from(selected) }).then((r) => r.data),
    onSuccess: () => { setSelected(new Set()); qc.invalidateQueries({ queryKey: ['needs-attention'] }); qc.invalidateQueries({ queryKey: ['agent-health'] }); },
  });

  function toggle(id: string) {
    const s = new Set(selected); s.has(id) ? s.delete(id) : s.add(id); setSelected(s);
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-3">
        <Bot className="h-6 w-6 text-brand-600" />
        <h1 className="text-2xl font-bold text-gray-900">AI Agents</h1>
        <span className="text-sm text-gray-500">monitoring · transparency · review</span>
      </div>

      {/* Agent health (roadmap C) */}
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-700"><Activity className="h-4 w-4" /> Agent health (last 30 days)</h2>
      {health.isLoading ? <div className="mb-6 h-28 animate-pulse rounded-lg bg-gray-200" /> : (
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(health.data?.agents ?? []).length === 0 && (
            <div className="col-span-full rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500">
              No processed work items yet. Agent metrics appear here as the pipeline runs.
            </div>
          )}
          {(health.data?.agents ?? []).map((a) => (
            <div key={a.agent_type} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-semibold capitalize text-gray-900">{a.agent_type.replace('_', ' ')}</span>
                <span className="text-xs text-gray-400">{a.processed} processed</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div><div className="text-lg font-bold text-green-600">{Math.round(a.auto_rate * 100)}%</div><div className="text-gray-500">auto</div></div>
                <div><div className="text-lg font-bold text-yellow-600">{Math.round(a.escalation_rate * 100)}%</div><div className="text-gray-500">escalated</div></div>
                <div><div className="text-lg font-bold text-blue-600">{a.avg_confidence != null ? a.avg_confidence.toFixed(2) : '—'}</div><div className="text-gray-500">avg conf</div></div>
              </div>
              {Object.keys(a.error_codes || {}).length > 0 && (
                <div className="mt-2 text-xs text-red-600">errors: {Object.entries(a.error_codes).map(([k, v]) => `${k}×${v}`).join(', ')}</div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Needs attention (roadmap D) */}
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-700"><AlertTriangle className="h-4 w-4" /> Needs attention ({attn.data?.total ?? 0})</h2>
        <button onClick={() => bulk.mutate()} disabled={selected.size === 0 || bulk.isPending}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-40">
          {bulk.isPending ? 'Approving…' : `Approve selected (${selected.size})`}
        </button>
      </div>
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        {(attn.data?.items ?? []).length === 0 ? (
          <div className="p-6 text-center text-sm text-gray-500">Nothing needs a human right now — high-confidence items auto-completed.</div>
        ) : (
          <table className="w-full text-sm">
            <thead><tr className="border-b border-gray-100 text-left text-xs text-gray-500">
              <th className="p-2 w-8"></th><th className="p-2">Agent</th><th className="p-2">Queue</th><th className="p-2">Status</th><th className="p-2">Conf.</th><th className="p-2">Reason</th><th className="p-2">Trace</th>
            </tr></thead>
            <tbody>
              {attn.data!.items.map((it) => (
                <tr key={it.id} className="border-b border-gray-50">
                  <td className="p-2"><input type="checkbox" checked={selected.has(it.id)} onChange={() => toggle(it.id)} /></td>
                  <td className="p-2 capitalize">{it.agent_type ?? '—'}</td>
                  <td className="p-2">{it.queue_type}</td>
                  <td className="p-2"><span className={`rounded-full px-2 py-0.5 text-xs ${it.status === 'escalated' ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'}`}>{it.status}</span></td>
                  <td className="p-2">{it.confidence != null ? Number(it.confidence).toFixed(2) : '—'}</td>
                  <td className="p-2 max-w-xs truncate text-gray-600" title={it.reason ?? ''}>{it.reason ?? '—'}</td>
                  <td className="p-2"><button onClick={() => setOpenItem(it.id)} className="text-brand-600 hover:underline">view</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Trace drawer (roadmap A) */}
      {openItem && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={() => setOpenItem(null)}>
          <div className="h-full w-full max-w-md overflow-y-auto bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h3 className="font-semibold text-gray-900">Agent reasoning trace</h3>
              <button onClick={() => setOpenItem(null)} className="text-gray-400 hover:text-gray-700">✕</button>
            </div>
            {detail.isLoading ? <div className="h-40 animate-pulse rounded bg-gray-200" /> : (
              <>
                <div className="mb-4 rounded-lg bg-gray-50 p-3 text-sm">
                  <div><span className="text-gray-500">Agent:</span> <span className="capitalize font-medium">{detail.data?.agent_type ?? '—'}</span></div>
                  <div><span className="text-gray-500">Status:</span> {detail.data?.status} · <span className="text-gray-500">confidence:</span> {detail.data?.confidence ?? '—'}</div>
                </div>
                <ol className="relative border-l border-gray-200 pl-5">
                  {(detail.data?.agent_trace ?? []).map((s) => (
                    <li key={s.seq} className="mb-4">
                      <span className="absolute -left-2.5 mt-0.5 rounded-full bg-white">{stepIcon[s.status] ?? <CircleDot className="h-4 w-4 text-gray-400" />}</span>
                      <p className="text-sm font-medium text-gray-900">{s.label}</p>
                      {s.detail && <p className="text-xs text-gray-500">{s.detail}</p>}
                    </li>
                  ))}
                  {(detail.data?.agent_trace ?? []).length === 0 && <li className="text-sm text-gray-500">No trace recorded for this item.</li>}
                </ol>
                {detail.data?.message && <div className="mt-4 rounded-lg bg-blue-50 p-3 text-xs text-blue-800">{detail.data.message}</div>}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
