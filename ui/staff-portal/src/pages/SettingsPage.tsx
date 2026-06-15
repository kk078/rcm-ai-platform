import { useState, useEffect } from 'react';
import {
  User, Shield, Bell, Users, Eye, EyeOff,
  Plus, Pencil, X, CheckCircle, AlertCircle,
  Key, Smartphone, Loader2,
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

// ── Types ─────────────────────────────────────────────────────────────────

type Tab = 'profile' | 'security' | 'notifications' | 'users';

interface UserRecord {
  id: string;
  email: string;
  full_name: string;
  first_name: string;
  last_name: string;
  internal_role: string;
  is_active: boolean;
  mfa_enabled: boolean;
  last_login: string | null;
  created_at: string;
}

const ROLES = [
  { value: 'company_admin',    label: 'Company Admin' },
  { value: 'billing_specialist', label: 'Billing Specialist' },
  { value: 'coder',            label: 'Medical Coder' },
  { value: 'ar_specialist',    label: 'A/R Specialist' },
  { value: 'payment_poster',   label: 'Payment Poster' },
  { value: 'denial_manager',   label: 'Denial Manager' },
  { value: 'viewer',           label: 'Viewer (Read-only)' },
];

// ── Shared UI ─────────────────────────────────────────────────────────────

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border p-6 ${className}`}
      style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)' }}>
      {children}
    </div>
  );
}

function CardHeader({ icon: Icon, title }: { icon: React.ElementType; title: string }) {
  return (
    <div className="flex items-center gap-3 mb-5">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-aethera-600/10">
        <Icon className="h-4 w-4 text-aethera-600" />
      </div>
      <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>{title}</h2>
    </div>
  );
}

function Alert({ type, msg }: { type: 'success' | 'error'; msg: string }) {
  const isOk = type === 'success';
  return (
    <div className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${
      isOk ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400'
           : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400'
    }`}>
      {isOk ? <CheckCircle className="h-4 w-4 shrink-0" /> : <AlertCircle className="h-4 w-4 shrink-0" />}
      {msg}
    </div>
  );
}

function Input({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <div>
      <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>{label}</label>
      <input
        {...props}
        className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50 transition-shadow"
        style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
      />
    </div>
  );
}

function Btn({ children, loading = false, variant = 'primary', ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; variant?: 'primary' | 'ghost' | 'danger' }) {
  const base = 'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:opacity-50';
  const variants = {
    primary: 'bg-aethera-600 text-white hover:bg-aethera-700',
    ghost: 'hover:bg-[var(--bg-tertiary)]',
    danger: 'bg-red-600 text-white hover:bg-red-700',
  };
  return (
    <button {...props} disabled={loading || props.disabled} className={`${base} ${variants[variant]}`}
      style={variant === 'ghost' ? { color: 'var(--text-muted)' } : undefined}>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
      {children}
    </button>
  );
}

// ── Profile Tab ───────────────────────────────────────────────────────────

function ProfileTab() {
  const { user, refreshUser } = useAuth() as any;
  const [firstName, setFirstName] = useState(user?.first_name ?? '');
  const [lastName, setLastName] = useState(user?.last_name ?? '');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  async function save() {
    setSaving(true); setMsg(null);
    try {
      await api.patch('/auth/me', { first_name: firstName, last_name: lastName });
      setMsg({ type: 'success', text: 'Profile updated successfully.' });
      if (refreshUser) await refreshUser();
    } catch (e: any) {
      setMsg({ type: 'error', text: e.response?.data?.detail ?? 'Failed to update profile.' });
    } finally { setSaving(false); }
  }

  return (
    <div className="space-y-5 max-w-lg">
      <Card>
        <CardHeader icon={User} title="Personal Information" />
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <Input label="First Name" value={firstName} onChange={e => setFirstName(e.target.value)} />
            <Input label="Last Name" value={lastName} onChange={e => setLastName(e.target.value)} />
          </div>
          <Input label="Email Address" value={user?.email ?? ''} disabled />
          <Input label="Role" value={user?.internal_role?.replace(/_/g, ' ') ?? ''} disabled />
        </div>
        <div className="mt-5 flex items-center gap-3">
          <Btn loading={saving} onClick={save}>Save Changes</Btn>
          {msg && <Alert type={msg.type} msg={msg.text} />}
        </div>
      </Card>
    </div>
  );
}

