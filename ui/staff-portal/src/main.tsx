import { StrictMode } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as Sentry from '@sentry/react';
import { AuthProvider } from './hooks/useAuth';
import { ThemeProvider } from './components/ThemeProvider';
import { ErrorOverlay } from './components/ErrorOverlay';
import App from './App';
import './index.css';

// ── Sentry ────────────────────────────────────────────────────────────────
const SENTRY_DSN = import.meta.env.VITE_SENTRY_DSN;
if (SENTRY_DSN) {
  Sentry.init({
    dsn: SENTRY_DSN,
    environment: import.meta.env.MODE,
    release: 'aethera-ai-staff@1.0.0',
    integrations: [
      Sentry.browserTracingIntegration(),
      Sentry.replayIntegration({
        maskAllText: true,
        blockAllMedia: true,
      }),
    ],
    tracesSampleRate: 0.2,
    replaysSessionSampleRate: 0.05,
    replaysOnErrorSampleRate: 0.5,
    beforeSend(event) {
      if (event.request?.data) {
        const sensitive = ['password', 'ssn', 'dob', 'tin', 'credit_card'];
        for (const key of sensitive) {
          if (event.request.data[key]) event.request.data[key] = '[REDACTED]';
        }
      }
      return event;
    },
  });
}

// ── Global JS Error Capture → Error Intelligence ──────────────────────────
const _PHI_RE = [
  /\b\d{3}-\d{2}-\d{4}\b/g,
  /(password|ssn|dob|tin|mrn|npi)\s*[:=]\s*\S+/gi,
];
function _sanitizeForCapture(s: string, maxLen = 2000): string {
  let out = String(s || '').slice(0, maxLen * 2);
  for (const re of _PHI_RE) out = out.replace(re, '[REDACTED]');
  return out.slice(0, maxLen);
}
function _getToken(): string | null {
  const keys = ['access_token', 'aethera_token', 'auth_token', 'token'];
  for (const k of keys) {
    const v = localStorage.getItem(k) ?? sessionStorage.getItem(k);
    if (v && v.split('.').length === 3) return v;
  }
  return null;
}
function _captureJsError(errorType: string, message: string, stack: string) {
  try {
    const token = _getToken();
    if (!token) return;
    fetch('/api/v1/errors/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        error_type: errorType,
        message: _sanitizeForCapture(message),
        stack_trace: _sanitizeForCapture(stack, 6000),
        url: window.location.pathname,
        source: 'frontend',
      }),
      keepalive: true,
    }).catch(() => {});
  } catch { /* never throw from error capture */ }
}
const _origOnError = window.onerror;
window.onerror = (msg, _src, _line, _col, err) => {
  _captureJsError(err?.name ?? 'JavaScriptError', String(msg), err?.stack ?? String(msg));
  return typeof _origOnError === 'function'
    ? _origOnError.call(window, msg, _src, _line, _col, err) as boolean
    : false;
};
window.addEventListener('unhandledrejection', (ev) => {
  const reason = ev.reason;
  _captureJsError(
    reason?.name ?? 'UnhandledPromiseRejection',
    reason?.message ?? String(reason),
    reason?.stack ?? '',
  );
});

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const root = document.getElementById('root')!;

ReactDOM.createRoot(root).render(
  <StrictMode>
    <Sentry.ErrorBoundary
      fallback={({ error: _err, resetError }) => (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', minHeight: '100vh', padding: '2rem',
          fontFamily: 'system-ui, sans-serif', background: '#0f172a', color: '#f1f5f9',
        }}>
          <h1 style={{ fontSize: '1.5rem', marginBottom: '0.5rem' }}>Something went wrong</h1>
          <p style={{ color: '#94a3b8', marginBottom: '1.5rem', maxWidth: 400, textAlign: 'center' }}>
            An unexpected error occurred. Our team has been automatically notified and is investigating.
          </p>
          {SENTRY_DSN && (
            <p style={{ color: '#64748b', fontSize: '0.8rem', marginBottom: '1rem' }}>
              Error ID: {Sentry.lastEventId()}
            </p>
          )}
          <button
            onClick={resetError}
            style={{
              padding: '0.6rem 1.5rem', background: '#6366f1', color: '#fff',
              border: 'none', borderRadius: '0.5rem', cursor: 'pointer', fontSize: '0.9rem',
            }}
          >
            Try again
          </button>
        </div>
      )}
    >
      <BrowserRouter>
        <QueryClientProvider client={queryClient}>
          <ThemeProvider>
            <AuthProvider>
              <App />
              <ErrorOverlay />
            </AuthProvider>
          </ThemeProvider>
        </QueryClientProvider>
      </BrowserRouter>
    </Sentry.ErrorBoundary>
  </StrictMode>
);
