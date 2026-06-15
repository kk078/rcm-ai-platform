import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Eye, EyeOff, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import api from '../lib/api';
import { useAuth } from '../hooks/useAuth';

const RULES = [
  { test: (v: string) => v.length >= 10,            label: 'At least 10 characters' },
  { test: (v: string) => /[A-Z]/.test(v),           label: 'One uppercase letter' },
  { test: (v: string) => /[a-z]/.test(v),           label: 'One lowercase letter' },
  { test: (v: string) => /[0-9]/.test(v),           label: 'One number' },
  { test: (v: string) => /[^A-Za-z0-9]/.test(v),   label: 'One special character' },
];

export function ForcePasswordChangePage() {
  const navigate = useNavigate();
  const { user, updateUser } = useAuth() as any;
  const [current, setCurrent]   = useState('');
  const [next, setNext]         = useState('');
  const [confirm, setConfirm]   = useState('');
  const [show, setShow]         = useState(false);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const strength = RULES.filter(r => r.test(next)).length;
  const strengthColor = ['bg-red-400', 'bg-orange-400', 'bg-yellow-400', 'bg-lime-500', 'bg-green-500'][Math.min(strength - 1, 4)] ?? 'bg-gray-200';

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) { setError('New passwords do not match.'); return; }
    if (strength < 4)     { setError('Password does not meet the requirements.'); return; }

    setLoading(true); setError(null);
    try {
      await api.post('/auth/change-password', {
        current_password: current,
        new_password: next,
      });
      // Clear the must_change_password flag in local state
      if (updateUser) updateUser({ must_change_password: false });
      navigate('/dashboard', { replace: true });
    } catch (ex: any) {
      setError(ex.response?.data?.detail ?? 'Failed to update password. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: 'var(--bg-primary)' }}>
      <div className="w-full max-w-md">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-aethera-500 to-aethera-700 shadow-lg">
            <Shield className="h-7 w-7 text-white" />
          </div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
            Set Your Password
          </h1>
          <p className="mt-2 text-sm" style={{ color: 'var(--text-muted)' }}>
            Welcome, {user?.full_name?.split(' ')[0] ?? 'there'}! For your security, please
            choose a strong password before continuing.
          </p>
        </div>

        {/* Card */}
        <div className="rounded-2xl border shadow-md p-8"
          style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)' }}>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Current password */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>
                Current (temporary) password
              </label>
              <div className="relative">
                <input
                  type={show ? 'text' : 'password'}
                  value={current} onChange={e => setCurrent(e.target.value)}
                  required autoFocus
                  className="w-full rounded-lg border px-3 py-2.5 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50"
                  style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
                  placeholder="Enter your temporary password"
                />
                <button type="button" onClick={() => setShow(s => !s)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                  {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {/* New password */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>
                New password
              </label>
              <input
                type={show ? 'text' : 'password'}
                value={next} onChange={e => setNext(e.target.value)}
                required
                className="w-full rounded-lg border px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50"
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
                placeholder="Choose a strong password"
              />
              {/* Strength bar */}
              {next.length > 0 && (
                <div className="mt-2">
                  <div className="flex gap-1">
                    {[0,1,2,3,4].map(i => (
                      <div key={i} className={`h-1 flex-1 rounded-full transition-all ${i < strength ? strengthColor : 'bg-gray-200 dark:bg-gray-700'}`} />
                    ))}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                    {RULES.map(r => (
                      <div key={r.label} className={`flex items-center gap-1.5 text-xs ${r.test(next) ? 'text-green-600 dark:text-green-400' : ''}`}
                        style={!r.test(next) ? { color: 'var(--text-subtle)' } : undefined}>
                        <CheckCircle className={`h-3 w-3 shrink-0 ${r.test(next) ? 'text-green-500' : 'text-gray-300'}`} />
                        {r.label}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Confirm password */}
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>
                Confirm new password
              </label>
              <input
                type={show ? 'text' : 'password'}
                value={confirm} onChange={e => setConfirm(e.target.value)}
                required
                className={`w-full rounded-lg border px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-aethera-600/50 ${
                  confirm.length > 0 && confirm !== next ? 'border-red-400' : ''}`}
                style={{ backgroundColor: 'var(--bg-primary)', borderColor: confirm.length > 0 && confirm !== next ? undefined : 'var(--border)', color: 'var(--text-primary)' }}
                placeholder="Re-enter new password"
              />
              {confirm.length > 0 && confirm !== next && (
                <p className="mt-1 text-xs text-red-500">Passwords do not match</p>
              )}
            </div>

            {error && (
              <div className="flex items-center gap-2 rounded-lg bg-red-50 dark:bg-red-900/20 px-3 py-2 text-sm text-red-700 dark:text-red-400">
                <AlertCircle className="h-4 w-4 shrink-0" />
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || strength < 4 || next !== confirm || !current}
              className="w-full rounded-lg py-2.5 text-sm font-semibold text-white transition-all bg-aethera-600 hover:bg-aethera-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {loading ? 'Updating password…' : 'Set Password & Continue →'}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-xs" style={{ color: 'var(--text-subtle)' }}>
          This is a one-time step required for all new accounts.
        </p>
      </div>
    </div>
  );
}