// ── Security Tab ──────────────────────────────────────────────────────────

function PasswordSection() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) { setMsg({ type: 'error', text: 'New passwords do not match.' }); return; }
    if (next.length < 10) { setMsg({ type: 'error', text: 'Password must be at least 10 characters.' }); return; }
    setSaving(true); setMsg(null);
    try {
      await api.post('/auth/change-password', { current_password: current, new_password: next });
      setMsg({ type: 'success', text: 'Password changed. You will need to log in again on other devices.' });
      setCurrent(''); setNext(''); setConfirm('');
    } catch (e: any) {
      setMsg({ type: 'error', text: e.response?.data?.detail ?? 'Failed to change password.' });
    } finally { setSaving(false); }
  }

  const type = showPw ? 'text' : 'password';
  return (
    <Card>
      <CardHeader icon={Key} title="Change Password" />
      <form onSubmit={submit} className="space-y-4">
        <Input label="Current Password" type={type} value={current} onChange={e => setCurrent(e.target.value)} required />
        <Input label="New Password" type={type} value={next} onChange={e => setNext(e.target.value)} required />
        <Input label="Confirm New Password" type={type} value={confirm} onChange={e => setConfirm(e.target.value)} required />
        <div>
          <label className="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" checked={showPw} onChange={e => setShowPw(e.target.checked)} className="rounded" />
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Show passwords</span>
          </label>
        </div>
        <p className="text-xs" style={{ color: 'var(--text-subtle)' }}>
          Min 10 characters · at least one uppercase, one lowercase, one digit
        </p>
        <div className="flex items-center gap-3">
          <Btn type="submit" loading={saving}>Update Password</Btn>
          {msg && <Alert type={msg.type} msg={msg.text} />}
        </div>
      </form>
    </Card>
  );
}

