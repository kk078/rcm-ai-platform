import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Building2, Search, Pencil, Trash2, Loader2, X } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse } from '../lib/apiHelpers';

interface Practice {
  id: string;
  practice_name: string;
  legal_name: string | null;
  group_npi: string | null;
  specialty_primary: string | null;
  status: string;
  intake_method: string;
  go_live_date: string | null;
  provider_count: number | null;
  active_claims_count: number | null;
}

type EditForm = {
  practice_name: string; legal_name: string; specialty_primary: string; group_npi: string;
  contact_name: string; contact_email: string; phone: string; email: string;
  address_line_1: string; city: string; state: string; zip_code: string; notes: string;
};

export function ClientsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Practice | null>(null);
  const [form, setForm] = useState<EditForm | null>(null);
  const [banner, setBanner] = useState('');

  const { data: rawData, isLoading } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.get('/clients/practices').then((r) => r.data),
  });
  const data = normalizeListResponse<Practice>(rawData);
  const items = data.items;
  const filtered = items.filter((c) => !search || (c.practice_name ?? '').toLowerCase().includes(search.toLowerCase()));

  function openEdit(p: Practice) {
    setEditing(p);
    setForm({
      practice_name: p.practice_name ?? '', legal_name: p.legal_name ?? '',
      specialty_primary: p.specialty_primary ?? '', group_npi: p.group_npi ?? '',
      contact_name: '', contact_email: '', phone: '', email: '',
      address_line_1: '', city: '', state: '', zip_code: '', notes: '',
    });
  }

  const updateMut = useMutation({
    mutationFn: async () => {
      if (!editing || !form) return;
      const body: Record<string, string> = {};
      Object.entries(form).forEach(([k, v]) => { if (v && v.trim()) body[k] = v.trim(); });
      return api.patch(`/clients/practices/${editing.id}`, body).then((r) => r.data);
    },
    onSuccess: () => { setEditing(null); setForm(null); setBanner('Client updated.'); qc.invalidateQueries({ queryKey: ['clients'] }); },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => api.delete(`/clients/practices/${id}`).then((r) => r.data),
    onSuccess: (res: any) => { setBanner(res?.message || (res?.status === 'deleted' ? 'Client deleted.' : 'Client deactivated.')); qc.invalidateQueries({ queryKey: ['clients'] }); },
    onError: (e: any) => setBanner(e?.response?.data?.detail || 'Delete failed.'),
  });

  function confirmDelete(p: Practice) {
    if (window.confirm(`Delete "${p.practice_name}"? If it has billing data it will be deactivated (records kept); an empty client is permanently removed.`)) {
      deleteMut.mutate(p.id);
    }
  }

  const inp = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-brand-500';
  const lbl = 'block text-xs font-medium text-gray-600 mb-1';

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Client Management</h1>
        <p className="mt-1 text-sm text-gray-500">{filtered.length} practices</p>
      </div>

      {banner && <div className="mb-4 flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-2 text-sm text-blue-800"><span>{banner}</span><button onClick={() => setBanner('')}><X className="h-4 w-4" /></button></div>}

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input type="text" placeholder="Search clients..." value={search} onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500" />
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-3 gap-4">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-32 animate-pulse rounded-xl bg-gray-200" />)}</div>
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((practice) => (
            <div key={practice.id} className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-shadow">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 rounded-lg bg-brand-50 flex items-center justify-center"><Building2 className="h-5 w-5 text-brand-600" /></div>
                  <div>
                    <h3 className="font-medium text-gray-900">{practice.practice_name}</h3>
                    <p className="text-xs text-gray-500">{practice.specialty_primary || 'N/A'}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button onClick={() => openEdit(practice)} title="Edit" className="text-gray-400 hover:text-brand-600 p-1"><Pencil className="h-4 w-4" /></button>
                  <button onClick={() => confirmDelete(practice)} title="Delete" className="text-gray-400 hover:text-red-500 p-1"><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div><p className="text-gray-500">NPI</p><p className="font-medium text-gray-900">{practice.group_npi || 'N/A'}</p></div>
                <div><p className="text-gray-500">Status</p><span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${practice.status === 'active' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'}`}>{practice.status}</span></div>
                <div><p className="text-gray-500">Go-Live</p><p className="text-gray-900">{practice.go_live_date || 'TBD'}</p></div>
                <div><p className="text-gray-500">Intake</p><p className="text-gray-900">{practice.intake_method}</p></div>
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="col-span-3 py-12 text-center text-sm text-gray-500"><Building2 className="mx-auto mb-2 h-8 w-8 text-gray-300" />No clients found</div>
          )}
        </div>
      )}

      {/* Edit modal */}
      {editing && form && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => { setEditing(null); setForm(null); }}>
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-gray-900">Edit {editing.practice_name}</h2>
              <button onClick={() => { setEditing(null); setForm(null); }} className="text-gray-400 hover:text-gray-600"><X className="h-5 w-5" /></button>
            </div>
            <p className="text-xs text-gray-400 mb-4">Pre-filled fields show current values. Contact/address fields are blank — fill any you want to set (blank ones are left unchanged). TIN and billing guidelines are edited elsewhere.</p>
            <div className="grid grid-cols-2 gap-4">
              {([
                ['practice_name', 'Practice name'], ['legal_name', 'Legal name'],
                ['specialty_primary', 'Primary specialty'], ['group_npi', 'Group NPI'],
                ['contact_name', 'Contact name'], ['contact_email', 'Contact email'],
                ['phone', 'Phone'], ['email', 'Email'],
                ['address_line_1', 'Address'], ['city', 'City'],
                ['state', 'State'], ['zip_code', 'ZIP'], ['notes', 'Notes'],
              ] as [keyof EditForm, string][]).map(([k, label]) => (
                <div key={k} className={k === 'notes' || k === 'address_line_1' ? 'col-span-2' : ''}>
                  <label className={lbl}>{label}</label>
                  <input className={inp} value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                </div>
              ))}
            </div>
            {updateMut.isError && <div className="mt-3 text-sm text-red-600">{(updateMut.error as any)?.response?.data?.detail || 'Update failed.'}</div>}
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => { setEditing(null); setForm(null); }} className="rounded-lg px-4 py-2 text-sm text-gray-600 hover:bg-gray-100">Cancel</button>
              <button onClick={() => updateMut.mutate()} disabled={updateMut.isPending} className="rounded-lg bg-brand-600 hover:bg-brand-700 disabled:bg-brand-300 px-4 py-2 text-sm font-medium text-white flex items-center gap-2">
                {updateMut.isPending && <Loader2 className="h-4 w-4 animate-spin" />} Save changes
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
