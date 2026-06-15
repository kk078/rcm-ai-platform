import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import api from '../lib/api';

const RULES = [
  { test: (v: string) => v.length >= 10,           label: 'At least 10 characters' },
  { test: (v: string) => /[A-Z]/.test(v),          label: 'One uppercase letter' },
  { test: (v: string) => /[a-z]/.test(v),          label: 'One lowercase letter' },
  { test: (v: string) => /[0-9]/.test(v),          label: 'One number' },
  { test: (v: string) => /[^A-Za-z0-9]/.test(v),  label: 'One special character' },
];

export function ForcePasswordChangePage() {
  const { updateUser } = useAuth();
  const navigate = useNavigate();

  const [current, setCurrent]     = useState('');
  const [next, setNext]           = useState('');
  const [confirm, setConfirm]     = useState('');
  const [error, setError]         = useState('');
  const [submitting, setSubmitting] = useState(false);

  const rulesPassed = RULES.filter(r => r.test(next));
  const allPassed   = rulesPassed.length === RULES.length;
  const matches     = next === confirm;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!allPassed) { setError('Password does not meet all requirements.'); return; }
    if (!matches)   { setError('New passwords do not match.'); return; }
    setSubmitting(true);
    try {
      await api.post('/auth/change-password', {
        current_password: current,
        new_password: next,
      });
      updateUser({ must_change_password: false });
      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? 'Failed to change password. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-8">
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-blue-100 mb-4">
            <svg className="w-7 h-7 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Set Your Password</h1>
          <p className="text-gray-500 text-sm mt-2">
            Your account requires a password change before you can continue.
          </p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Current Password</label>
            <input type="password" value={current} onChange={e => setCurrent(e.target.value)} required
              autoComplete="current-password"
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition text-sm"
              placeholder="Enter your current password" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">New Password</label>
            <input type="password" value={next} onChange={e => setNext(e.target.value)} required
              autoComplete="new-password"
              className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition text-sm"
              placeholder="Enter your new password" />
            {next && (
              <ul className="mt-2 space-y-1">
                {RULES.map(rule => {
                  const ok = rule.test(next);
                  return (
                    <li key={rule.label} className={`flex items-center gap-1.5 text-xs ${ok ? 'text-green-600' : 'text-gray-400'}`}>
                      {ok
                        ? <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                        : <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
                      }
                      {rule.label}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Confirm New Password</label>
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} required
              autoComplete="new-password"
              className={`w-full px-4 py-2.5 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition text-sm ${confirm && !matches ? 'border-red-400' : 'border-gray-300'}`}
              placeholder="Confirm your new password" />
            {confirm && !matches && <p className="text-red-500 text-xs mt-1">Passwords do not match</p>}
          </div>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm">{error}</div>
          )}
          <button type="submit" disabled={submitting || !allPassed || !matches || !current}
            className="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold rounded-lg transition text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2">
            {submitting ? 'Updating...' : 'Update Password'}
          </button>
        </form>
      </div>
    </div>
  );
}