function MFASection() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [qrUri, setQrUri] = useState<string | null>(null);
  const [backupCodes, setBackupCodes] = useState<string[]>([]);
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'idle' | 'scan' | 'verify' | 'done'>('idle');
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const enabled = user?.mfa_enabled;

  async function startSetup() {
    setLoading(true); setMsg(null);
    try {
      const res = await api.post('/auth/mfa/setup');
      setQrUri(res.data.provisioning_uri);
      setBackupCodes(res.data.backup_codes ?? []);
      setStep('scan');
    } catch { setMsg({ type: 'error', text: 'Failed to start MFA setup.' }); }
    finally { setLoading(false); }
  }

  async function verify() {
    setLoading(true); setMsg(null);
    try {
      await api.post('/auth/mfa/verify', { code });
      setStep('done');
      setMsg({ type: 'success', text: 'MFA enabled! Save your backup codes in a safe place.' });
    } catch { setMsg({ type: 'error', text: 'Invalid code — try again.' }); }
    finally { setLoading(false); }
  }

  return (
    <Card>
      <CardHeader icon={Smartphone} title="Two-Factor Authentication (MFA)" />
      {enabled ? (
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-sm text-green-600 dark:text-green-400">
            <CheckCircle className="h-4 w-4" /> MFA is enabled on your account
          </div>
        </div>
      ) : step === 'idle' ? (
        <div className="space-y-3">
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            Add an extra layer of security using an authenticator app (Google Authenticator, Authy, etc.).
          </p>
          <Btn onClick={startSetup} loading={loading}>Enable MFA</Btn>
          {msg && <Alert type={msg.type} msg={msg.text} />}
        </div>
      ) : step === 'scan' ? (
        <div className="space-y-4">
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            1. Open your authenticator app and scan the QR code, or enter the URL manually.
          </p>
          {qrUri && (
            <div className="rounded-lg border p-4 text-center" style={{ borderColor: 'var(--border)' }}>
              <img
                src={`https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(qrUri)}`}
                alt="MFA QR Code" className="mx-auto rounded"
              />
              <details className="mt-3 text-left">
                <summary className="cursor-pointer text-xs" style={{ color: 'var(--text-subtle)' }}>Manual entry URL</summary>
                <p className="mt-1 break-all font-mono text-xs" style={{ color: 'var(--text-muted)' }}>{qrUri}</p>
              </details>
            </div>
          )}
          {backupCodes.length > 0 && (
            <div className="rounded-lg border p-4" style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-tertiary)' }}>
              <p className="mb-2 text-xs font-semibold text-amber-600 dark:text-amber-400">⚠ Save these backup codes — shown only once</p>
              <div className="grid grid-cols-2 gap-1">
                {backupCodes.map(c => (
                  <code key={c} className="rounded px-2 py-0.5 text-xs font-mono" style={{ color: 'var(--text-primary)' }}>{c}</code>
                ))}
              </div>
            </div>
          )}
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>2. Enter the 6-digit code from your app to confirm:</p>
          <div className="flex items-center gap-3">
            <input
              value={code} onChange={e => setCode(e.target.value)} maxLength={6} placeholder="000000"
              className="w-32 rounded-lg border px-3 py-2 text-center text-lg font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-aethera-600/50"
              style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            />
            <Btn onClick={verify} loading={loading} disabled={code.length !== 6}>Verify & Enable</Btn>
          </div>
          {msg && <Alert type={msg.type} msg={msg.text} />}
        </div>
      ) : (
        <div className="space-y-3">
          <Alert type="success" msg="MFA enabled! Store your backup codes somewhere safe." />
          {backupCodes.length > 0 && (
            <div className="rounded-lg border p-4" style={{ borderColor: 'var(--border)', backgroundColor: 'var(--bg-tertiary)' }}>
              <div className="grid grid-cols-2 gap-1">
                {backupCodes.map(c => (
                  <code key={c} className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>{c}</code>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

function SecurityTab() {
  return (
    <div className="space-y-5 max-w-lg">
      <PasswordSection />
      <MFASection />
    </div>
  );
}

// ── Notifications Tab ─────────────────────────────────────────────────────

function NotificationsTab() {
  const [prefs, setPrefs] = useState({
    sla_breach: true, appeal_deadline: true, payment_posting: false,
    denial_alert: true, daily_summary: false,
  });
  const toggle = (k: keyof typeof prefs) => setPrefs(p => ({ ...p, [k]: !p[k] }));

  const items = [
    { key: 'sla_breach' as const,       label: 'SLA breach alerts',            desc: 'Notify when a claim exceeds its SLA window' },
    { key: 'appeal_deadline' as const,   label: 'Appeal deadline reminders',     desc: 'Alerts 5 days before a denial appeal deadline' },
    { key: 'denial_alert' as const,      label: 'New denial notifications',       desc: 'Email when a new denial is received' },
    { key: 'payment_posting' as const,   label: 'Payment posting confirmations', desc: 'Confirm each ERA/EOB batch posted' },
    { key: 'daily_summary' as const,     label: 'Daily digest email',            desc: 'Summary of queue activity every morning' },
  ];

  return (
    <div className="max-w-lg">
      <Card>
        <CardHeader icon={Bell} title="Email Notifications" />
        <div className="space-y-4">
          {items.map(({ key, label, desc }) => (
            <label key={key} className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox" checked={prefs[key]} onChange={() => toggle(key)}
                className="mt-0.5 h-4 w-4 rounded border-gray-300 text-aethera-600 focus:ring-aethera-600"
              />
              <div>
                <p className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{label}</p>
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-subtle)' }}>{desc}</p>
              </div>
            </label>
          ))}
        </div>
        <div className="mt-5">
          <Btn>Save Preferences</Btn>
        </div>
      </Card>
    </div>
  );
}

// ── Users Tab ─────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: string }) {
  const color: Record<string, string> = {
    company_admin: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300',
    billing_specialist: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    coder: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
    ar_specialist: 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300',
    payment_poster: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
    denial_manager: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300',
    viewer: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300',
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${color[role] ?? color.viewer}`}>
      {ROLES.find(r => r.value === role)?.label ?? role}
    </span>
  );
}

interface CreateFormData { email: string; first_name: string; last_name: string; internal_role: string; password: string; }

function CreateUserModal({ onClose, onCreated }: { onClose: () => void; onCreated: (u: UserRecord) => void }) {
  const [form, setForm] = useState<CreateFormData>({
    email: '', first_name: '', last_name: '', internal_role: 'billing_specialist', password: '',
  });
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function set(k: keyof CreateFormData, v: string) { setForm(f => ({ ...f, [k]: v })); }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setSaving(true); setErr(null);
    try {
      const res = await api.post('/users', form);
      onCreated(res.data);
      onClose();
    } catch (ex: any) {
      setErr(ex.response?.data?.detail ?? 'Failed to create user.');
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-2xl shadow-xl p-6 m-4"
        style={{ backgroundColor: 'var(--card-bg)', border: '1px solid var(--border)' }}>
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>Create New User</h3>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-[var(--bg-tertiary)]" style={{ color: 'var(--text-muted)' }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <Input label="First Name" value={form.first_name} onChange={e => set('first_name', e.target.value)} required />
            <Input label="Last Name" value={form.last_name} onChange={e => set('last_name', e.target.value)} required />
          </div>
          <Input label="Email Address" type="email" value={form.email} onChange={e => set('email', e.target.value)} required />
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>Role</label>
            <select
              value={form.internal_role} onChange={e => set('internal_role', e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50"
              style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
            >
              {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="relative">
            <Input label="Temporary Password" type={showPw ? 'text' : 'password'} value={form.password} onChange={e => set('password', e.target.value)} required />
            <button type="button" onClick={() => setShowPw(s => !s)}
              className="absolute right-3 top-7 text-gray-400 hover:text-gray-600">
              {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="text-xs" style={{ color: 'var(--text-subtle)' }}>Min 10 chars · uppercase · lowercase · digit</p>
          {err && <Alert type="error" msg={err} />}
          <div className="flex justify-end gap-3 pt-2">
            <Btn variant="ghost" type="button" onClick={onClose}>Cancel</Btn>
            <Btn type="submit" loading={saving}><Plus className="h-3.5 w-3.5" /> Create User</Btn>
          </div>
        </form>
      </div>
    </div>
  );
}

function EditUserModal({ user: u, onClose, onUpdated }: { user: UserRecord; onClose: () => void; onUpdated: (u: UserRecord) => void }) {
  const [role, setRole] = useState(u.internal_role);
  const [active, setActive] = useState(u.is_active);
  const [newPw, setNewPw] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  async function saveUser() {
    setSaving(true); setErr(null); setOk(null);
    try {
      const res = await api.patch(`/users/${u.id}`, { internal_role: role, is_active: active });
      onUpdated(res.data);
      setOk('User updated successfully.');
    } catch (ex: any) { setErr(ex.response?.data?.detail ?? 'Update failed.'); }
    finally { setSaving(false); }
  }

  async function resetPw() {
    if (!newPw) return;
    setSaving(true); setErr(null); setOk(null);
    try {
      await api.post(`/users/${u.id}/reset-password`, { new_password: newPw });
      setOk('Password reset successfully.'); setNewPw('');
    } catch (ex: any) { setErr(ex.response?.data?.detail ?? 'Reset failed.'); }
    finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-md rounded-2xl shadow-xl p-6 m-4"
        style={{ backgroundColor: 'var(--card-bg)', border: '1px solid var(--border)' }}>
        <div className="flex items-center justify-between mb-5">
          <div>
            <h3 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>{u.full_name}</h3>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{u.email}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 hover:bg-[var(--bg-tertiary)]" style={{ color: 'var(--text-muted)' }}>
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>Role</label>
            <select value={role} onChange={e => setRole(e.target.value)}
              className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50"
              style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
              {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <label className="flex items-center gap-3 cursor-pointer select-none">
            <input type="checkbox" checked={active} onChange={e => setActive(e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-aethera-600" />
            <span className="text-sm" style={{ color: 'var(--text-primary)' }}>Account active</span>
          </label>
          <Btn onClick={saveUser} loading={saving}>Save Changes</Btn>

          <hr style={{ borderColor: 'var(--border)' }} />

          <div className="space-y-2">
            <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>Reset Password</p>
            <Input label="New Password" type="password" value={newPw} onChange={e => setNewPw(e.target.value)} placeholder="Min 10 chars" />
            <Btn variant="danger" onClick={resetPw} loading={saving} disabled={!newPw}>Reset Password</Btn>
          </div>

          {err && <Alert type="error" msg={err} />}
          {ok && <Alert type="success" msg={ok} />}
        </div>
      </div>
    </div>
  );
}

function UsersTab() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<UserRecord | null>(null);

  useEffect(() => {
    api.get('/users').then(r => { setUsers(r.data); setLoading(false); })
      .catch(() => { setErr('Failed to load users.'); setLoading(false); });
  }, []);

  if (me?.internal_role !== 'company_admin') {
    return (
      <Card className="max-w-lg">
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          User management is available to Company Administrators only.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {users.length} staff {users.length === 1 ? 'member' : 'members'}
        </p>
        <Btn onClick={() => setShowCreate(true)}><Plus className="h-3.5 w-3.5" /> New User</Btn>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-aethera-600" /></div>
      ) : err ? (
        <Alert type="error" msg={err} />
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ backgroundColor: 'var(--bg-secondary)', borderBottom: '1px solid var(--border)' }}>
                {['Name', 'Email', 'Role', 'MFA', 'Status', 'Last Login', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--text-subtle)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} style={{ borderBottom: '1px solid var(--border)', backgroundColor: 'var(--card-bg)' }}
                  className="hover:bg-[var(--bg-secondary)] transition-colors">
                  <td className="px-4 py-3 font-medium" style={{ color: 'var(--text-primary)' }}>{u.full_name || '—'}</td>
                  <td className="px-4 py-3" style={{ color: 'var(--text-muted)' }}>{u.email}</td>
                  <td className="px-4 py-3"><RoleBadge role={u.internal_role} /></td>
                  <td className="px-4 py-3">
                    {u.mfa_enabled
                      ? <span className="text-xs text-green-600 dark:text-green-400 font-medium">On</span>
                      : <span className="text-xs" style={{ color: 'var(--text-subtle)' }}>Off</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      u.is_active ? 'bg-green-100 text-green-700 dark:bg-green-900/20 dark:text-green-400'
                                  : 'bg-red-100 text-red-600 dark:bg-red-900/20 dark:text-red-400'}`}>
                      {u.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs" style={{ color: 'var(--text-subtle)' }}>
                    {u.last_login ? new Date(u.last_login).toLocaleDateString() : 'Never'}
                  </td>
                  <td className="px-4 py-3">
                    <button onClick={() => setEditing(u)}
                      className="rounded p-1 hover:bg-[var(--bg-tertiary)] transition-colors" style={{ color: 'var(--text-muted)' }}>
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateUserModal
          onClose={() => setShowCreate(false)}
          onCreated={u => setUsers(prev => [u, ...prev])}
        />
      )}
      {editing && (
        <EditUserModal
          user={editing}
          onClose={() => setEditing(null)}
          onUpdated={u => { setUsers(prev => prev.map(x => x.id === u.id ? u : x)); setEditing(null); }}
        />
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'profile',       label: 'Profile',       icon: User },
  { id: 'security',      label: 'Security',       icon: Shield },
  { id: 'notifications', label: 'Notifications',  icon: Bell },
  { id: 'users',         label: 'User Management', icon: Users },
];

export function SettingsPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>('profile');
  const isAdmin = user?.internal_role === 'company_admin';

  const visibleTabs = isAdmin ? TABS : TABS.filter(t => t.id !== 'users');

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>Settings</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>Manage your account, security, and team</p>
      </div>

      <div className="flex gap-6">
        {/* Sidebar nav */}
        <div className="w-48 shrink-0">
          <nav className="space-y-1">
            {visibleTabs.map(({ id, label, icon: Icon }) => (
              <button key={id} onClick={() => setTab(id)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  tab === id ? 'bg-aethera-600/10 text-aethera-600' : 'hover:bg-[var(--bg-tertiary)]'
                }`}
                style={tab !== id ? { color: 'var(--text-muted)' } : undefined}>
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </button>
            ))}
          </nav>
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          {tab === 'profile'       && <ProfileTab />}
          {tab === 'security'      && <SecurityTab />}
          {tab === 'notifications' && <NotificationsTab />}
          {tab === 'users'         && <UsersTab />}
        </div>
      </div>
    </div>
  );
}
