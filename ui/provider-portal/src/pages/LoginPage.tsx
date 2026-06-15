import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { getErrorMessage } from '../lib/errorHandler';
import { Eye, EyeOff, ShieldCheck, ArrowRight, Activity } from 'lucide-react';

function EcgLine() {
  return (
    <svg viewBox="0 0 900 100" preserveAspectRatio="none" className="w-full" style={{ height: '70px' }} aria-hidden="true">
      <path
        className="ecg-path"
        d="M0,50 L60,50 L70,50 L80,15 L90,85 L100,50 L120,50 L180,50 L190,50 L200,15 L210,85 L220,50 L240,50 L300,50 L310,50 L320,15 L330,85 L340,50 L360,50 L420,50 L430,50 L440,15 L450,85 L460,50 L480,50 L540,50 L550,50 L560,15 L570,85 L580,50 L600,50 L660,50 L670,50 L680,15 L690,85 L700,50 L720,50 L780,50 L790,50 L800,15 L810,85 L820,50 L900,50"
        fill="none"
        stroke="rgba(201,168,76,0.55)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}



export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login({ email, password });
      navigate('/dashboard');
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* LEFT PANEL */}
      <div
        className="hidden lg:flex lg:w-[55%] flex-col justify-between relative overflow-hidden"
        style={{ background: '#f5f5f7' }}
      >
        {/* Logo */}
        <div className="relative z-10 p-10">
          <div className="flex items-center gap-3">
            <svg width="40" height="40" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <linearGradient id="providerLoginMark" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0%" stopColor="#003087"/>
                  <stop offset="100%" stopColor="#0066cc"/>
                </linearGradient>
              </defs>
              <rect width="100" height="100" rx="22" fill="url(#providerLoginMark)"/>
              <path fillRule="evenodd"
                d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
                fill="white"/>
            </svg>
            <div>
              <p className="font-bold text-sm" style={{ color: '#1d1d1f' }}>Aethera Healthcare</p>
              <p className="text-xs" style={{ color: '#6e6e73' }}>Provider Portal</p>
            </div>
          </div>
        </div>

        {/* Hero */}
        <div className="relative z-10 px-10 pb-4 flex-1 flex flex-col justify-center">
          <div className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 mb-6 w-fit" style={{ background: 'rgba(0,48,135,0.08)', border: '1px solid rgba(0,48,135,0.18)' }}>
            <Activity className="h-3.5 w-3.5" style={{ color: '#003087' }} />
            <span className="text-xs font-medium" style={{ color: '#003087' }}>Real-time revenue intelligence</span>
          </div>

          <h1 className="text-4xl xl:text-5xl font-bold leading-tight mb-4 animate-fade-up" style={{ animationDelay: '0.1s', opacity: 0, color: '#1d1d1f' }}>
            Your practice,
            <br />
            <span style={{ color: '#003087' }}>fully optimized.</span>
          </h1>

          <p className="text-base mb-10 animate-fade-up" style={{ color: '#6e6e73', animationDelay: '0.2s', opacity: 0, maxWidth: '380px', lineHeight: 1.7 }}>
            AI-powered revenue cycle management built for physicians, physician groups, and health systems.
          </p>

          <div className="grid grid-cols-3 gap-3 mb-10">
            <div className="animate-fade-up rounded-2xl px-4 py-4" style={{ animationDelay: '0.3s', opacity: 0, background: '#ffffff', border: '1px solid #d2d2d7' }}>
              <p className="text-xl font-bold leading-tight" style={{ color: '#003087' }}>98.4%</p>
              <p className="text-xs mt-0.5" style={{ color: '#6e6e73' }}>Clean claim rate</p>
            </div>
            <div className="animate-fade-up rounded-2xl px-4 py-4" style={{ animationDelay: '0.4s', opacity: 0, background: '#ffffff', border: '1px solid #d2d2d7' }}>
              <p className="text-xl font-bold leading-tight" style={{ color: '#003087' }}>12 days</p>
              <p className="text-xs mt-0.5" style={{ color: '#6e6e73' }}>Avg. AR days</p>
            </div>
            <div className="animate-fade-up rounded-2xl px-4 py-4" style={{ animationDelay: '0.5s', opacity: 0, background: '#ffffff', border: '1px solid #d2d2d7' }}>
              <p className="text-xl font-bold leading-tight" style={{ color: '#003087' }}>$0 lost</p>
              <p className="text-xs mt-0.5" style={{ color: '#6e6e73' }}>To coding errors</p>
            </div>
          </div>
        </div>

        {/* Trust bar */}
        <div className="relative z-10">
          <div className="px-6 opacity-40"><EcgLine /></div>
          <div className="flex items-center justify-between px-10 py-4" style={{ borderTop: '1px solid #d2d2d7' }}>
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4" style={{ color: '#003087' }} />
              <span className="text-xs" style={{ color: '#6e6e73' }}>HIPAA Compliant</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              <span className="text-xs" style={{ color: '#6e6e73' }}>SOC 2 Type II</span>
            </div>
            <span className="text-xs" style={{ color: '#86868b' }}>256-bit encryption</span>
          </div>
        </div>
      </div>

      {/* RIGHT PANEL */}
      <div className="flex-1 flex flex-col items-center justify-center px-6 py-12 bg-white">
        {/* Mobile logo */}
        <div className="lg:hidden mb-10 flex flex-col items-center">
          <svg width="48" height="48" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="mb-3">
            <defs>
              <linearGradient id="providerLoginMobile" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0%" stopColor="#003087"/>
                <stop offset="100%" stopColor="#0066cc"/>
              </linearGradient>
            </defs>
            <rect width="100" height="100" rx="22" fill="url(#providerLoginMobile)"/>
            <path fillRule="evenodd"
              d="M 50 10 L 87 90 L 75 90 L 65 64 L 35 64 L 25 90 L 13 90 Z M 50 24 L 62 58 L 38 58 Z"
              fill="white"/>
          </svg>
          <p className="font-bold text-lg" style={{ color: '#0a1a3c' }}>Aethera Healthcare</p>
          <p className="text-sm" style={{ color: '#5272a4' }}>Provider Portal</p>
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="text-3xl font-bold" style={{ color: '#0a1a3c' }}>Physician Sign In</h2>
            <p className="mt-2 text-sm" style={{ color: '#5272a4' }}>Access your practice revenue dashboard</p>
          </div>

          {error && (
            <div className="mb-5 rounded-lg px-4 py-3 text-sm" style={{ background: '#fef2f2', border: '1px solid #fecaca', color: '#b91c1c' }}>
              {typeof error === 'string' ? error : 'Authentication failed. Please try again.'}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider mb-1.5" style={{ color: '#1a3872' }}>Email Address</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" placeholder="physician@practice.org" className="input-field" />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-semibold uppercase tracking-wider" style={{ color: '#1a3872' }}>Password</label>
                <button type="button" className="text-xs font-medium" style={{ color: '#003087' }}>Forgot password?</button>
              </div>
              <div className="relative">
                <input type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" className="input-field pr-10" />
                <button type="button" onClick={() => setShowPw(!showPw)} className="absolute right-3 top-1/2 -translate-y-1/2" style={{ color: '#7e95ba' }} tabIndex={-1}>
                  {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="group w-full flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold text-white transition-all duration-200 disabled:opacity-60"
              style={{ background: 'linear-gradient(135deg, #003087 0%, #0066cc 100%)', boxShadow: '0 4px 14px rgba(0,48,135,0.30)' }}
            >
              {loading ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Authenticating...
                </>
              ) : (
                <>Sign in to Portal <ArrowRight className="h-4 w-4 group-hover:translate-x-0.5 transition-transform" /></>
              )}
            </button>
          </form>

          <div className="mt-8 pt-6" style={{ borderTop: '1px solid #eef1f8' }}>
            <div className="flex items-center justify-center gap-6">
              <div className="flex items-center gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5" style={{ color: '#003087' }} />
                <span className="text-xs" style={{ color: '#6e6e73' }}>HIPAA Compliant</span>
              </div>
              <div className="h-4 w-px" style={{ background: '#eef1f8' }} />
              <div className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                <span className="text-xs" style={{ color: '#6e6e73' }}>256-bit TLS</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
