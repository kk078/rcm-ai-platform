import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plug, RefreshCw, X, CheckCircle2, AlertTriangle, Clock } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse } from '../lib/apiHelpers';

interface EHRConnection {
  id: string;
  ehr_type: string;
  status: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
  last_sync_count: number | null;
  base_url?: string;
  sftp_host?: string;
  webhook_secret?: string;
}

interface SyncLog {
  id: string;
  sync_type: string;
  trigger: string;
  fetched_count: number;
  created_count: number;
  updated_count: number;
  error_count: number;
  status: string;
  started_at: string;
}

const EHR_TYPES = ['FHIR R4', 'SFTP/CSV', 'Webhook', 'Athena', 'Kareo'];

const emptyFhir = { base_url: '', client_id: '', client_secret: '', scopes: [] as string[] };
const emptySftp = { host: '', port: '22', username: '', password: '', path: '' };
const emptyWebhook = { webhook_secret: '' };

export function EHRConnectionsPage() {
  const qc = useQueryClient();
  const [showModal, setShowModal] = useState(false);
  const [ehrType, setEhrType] = useState('FHIR R4');
  const [fhirForm, setFhirForm] = useState(emptyFhir);
  const [sftpForm, setSftpForm] = useState(emptySftp);
  const [webhookForm, setWebhookForm] = useState(emptyWebhook);

  const { data: connection, isLoading: connLoading } = useQuery<EHRConnection | null>({
    queryKey: ['ehr-connection'],
    queryFn: () => api.get('/ehr/connections').then((r) => r.data).catch(() => null),
  });

  const { data: rawLogs, isLoading: logsLoading } = useQuery({
    queryKey: ['ehr-sync-log'],
    queryFn: () => api.get('/ehr/connections/sync-log').then((r) => r.data),
  });
  const logs = normalizeListResponse<SyncLog>(rawLogs);

  const createConn = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      api.post('/ehr/connections', payload).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ehr-connection'] }); setShowModal(false); },
  });

  const syncNow = useMutation({
    mutationFn: () => api.post('/ehr/connections/sync').then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ehr-connection'] }); qc.invalidateQueries({ queryKey: ['ehr-sync-log'] }); },
  });

  function buildPayload() {
    const base = { ehr_type: ehrType };
    if (ehrType === 'FHIR R4') return { ...base, ...fhirForm };
    if (ehrType === 'SFTP/CSV') return { ...base, ...sftpForm };
    return { ...base, ...webhookForm };
  }

  const webhookUrl = `${window.location.origin}/api/v1/ehr/webhooks/patient`;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">EHR / PMS Integration</h1>
          <p className="mt-1 text-sm text-gray-500">Connect your Electronic Health Record or Practice Management System</p>
        </div>
        {!connection && !connLoading && (
          <button
            onClick={() => setShowModal(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 transition-colors"
          >
            <Plug className="h-4 w-4" /> Setup Integration
          </button>
        )}
      </div>

      {/* Current Connection Card */}
      {connLoading ? (
        <div className="h-36 animate-pulse rounded-xl bg-gray-200 mb-6" />
      ) : connection ? (
        <div className="mb-6 rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-aethera-600/10">
                <Plug className="h-5 w-5 text-aethera-600" />
              </div>
              <div>
                <p className="font-semibold text-gray-900">{connection.ehr_type}</p>
                <p className="text-xs text-gray-500">{connection.base_url ?? connection.sftp_host ?? 'Configured'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${connection.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}`}>
                {connection.status === 'active' ? 'Active' : 'Inactive'}
              </span>
              {connection.ehr_type === 'FHIR R4' && (
                <button
                  onClick={() => syncNow.mutate()}
                  disabled={syncNow.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${syncNow.isPending ? 'animate-spin' : ''}`} />
                  {syncNow.isPending ? 'Syncing...' : 'Sync Now'}
                </button>
              )}
            </div>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-4 pt-4 border-t border-gray-100">
            <div>
              <p className="text-xs text-gray-500">Last Sync</p>
              <p className="text-sm font-medium text-gray-900">{connection.last_sync_at ? new Date(connection.last_sync_at).toLocaleString() : 'Never'}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Last Sync Status</p>
              <p className={`text-sm font-medium capitalize ${connection.last_sync_status === 'success' ? 'text-green-600' : 'text-red-600'}`}>
                {connection.last_sync_status ?? '—'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Records Last Sync</p>
              <p className="text-sm font-medium text-gray-900">{connection.last_sync_count ?? '—'}</p>
            </div>
          </div>
        </div>
      ) : (
        <div className="mb-6 rounded-xl border-2 border-dashed border-gray-200 bg-gray-50 p-8 text-center">
          <Plug className="mx-auto mb-3 h-10 w-10 text-gray-300" />
          <p className="font-semibold text-gray-700">No integration configured</p>
          <p className="mt-1 text-sm text-gray-500">Connect your EHR/PMS to automatically sync patient and encounter data.</p>
        </div>
      )}

      {/* Webhook Info Panel */}
      {connection?.ehr_type === 'Webhook' && (
        <div className="mb-6 rounded-xl border border-blue-200 bg-blue-50 p-5">
          <h3 className="mb-2 font-semibold text-blue-800">Webhook Configuration</h3>
          <p className="mb-3 text-sm text-blue-700">Configure your PMS to POST patient data to the following URL:</p>
          <div className="rounded-lg bg-white border border-blue-200 px-3 py-2 font-mono text-sm text-gray-800 break-all">{webhookUrl}</div>
          <p className="mt-2 text-xs text-blue-600">Required headers: <code className="bg-blue-100 px-1 rounded">X-Webhook-Secret: &lt;your secret&gt;</code></p>
        </div>
      )}

      {/* Sync History Table */}
      <div className="mb-3">
        <h2 className="text-lg font-semibold text-gray-900">Sync History</h2>
      </div>
      {logsLoading ? (
        <div className="space-y-3">{Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded-lg bg-gray-200" />)}</div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Type</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Trigger</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Fetched</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Created</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Updated</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Errors</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {logs.items.map((log) => (
                <tr key={log.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm text-gray-900 capitalize">{log.sync_type ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600 capitalize">{log.trigger ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-900">{log.fetched_count ?? 0}</td>
                  <td className="px-4 py-3 text-sm text-green-600">{log.created_count ?? 0}</td>
                  <td className="px-4 py-3 text-sm text-blue-600">{log.updated_count ?? 0}</td>
                  <td className="px-4 py-3 text-sm text-red-600">{log.error_count ?? 0}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${log.status === 'success' ? 'bg-green-100 text-green-700' : log.status === 'running' ? 'bg-blue-100 text-blue-700' : 'bg-red-100 text-red-700'}`}>
                      {log.status === 'success' ? <CheckCircle2 className="h-3 w-3" /> : log.status === 'running' ? <Clock className="h-3 w-3" /> : <AlertTriangle className="h-3 w-3" />}
                      {log.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600">{log.started_at ? new Date(log.started_at).toLocaleString() : '—'}</td>
                </tr>
              ))}
              {logs.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">No sync history yet</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Setup Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Setup EHR Integration</h2>
              <button onClick={() => setShowModal(false)} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X className="h-4 w-4 text-gray-500" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">EHR / Integration Type</label>
                <select
                  value={ehrType}
                  onChange={(e) => setEhrType(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                >
                  {EHR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>

              {/* FHIR R4 Fields */}
              {(ehrType === 'FHIR R4' || ehrType === 'Athena' || ehrType === 'Kareo') && (
                <>
                  {[
                    { key: 'base_url', label: 'Base URL', placeholder: 'https://fhir.example.com/r4' },
                    { key: 'client_id', label: 'Client ID', placeholder: 'Client ID' },
                    { key: 'client_secret', label: 'Client Secret', placeholder: 'Client Secret', type: 'password' },
                  ].map(({ key, label, placeholder, type }) => (
                    <div key={key}>
                      <label className="mb-1 block text-xs font-medium text-gray-700">{label}</label>
                      <input
                        type={type ?? 'text'}
                        value={fhirForm[key as keyof typeof fhirForm] as string}
                        onChange={(e) => setFhirForm((f) => ({ ...f, [key]: e.target.value }))}
                        placeholder={placeholder}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                      />
                    </div>
                  ))}
                  <div>
                    <label className="mb-2 block text-xs font-medium text-gray-700">Scopes</label>
                    <div className="flex flex-wrap gap-2">
                      {['patient/*.read', 'user/*.read', 'launch/patient', 'openid'].map((scope) => (
                        <label key={scope} className="flex items-center gap-1.5 text-xs text-gray-700 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={fhirForm.scopes.includes(scope)}
                            onChange={(e) =>
                              setFhirForm((f) => ({
                                ...f,
                                scopes: e.target.checked
                                  ? [...f.scopes, scope]
                                  : f.scopes.filter((s) => s !== scope),
                              }))
                            }
                            className="rounded border-gray-300 text-aethera-600"
                          />
                          <code className="bg-gray-100 px-1.5 py-0.5 rounded text-xs">{scope}</code>
                        </label>
                      ))}
                    </div>
                  </div>
                </>
              )}

              {/* SFTP/CSV Fields */}
              {ehrType === 'SFTP/CSV' && (
                <div className="grid grid-cols-2 gap-4">
                  {[
                    { key: 'host', label: 'SFTP Host', placeholder: 'sftp.example.com', span: 2 },
                    { key: 'port', label: 'Port', placeholder: '22', span: 1 },
                    { key: 'username', label: 'Username', placeholder: 'username', span: 1 },
                    { key: 'password', label: 'Password', placeholder: 'Password', span: 2, type: 'password' },
                    { key: 'path', label: 'Remote Path', placeholder: '/exports/patients/', span: 2 },
                  ].map(({ key, label, placeholder, span, type }) => (
                    <div key={key} className={span === 2 ? 'col-span-2' : ''}>
                      <label className="mb-1 block text-xs font-medium text-gray-700">{label}</label>
                      <input
                        type={type ?? 'text'}
                        value={sftpForm[key as keyof typeof sftpForm]}
                        onChange={(e) => setSftpForm((f) => ({ ...f, [key]: e.target.value }))}
                        placeholder={placeholder}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                      />
                    </div>
                  ))}
                </div>
              )}

              {/* Webhook Fields */}
              {ehrType === 'Webhook' && (
                <>
                  <div>
                    <label className="mb-1 block text-xs font-medium text-gray-700">Webhook Secret</label>
                    <input
                      type="text"
                      value={webhookForm.webhook_secret}
                      onChange={(e) => setWebhookForm({ webhook_secret: e.target.value })}
                      placeholder="Secret token for HMAC validation"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                    />
                  </div>
                  <div className="rounded-lg bg-blue-50 border border-blue-200 p-3">
                    <p className="text-xs font-medium text-blue-800 mb-1">Configure your PMS to POST to:</p>
                    <p className="font-mono text-xs text-blue-700 break-all">{webhookUrl}</p>
                  </div>
                </>
              )}

              {createConn.isError && <p className="text-xs text-red-600">Error saving configuration. Please try again.</p>}
              <div className="flex justify-end gap-3 pt-2">
                <button onClick={() => setShowModal(false)} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">Cancel</button>
                <button
                  onClick={() => createConn.mutate(buildPayload())}
                  disabled={createConn.isPending}
                  className="rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 disabled:opacity-50"
                >
                  {createConn.isPending ? 'Saving...' : 'Save Integration'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
