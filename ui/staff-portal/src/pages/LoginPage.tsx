import { useState, useRef, useEffect, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { getErrorMessage } from '../lib/errorHandler';

// ─── Decorative SVG illustration ──────────────────────────────────────────────
function BrandIllustration() {
  return (
    <svg
      viewBox="0 0 480 360"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className="w-full max-w-md opacity-80"
      aria-hidden="true"
    >
      {/* Connection lines */}
      <line x1="240" y1="180" x2="100" y2="80"  stroke="#0066cc" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="240" y1="180" x2="380" y2="80"  stroke="#0066cc" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="240" y1="180" x2="80"  y2="270" stroke="#0066cc" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="240" y1="180" x2="400" y2="270" stroke="#0066cc" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="240" y1="180" x2="240" y2="40"  stroke="#7C3AED" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="240" y1="180" x2="240" y2="320" stroke="#7C3AED" strokeWidth="1.5" strokeOpacity="0.4" />
      <line x1="100" y1="80"  x2="240" y2="40"  stroke="#0066cc" strokeWidth="1"   strokeOpacity="0.25" />
      <line x1="380" y1="80"  x2="240" y2="40"  stroke="#0066cc" strokeWidth="1"   strokeOpacity="0.25" />
      <line x1="80"  y1="270" x2="240" y2="320" stroke="#0066cc" strokeWidth="1"   strokeOpacity="0.25" />
      <line x1="400" y1="270" x2="240" y2="320" stroke="#0066cc" strokeWidth="1"   strokeOpacity="0.25" />
      <line x1="100" y1="80"  x2="80"  y2="270" stroke="#7C3AED" strokeWidth="0.8" strokeOpacity="0.2" />
      <line x1="380" y1="80"  x2="400" y2="270" stroke="#7C3AED" strokeWidth="0.8" strokeOpacity="0.2" />

      {/* Outer nodes */}
      <circle cx="100" cy="80"  r="18" fill="#003087" fillOpacity="0.15" stroke="#0066cc" strokeWidth="1.5" />
      <circle cx="380" cy="80"  r="18" fill="#003087" fillOpacity="0.15" stroke="#0066cc" strokeWidth="1.5" />
      <circle cx="80"  cy="270" r="18" fill="#003087" fillOpacity="0.15" stroke="#0066cc" strokeWidth="1.5" />
      <circle cx="400" cy="270" r="18" fill="#003087" fillOpacity="0.15" stroke="#0066cc" strokeWidth="1.5" />
      <circle cx="240" cy="40"  r="14" fill="#7C3AED" fillOpacity="0.15" stroke="#7C3AED" strokeWidth="1.5" />
      <circle cx="240" cy="320" r="14" fill="#7C3AED" fillOpacity="0.15" stroke="#7C3AED" strokeWidth="1.5" />

      {/* Inner node icons (cross shape = medical) */}
      <rect x="96"  y="76"  width="8" height="2" rx="1" fill="#0066cc" />
      <rect x="99"  y="73"  width="2" height="8" rx="1" fill="#0066cc" />
      <rect x="376" y="76"  width="8" height="2" rx="1" fill="#0066cc" />
      <rect x="379" y="73"  width="2" height="8" rx="1" fill="#0066cc" />
      <rect x="76"  y="266" width="8" height="2" rx="1" fill="#0066cc" />
      <rect x="79"  y="263" width="2" height="8" rx="1" fill="#0066cc" />
      <rect x="396" y="266" width="8" height="2" rx="1" fill="#0066cc" />
      <rect x="399" y="263" width="2" height="8" rx="1" fill="#0066cc" />

      {/* Center node */}
      <circle cx="240" cy="180" r="36" fill="#003087" fillOpacity="0.2" stroke="#0066cc" strokeWidth="2" />
      <circle cx="240" cy="180" r="24" fill="#003087" fillOpacity="0.3" stroke="#0066cc" strokeWidth="1.5" />
      {/* Center "A" */}
      <text x="240" y="186" textAnchor="middle" fontSize="18" fontWeight="800" fill="#0066cc" fontFamily="Inter, sans-serif">A</text>

      {/* Pulse rings */}
      <circle cx="240" cy="180" r="50" stroke="#0066cc" strokeWidth="0.75" strokeOpacity="0.2" fill="none" strokeDasharray="4 4" />
      <circle cx="240" cy="180" r="70" stroke="#0066cc" strokeWidth="0.5"  strokeOpacity="0.12" fill="none" strokeDasharray="3 6" />
    </svg>
  );
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode]   = useState('');
  const [showMfa, setShowMfa]   = useState(false);
  const [showPw, setShowPw]     = useState(false);
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

  const mfaRef = useRef<HTMLInputElement>(null);

  // Auto-focus the MFA input when it appears
  useEffect(() => {
    if (showMfa) mfaRef.current?.focus();
  }, [showMfa]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login({ email, password, mfa_code: showMfa ? mfaCode : undefined });
      navigate('/dashboard');
    } catch (err: any) {
      if (err.response?.data?.mfa_required && !showMfa) {
        setShowMfa(true);
      } else {
        setError(getErrorMessage(err));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen" style={{ backgroundColor: 'var(--bg-primary)' }}>
      {/* ── Left panel — branding ── */}
      <div className="hidden lg:flex lg:w-[60%] flex-col items-center justify-center relative overflow-hidden bg-gradient-to-br from-aethera-900 via-aethera-800 to-[#0a0f1e] p-16">
        {/* Subtle grid overlay */}
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage:
              'linear-gradient(rgba(13,148,148,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(13,148,148,0.3) 1px, transparent 1px)',
            backgroundSize: '40px 40px',
          }}
        />

        <div className="relative z-10 flex flex-col items-center text-center">
          {/* Logo mark */}
          <svg width="64" height="64" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="mb-6 drop-shadow-xl">
            <defs>
              <linearGradient id="loginMarkStaff" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#003087"/>
                <stop offset="100%" stopColor="#0066cc"/>
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="22" fill="url(#loginMarkStaff)"/>
            <path fillRule="evenodd"
              d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
              fill="white"/>
          </svg>

          <h1 className="text-4xl font-extrabold text-white tracking-tight">Aethera AI</h1>
          <p className="mt-2 text-aethera-300 text-lg font-medium">Revenue Cycle Intelligence</p>

          <p className="mt-6 max-w-sm text-aethera-200/70 text-sm leading-relaxed">
            AI-powered billing, coding automation, and denial management — purpose-built for medical billing teams.
          </p>

          {/* Illustration */}
          <div className="mt-12 w-full max-w-sm">
            <BrandIllustration />
          </div>

          {/* Feature pills */}
          <div className="mt-10 flex flex-wrap justify-center gap-2">
            {['Smart Coding', 'Denial Management', 'AR Tracking', 'ERA Processing'].map((f) => (
              <span
                key={f}
                className="rounded-full border border-aethera-600/40 bg-aethera-800/50 px-3 py-1 text-xs font-medium text-aethera-300"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* ── Right panel — form ── */}
      <div className="flex flex-1 flex-col items-center justify-center px-8 py-12">
        {/* Mobile logo */}
        <div className="flex lg:hidden flex-col items-center mb-8">
          <svg width="48" height="48" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="mb-3 drop-shadow-md">
            <defs>
              <linearGradient id="loginMarkStaffMobile" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#003087"/>
                <stop offset="100%" stopColor="#0066cc"/>
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="22" fill="url(#loginMarkStaffMobile)"/>
            <path fillRule="evenodd"
              d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
              fill="white"/>
          </svg>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>Aethera AI</h1>
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Staff Portal</p>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
              {showMfa ? 'Two-factor authentication' : 'Welcome back'}
            </h2>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
              {showMfa
                ? 'Enter the 6-digit code from your authenticator app.'
                : 'Sign in to your Aethera AI account.'}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {/* Error alert */}
            {error && (
              <div className="flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800/40 dark:bg-red-900/20">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" />
                <p className="text-sm text-red-700 dark:text-red-400">{error}</p>
              </div>
            )}

            {!showMfa ? (
              <>
                {/* Email */}
                <div className="relative">
                  <label
                    htmlFor="email"
                    className="mb-1.5 block text-xs font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    Email address
                  </label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className="w-full rounded-lg border px-3.5 py-2.5 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-aethera-600/30"
                    style={{
                      backgroundColor: 'var(--bg-primary)',
                      borderColor: 'var(--border)',
                      color: 'var(--text-primary)',
                    }}
                    placeholder="you@hospital.org"
                  />
                </div>

                {/* Password */}
                <div>
                  <div className="mb-1.5 flex items-center justify-between">
                    <label
                      htmlFor="password"
                      className="block text-xs font-semibold uppercase tracking-wide"
                      style={{ color: 'var(--text-muted)' }}
                    >
                      Password
                    </label>
                    <button
                      type="button"
                      className="text-xs text-aethera-600 hover:text-aethera-700 font-medium"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <div className="relative">
                    <input
                      id="password"
                      type={showPw ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      autoComplete="current-password"
                      className="w-full rounded-lg border px-3.5 py-2.5 pr-10 text-sm transition-colors focus:outline-none focus:ring-2 focus:ring-aethera-600/30"
                      style={{
                        backgroundColor: 'var(--bg-primary)',
                        borderColor: 'var(--border)',
                        color: 'var(--text-primary)',
                      }}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPw((v) => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2"
                      style={{ color: 'var(--text-subtle)' }}
                      tabIndex={-1}
                      aria-label={showPw ? 'Hide password' : 'Show password'}
                    >
                      {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                </div>
              </>
            ) : (
              /* MFA input */
              <div>
                <label
                  htmlFor="mfa"
                  className="mb-1.5 block text-xs font-semibold uppercase tracking-wide"
                  style={{ color: 'var(--text-muted)' }}
                >
                  Authentication code
                </label>
                <input
                  id="mfa"
                  ref={mfaRef}
                  type="text"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  className="w-full rounded-lg border px-3.5 py-2.5 text-center text-2xl font-bold tracking-[0.5em] transition-colors focus:outline-none focus:ring-2 focus:ring-aethera-600/30"
                  style={{
                    backgroundColor: 'var(--bg-primary)',
                    borderColor: 'var(--border)',
                    color: 'var(--text-primary)',
                  }}
                  placeholder="------"
                />
                <button
                  type="button"
                  onClick={() => { setShowMfa(false); setMfaCode(''); setError(''); }}
                  className="mt-2 text-xs text-aethera-600 hover:text-aethera-700 font-medium"
                >
                  &larr; Back to sign in
                </button>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-full py-2.5 text-sm font-semibold text-white transition-all disabled:opacity-50"
              style={{ background: 'linear-gradient(135deg, #003087, #0066cc)', boxShadow: '0 2px 8px rgba(0,48,135,0.30)' }}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                showMfa ? 'Verify' : 'Sign in'
              )}
            </button>
          </form>

          {/* Footer */}
          <p className="mt-8 text-center text-xs" style={{ color: 'var(--text-subtle)' }}>
            © {new Date().getFullYear()} Aethera Healthcare Solutions. All rights reserved.
          </p>
        </div>
      </div>
    </div>
  );
}
