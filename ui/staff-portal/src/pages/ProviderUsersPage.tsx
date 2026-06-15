import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  UserPlus, Search, MoreVertical, Shield, Building2,
  KeyRound, PowerOff, Power, X, Eye, EyeOff, RefreshCw,
  CheckCircle2, XCircle, Clock, ChevronDown,
} from 'lucide-react';
import api from '../lib/api';

// ── Types ────────────────────────────────────────────────────────────────

interface Practice { id: string; practice_name: string; specialty_primary: string | null; status: string; }
interface ProviderUser {
  id: string; email: string; first_name: string; last_name: string; full_name: string;
  provider_role: string | null; practice_id: string | null; practice_name: string | null;
  is_active: boolean; must_change_password: boolean; last_login: string | null; created_at: string;
}

const ROLES: Record<string, { label: string; color: string; bg: string }> = {
  practice_admin:  { label: 'Practice Admin',  color: '#1d4ed8', bg: 'rgba(29,78,216,0.08)' },
  physician:       { label: 'Physician',        color: '#047857', bg: 'rgba(4,120,87,0.08)'  },
  office_manager:  { label: 'Office Manager',  color: '#92400e', bg: 'rgba(217,119,6,0.08)' },
  billing_contact: { label: 'Billing Contact', color: '#6b21a8', bg: 'rgba(107,33,168,0.08)'},
  read_only:       { label: 'Read Only',       color: '#374151', bg: 'rgba(55,65,81,0.08)'  },
};

function roleCfg(r: string | null) {
  return ROLES[r ?? ''] ?? { label: r ?? 'Unknown', color: '#374151', bg: 'rgba(55,65,81,0.08)' };
}

// ── Small helpers ─────────────────────────────────────────────────────────

function Badge({ role }: { role: string | null }) {
  const { label, color, bg } = roleCfg(role);
  return (
    <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: bg, color }}>
      {label}
    </span>
  );
}

function StatusPill({ active, mustChange }: { active: boolean; mustChange: boolean }) {
  if (!active) return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: 'rgba(220,38,38,0.08)', color: '#b91c1c' }}>
      <XCircle className="h-3 w-3" /> Inactive
    </span>
  );
  if (mustChange) return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: 'rgba(217,119,6,0.08)', color: '#92400e' }}>
      <Clock className="h-3 w-3" /> Pending Setup
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
      style={{ background: 'rgba(5,150,105,0.08)', color: '#047857' }}>
      <CheckCircle2 className="h-3 w-3" /> Active
    </span>
  );
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="mt-1 text-xs" style={{ color: '#dc2626' }}>{msg}</p>;
}

// ── Modal shell ───────────────────────────────────────────────────────────

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.45)' }}>
      <div className="w-full max-w-md rounded-2xl shadow-2xl overflow-hidden"
        style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
        <div className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: '1px solid var(--border)' }}>
          <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 transition-colors hover:bg-[var(--bg-tertiary)]"
            style={{ color: 'var(--text-subtle)' }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

function Input({ label, error, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  return (
    <div>
      <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--text-secondary)' }}>{label}</label>
      <input {...props} className="w-full rounded-lg border px-3.5 py-2.5 text-sm outline-none transition-all"
        style={{ background: 'var(--bg-primary)', borderColor: error ? '#dc2626' : 'var(--border)', color: 'var(--text-primary)' }} />
      <FieldError msg={error} />
    </div>
  );
}

function Select({ label, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <div>
      <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--text-secondary)' }}>{label}</label>
      <div className="relative">
        <select {...props} className="w-full appearance-none rounded-lg border px-3.5 py-2.5 text-sm outline-none pr-10"
          style={{ background: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
          {children}
        </select>
        <ChevronDown className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4"
          style={{ color: 'var(--text-subtle)' }} />
      </div>
    </div>
  );
}

function PwInput({ label, value, onChange, error }: { label: string; value: string; onChange: (v: string) => void; error?: string }) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <label className="block text-xs font-semibold mb-1.5" style={{ color: 'var(--text-secondary)' }}>{label}</label>
      <div className="relative">
        <input type={show ? 'text' : 'password'} value={value} onChange={e => onChange(e.target.value)}
          className="w-full rounded-lg border px-3.5 py-2.5 text-sm outline-none pr-10"
          style={{ background: 'var(--bg-primary)', borderColor: error ? '#dc2626' : 'var(--border)', color: 'var(--text-primary)' }} />
        <button type="button" onClick={() => setShow(s => !s)}
          className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-subtle)' }}>
          {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
        </button>
      </div>
      <FieldError msg={error} />
    </div>
  );
}

