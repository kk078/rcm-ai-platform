import { useEffect, useState } from 'react';
import api from '../lib/api';
import { useAuth } from '../hooks/useAuth';

interface StaffUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  full_name: string;
  internal_role: string | null;
  is_active: boolean;
  mfa_enabled: boolean;
  agent_areas: string[];
  last_login: string | null;
  created_at: string;
}

const ROLES = [
  'company_admin', 'billing_specialist', 'coder',
  'ar_specialist', 'payment_poster', 'denial_manager', 'viewer',
];

const ROLE_LABEL: Record<string, string> = {
  company_admin: 'Super Admin (company_admin)',
  billing_specialist: 'Billing Specialist',
  coder: 'Coder',
  ar_specialist: 'AR / Denials Specialist',
  payment_poster: 'Payment Poster',
  denial_manager: 'Denial Manager',
  viewer: 'Viewer (read-only)',
};

export function UsersPage() {
  const { user } = useAuth();
  const isSuper = user?.internal_role === 'company_admin';

  const [users, setUsers] = useState<StaffUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ email: '', first_name: '', last_name: '', internal_role: 'coder', password: '' });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    setLoading(true); setError(null);
    try {
      const { data } = await api.get('/users');
      setUsers(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to load users.');
    } finally { setLoading(false); }
  }
  useEffect(() => { if (isSuper) load(); else setLoading(false); }, [isSuper]);

  async function createUser() {
    setBusy(true); setNotice(null); setError(null);
    try {
      await api.post('/users', form);
      setShowCreate(false);
      setForm({ email: '', first_name: '', last_name: '', internal_role: 'coder', password: '' });
      setNotice('User created.');
      await load();
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Failed to create user.');
    } finally { setBusy(false); }
  }

  async function setRole(u: StaffUser, role: string) {
    try { await api.patch(`/users/${u.id}`, { internal_role: role }); await load(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Update failed.'); }
  }
  async function toggleActive(u: StaffUser) {
    try { await api.patch(`/users/${u.id}`, { is_active: !u.is_active }); await load(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Update failed.'); }
  }
  async function resetPassword(u: StaffUser) {
    const np = prompt(`New temporary password for ${u.email} (min 10 chars, upper/lower/digit):`);
    if (!np) return;
    try { await api.post(`/users/${u.id}/reset-password`, { new_password: np }); setNotice('Password reset.'); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Reset failed.'); }
  }

  if (!isSuper) {
    return (
      <div className="p-8">
        <h1 className="text-xl font-semibold text-gray-900">User Management</h1>
        <p className="mt-3 rounded-md bg-amber-50 p-4 text-sm text-amber-800">
          User management is available to super admins only.
        </p>
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">User Management</h1>
          <p className="text-sm text-gray-500">Create staff, assign their agent areas (by role), and control access.</p>
        </div>
        <button onClick={() => setShowCreate((s) => !s)}
          className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">
          {showCreate ? 'Cancel' : '+ New user'}
        </button>
      </div>

      {notice && <div className="mb-3 rounded-md bg-green-50 p-3 text-sm text-green-700">{notice}</div>}
      {error && <div className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {showCreate && (
        <div className="mb-5 grid grid-cols-1 gap-3 rounded-lg border border-gray-200 bg-white p-4 md:grid-cols-2">
          <input className="rounded-md border px-3 py-2 text-sm" placeholder="Email"
            value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <select className="rounded-md border px-3 py-2 text-sm"
            value={form.internal_role} onChange={(e) => setForm({ ...form, internal_role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <input className="rounded-md border px-3 py-2 text-sm" placeholder="First name"
            value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          <input className="rounded-md border px-3 py-2 text-sm" placeholder="Last name"
            value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          <input className="rounded-md border px-3 py-2 text-sm" type="password" placeholder="Temp password (10+ chars)"
            value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          <button disabled={busy} onClick={createUser}
            className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50">
            {busy ? 'Creating…' : 'Create user'}
          </button>
        </div>
      )}

      {loading ? <p className="text-sm text-gray-500">Loading…</p> : (
        <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase text-gray-500">
              <tr>
                <th className="px-4 py-2">User</th><th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Agent areas</th><th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-2">
                    <div className="font-medium text-gray-900">{u.full_name || u.email}</div>
                    <div className="text-xs text-gray-500">{u.email}</div>
                  </td>
                  <td className="px-4 py-2">
                    <select value={u.internal_role || ''} onChange={(e) => setRole(u, e.target.value)}
                      className="rounded border px-2 py-1 text-xs">
                      {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                    </select>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {(u.agent_areas || []).length === 0 && <span className="text-xs text-gray-400">—</span>}
                      {(u.agent_areas || []).map((a) => (
                        <span key={a} className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">{a}</span>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs ${u.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600'}`}>
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-2 text-xs">
                      <button onClick={() => toggleActive(u)} className="text-blue-600 hover:underline">
                        {u.is_active ? 'Deactivate' : 'Activate'}
                      </button>
                      <button onClick={() => resetPassword(u)} className="text-gray-600 hover:underline">Reset PW</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