// ── Create modal ──────────────────────────────────────────────────────────

function CreateModal({ practices, onClose }: { practices: Practice[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    email: '', first_name: '', last_name: '', provider_role: 'practice_admin',
    practice_id: '', password: '', must_change_password: true,
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [apiError, setApiError] = useState('');

  const mutation = useMutation({
    mutationFn: (data: typeof form) => api.post('/provider-users', {
      ...data,
      practice_id: data.practice_id || null,
    }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['provider-users'] }); onClose(); },
    onError: (e: any) => setApiError(e?.response?.data?.detail ?? 'Failed to create user'),
  });

  function validate() {
    const errs: Record<string, string> = {};
    if (!form.email) errs.email = 'Email is required';
    if (!form.first_name) errs.first_name = 'First name is required';
    if (!form.last_name) errs.last_name = 'Last name is required';
    if (!form.password || form.password.length < 10) errs.password = 'At least 10 characters';
    else if (!/[A-Z]/.test(form.password)) errs.password = 'Needs an uppercase letter';
    else if (!/[a-z]/.test(form.password)) errs.password = 'Needs a lowercase letter';
    else if (!/[0-9]/.test(form.password)) errs.password = 'Needs a digit';
    setErrors(errs);
    return Object.keys(errs).length === 0;
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!validate()) return;
    mutation.mutate(form);
  }

  const f = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }));

  return (
    <Modal title="Add Provider Login" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {apiError && <div className="rounded-lg px-4 py-3 text-sm" style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c' }}>{apiError}</div>}

        <div className="grid grid-cols-2 gap-3">
          <Input label="First Name" value={form.first_name} onChange={f('first_name')} error={errors.first_name} placeholder="Jane" />
          <Input label="Last Name" value={form.last_name} onChange={f('last_name')} error={errors.last_name} placeholder="Smith" />
        </div>

        <Input label="Email Address" type="email" value={form.email} onChange={f('email')} error={errors.email} placeholder="jane.smith@practice.org" />

        <Select label="Portal Role" value={form.provider_role} onChange={f('provider_role')}>
          {Object.entries(ROLES).map(([k, { label }]) => <option key={k} value={k}>{label}</option>)}
        </Select>

        <Select label="Practice / Hospital (optional)" value={form.practice_id} onChange={f('practice_id')}>
          <option value="">— No practice assigned —</option>
          {practices.map(p => <option key={p.id} value={p.id}>{p.practice_name}</option>)}
        </Select>

        <PwInput label="Temporary Password" value={form.password} onChange={v => setForm(p => ({ ...p, password: v }))} error={errors.password} />

        <label className="flex items-center gap-2.5 cursor-pointer">
          <input type="checkbox" checked={form.must_change_password}
            onChange={e => setForm(p => ({ ...p, must_change_password: e.target.checked }))}
            className="rounded" />
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>Require password change on first login</span>
        </label>

        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--bg-tertiary)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
            Cancel
          </button>
          <button type="submit" disabled={mutation.isPending}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #1a3872, #2a508e)', boxShadow: '0 4px 12px rgba(26,56,114,0.25)' }}>
            {mutation.isPending ? 'Creating…' : 'Create Login'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Edit modal ────────────────────────────────────────────────────────────

function EditModal({ user, practices, onClose }: { user: ProviderUser; practices: Practice[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    first_name: user.first_name, last_name: user.last_name,
    provider_role: user.provider_role ?? 'read_only',
    practice_id: user.practice_id ?? '',
  });
  const [apiError, setApiError] = useState('');

  const mutation = useMutation({
    mutationFn: () => api.patch(`/provider-users/${user.id}`, {
      ...form, practice_id: form.practice_id || null,
    }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['provider-users'] }); onClose(); },
    onError: (e: any) => setApiError(e?.response?.data?.detail ?? 'Failed to update user'),
  });

  const f = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm(p => ({ ...p, [k]: e.target.value }));

  return (
    <Modal title={`Edit — ${user.full_name}`} onClose={onClose}>
      <form onSubmit={e => { e.preventDefault(); mutation.mutate(); }} className="space-y-4">
        {apiError && <div className="rounded-lg px-4 py-3 text-sm" style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c' }}>{apiError}</div>}
        <div className="grid grid-cols-2 gap-3">
          <Input label="First Name" value={form.first_name} onChange={f('first_name')} />
          <Input label="Last Name" value={form.last_name} onChange={f('last_name')} />
        </div>
        <Select label="Portal Role" value={form.provider_role} onChange={f('provider_role')}>
          {Object.entries(ROLES).map(([k, { label }]) => <option key={k} value={k}>{label}</option>)}
        </Select>
        <Select label="Practice / Hospital" value={form.practice_id} onChange={f('practice_id')}>
          <option value="">— No practice assigned —</option>
          {practices.map(p => <option key={p.id} value={p.id}>{p.practice_name}</option>)}
        </Select>
        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--bg-tertiary)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
            Cancel
          </button>
          <button type="submit" disabled={mutation.isPending}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #1a3872, #2a508e)' }}>
            {mutation.isPending ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Reset password modal ──────────────────────────────────────────────────

function ResetPasswordModal({ user, onClose }: { user: ProviderUser; onClose: () => void }) {
  const qc = useQueryClient();
  const [password, setPassword] = useState('');
  const [mustChange, setMustChange] = useState(true);
  const [error, setError] = useState('');
  const [apiError, setApiError] = useState('');

  const mutation = useMutation({
    mutationFn: () => api.post(`/provider-users/${user.id}/reset-password`, {
      new_password: password, must_change_password: mustChange,
    }).then(r => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['provider-users'] }); onClose(); },
    onError: (e: any) => setApiError(e?.response?.data?.detail ?? 'Failed to reset password'),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (password.length < 10) { setError('At least 10 characters'); return; }
    if (!/[A-Z]/.test(password)) { setError('Needs an uppercase letter'); return; }
    if (!/[a-z]/.test(password)) { setError('Needs a lowercase letter'); return; }
    if (!/[0-9]/.test(password)) { setError('Needs a digit'); return; }
    mutation.mutate();
  }

  return (
    <Modal title={`Reset Password — ${user.full_name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {apiError && <div className="rounded-lg px-4 py-3 text-sm" style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c' }}>{apiError}</div>}
        <div className="rounded-xl p-3.5 text-sm" style={{ background: 'rgba(217,119,6,0.06)', border: '1px solid rgba(217,119,6,0.2)', color: '#92400e' }}>
          Setting a new password for <strong>{user.email}</strong>. Share it securely with the user.
        </div>
        <PwInput label="New Password" value={password} onChange={setPassword} error={error} />
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input type="checkbox" checked={mustChange} onChange={e => setMustChange(e.target.checked)} className="rounded" />
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>Require password change on next login</span>
        </label>
        <div className="flex gap-3 pt-2">
          <button type="button" onClick={onClose}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-medium transition-colors hover:bg-[var(--bg-tertiary)]"
            style={{ border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
            Cancel
          </button>
          <button type="submit" disabled={mutation.isPending}
            className="flex-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #b91c1c, #dc2626)' }}>
            {mutation.isPending ? 'Resetting…' : 'Reset Password'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ── Row action menu ───────────────────────────────────────────────────────

function RowMenu({ user, onEdit, onReset, onToggle }: {
  user: ProviderUser;
  onEdit: () => void; onReset: () => void; onToggle: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button onClick={() => setOpen(o => !o)}
        className="rounded-lg p-1.5 transition-colors hover:bg-[var(--bg-tertiary)]"
        style={{ color: 'var(--text-subtle)' }}>
        <MoreVertical className="h-4 w-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-20 mt-1 w-44 rounded-xl shadow-lg overflow-hidden"
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
            <button onClick={() => { setOpen(false); onEdit(); }}
              className="flex w-full items-center gap-2.5 px-4 py-2.5 text-xs font-medium transition-colors hover:bg-[var(--bg-tertiary)]"
              style={{ color: 'var(--text-primary)' }}>
              <Shield className="h-3.5 w-3.5" /> Edit Details
            </button>
            <button onClick={() => { setOpen(false); onReset(); }}
              className="flex w-full items-center gap-2.5 px-4 py-2.5 text-xs font-medium transition-colors hover:bg-[var(--bg-tertiary)]"
              style={{ color: 'var(--text-primary)' }}>
              <KeyRound className="h-3.5 w-3.5" /> Reset Password
            </button>
            <div style={{ height: 1, background: 'var(--border)', margin: '2px 0' }} />
            <button onClick={() => { setOpen(false); onToggle(); }}
              className="flex w-full items-center gap-2.5 px-4 py-2.5 text-xs font-medium transition-colors"
              style={{ color: user.is_active ? '#dc2626' : '#059669' }}
              onMouseEnter={e => { e.currentTarget.style.background = user.is_active ? 'rgba(220,38,38,0.06)' : 'rgba(5,150,105,0.06)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}>
              {user.is_active
                ? <><PowerOff className="h-3.5 w-3.5" /> Deactivate</>
                : <><Power className="h-3.5 w-3.5" /> Activate</>}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────

export function ProviderUsersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ProviderUser | null>(null);
  const [resetting, setResetting] = useState<ProviderUser | null>(null);

  const { data: rawUsers, isLoading } = useQuery<ProviderUser[]>({
    queryKey: ['provider-users'],
    queryFn: () => api.get('/provider-users').then(r => r.data),
  });
  const users = Array.isArray(rawUsers) ? rawUsers : [];

  const { data: rawPractices } = useQuery<Practice[]>({
    queryKey: ['provider-user-practices'],
    queryFn: () => api.get('/provider-users/practices').then(r => r.data),
  });
  const practices = Array.isArray(rawPractices) ? rawPractices : [];

  const toggleActive = useMutation({
    mutationFn: (u: ProviderUser) => api.patch(`/provider-users/${u.id}`, { is_active: !u.is_active }).then(r => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['provider-users'] }),
  });

  const filtered = users.filter(u => {
    const q = search.toLowerCase();
    const matchSearch = !q || u.full_name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q)
      || (u.practice_name ?? '').toLowerCase().includes(q);
    const matchRole = !roleFilter || u.provider_role === roleFilter;
    return matchSearch && matchRole;
  });

  const stats = {
    total: users.length,
    active: users.filter(u => u.is_active).length,
    pending: users.filter(u => u.is_active && u.must_change_password).length,
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Provider Logins</h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-subtle)' }}>
            Manage portal access for practices, physicians, and hospitals
          </p>
        </div>
        <button onClick={() => setCreating(true)}
          className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold text-white transition-all"
          style={{ background: 'linear-gradient(135deg, #1a3872, #2a508e)', boxShadow: '0 4px 12px rgba(26,56,114,0.25)' }}>
          <UserPlus className="h-4 w-4" /> Add Provider Login
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Total Logins', value: stats.total, color: '#1a3872', bg: 'rgba(26,56,114,0.08)' },
          { label: 'Active',        value: stats.active, color: '#059669', bg: 'rgba(5,150,105,0.08)' },
          { label: 'Pending Setup', value: stats.pending, color: '#d97706', bg: 'rgba(217,119,6,0.08)' },
        ].map(s => (
          <div key={s.label} className="rounded-xl p-4"
            style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
            <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-subtle)' }}>{s.label}</p>
            <p className="text-2xl font-bold" style={{ color: s.color }}>{isLoading ? '—' : s.value}</p>
          </div>
        ))}
      </div>

      {/* Table card */}
      <div className="rounded-xl overflow-hidden" style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }}>
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-5 py-3.5" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="relative flex-1 max-w-xs">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5" style={{ color: 'var(--text-subtle)' }} />
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search name, email, practice…"
              className="w-full rounded-lg border pl-9 pr-3 py-2 text-xs outline-none"
              style={{ background: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }} />
          </div>
          <div className="relative">
            <select value={roleFilter} onChange={e => setRoleFilter(e.target.value)}
              className="appearance-none rounded-lg border pl-3 pr-8 py-2 text-xs outline-none"
              style={{ background: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
              <option value="">All Roles</option>
              {Object.entries(ROLES).map(([k, { label }]) => <option key={k} value={k}>{label}</option>)}
            </select>
            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5"
              style={{ color: 'var(--text-subtle)' }} />
          </div>
          <button onClick={() => qc.invalidateQueries({ queryKey: ['provider-users'] })}
            className="rounded-lg p-2 transition-colors hover:bg-[var(--bg-tertiary)]"
            style={{ color: 'var(--text-subtle)' }}>
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['User', 'Practice / Hospital', 'Role', 'Status', 'Last Login', ''].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-wider"
                    style={{ color: 'var(--text-subtle)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 4 }).map((_, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    {[140, 120, 90, 80, 80, 30].map((w, j) => (
                      <td key={j} className="px-5 py-3.5">
                        <div className="h-3 rounded animate-pulse" style={{ background: 'var(--bg-tertiary)', width: w }} />
                      </td>
                    ))}
                  </tr>
                ))
                : filtered.length === 0
                  ? (
                    <tr>
                      <td colSpan={6} className="px-5 py-14 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <Building2 className="h-10 w-10 opacity-20" style={{ color: 'var(--text-subtle)' }} />
                          <p className="text-sm" style={{ color: 'var(--text-subtle)' }}>
                            {search || roleFilter ? 'No users match your filters' : 'No provider logins yet — add one to get started'}
                          </p>
                        </div>
                      </td>
                    </tr>
                  )
                  : filtered.map(u => (
                    <tr key={u.id} style={{ borderBottom: '1px solid var(--border-subtle)' }}
                      onMouseEnter={e => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-tertiary)'; }}
                      onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-3">
                          <div className="h-7 w-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white flex-shrink-0"
                            style={{ background: 'linear-gradient(135deg, #2a508e, #5272a4)' }}>
                            {(u.first_name[0] ?? '') + (u.last_name[0] ?? '')}
                          </div>
                          <div>
                            <p className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>{u.full_name}</p>
                            <p className="text-[11px]" style={{ color: 'var(--text-subtle)' }}>{u.email}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-5 py-3.5">
                        {u.practice_name
                          ? <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{u.practice_name}</span>
                          : <span className="text-xs italic" style={{ color: 'var(--text-subtle)' }}>Not assigned</span>}
                      </td>
                      <td className="px-5 py-3.5"><Badge role={u.provider_role} /></td>
                      <td className="px-5 py-3.5"><StatusPill active={u.is_active} mustChange={u.must_change_password} /></td>
                      <td className="px-5 py-3.5">
                        <span className="text-xs" style={{ color: 'var(--text-subtle)' }}>
                          {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                        </span>
                      </td>
                      <td className="px-5 py-3.5">
                        <RowMenu user={u}
                          onEdit={() => setEditing(u)}
                          onReset={() => setResetting(u)}
                          onToggle={() => toggleActive.mutate(u)} />
                      </td>
                    </tr>
                  ))
              }
            </tbody>
          </table>
        </div>

        {!isLoading && filtered.length > 0 && (
          <div className="px-5 py-3 text-xs" style={{ borderTop: '1px solid var(--border)', color: 'var(--text-subtle)' }}>
            Showing {filtered.length} of {users.length} logins
          </div>
        )}
      </div>

      {/* Modals */}
      {creating && <CreateModal practices={practices} onClose={() => setCreating(false)} />}
      {editing  && <EditModal user={editing} practices={practices} onClose={() => setEditing(null)} />}
      {resetting && <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />}
    </div>
  );
}
