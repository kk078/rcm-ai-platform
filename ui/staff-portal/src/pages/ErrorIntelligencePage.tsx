import { useState, useEffect } from 'react';
import { AlertOctagon, AlertTriangle, CheckCircle2, Info, RefreshCw,
         ShieldAlert, Bug, Cpu, ChevronDown, ChevronRight,
         Clock, User, Globe, Layers, Lightbulb, ListChecks,
         X, RotateCcw, CheckCheck, Search, Zap, Wrench } from 'lucide-react';
import api from '../lib/api';

// ── Types ─────────────────────────────────────────────────────────────────
interface ErrorStats {
  total: number; unresolved: number; critical: number; high: number;
  medium: number; low: number; last_24h: number; security_related: number;
  auto_patched: number;
}

interface AiAnalysis {
  severity: string; root_cause: string; suggested_fix: string;
  affected_area: string; debug_steps: string[]; is_security_related: boolean;
  estimated_impact: string; confidence: string;
}

interface ErrorSummary {
  id: string; error_type: string; message: string;
  request_path: string | null; request_method: string | null;
  status_code: number | null; severity: string; analysis_status: string;
  resolved: boolean; occurrence_count: number; created_at: string;
  affected_area: string | null; root_cause: string | null;
  patch_applied: boolean; patch_applied_at: string | null;
}

interface ErrorDetail extends ErrorSummary {
  stack_trace: string; user_id: string | null; sentry_event_id: string | null;
  ai_analysis: AiAnalysis | null; resolved_at: string | null;
  patch_backup_path: string | null; patch_diff: string | null; patch_error: string | null;
}

// ── Severity config ────────────────────────────────────────────────────────
const SEV = {
  critical: { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', icon: AlertOctagon, label: 'Critical' },
  high:     { color: '#f97316', bg: 'rgba(249,115,22,0.12)', icon: AlertTriangle, label: 'High' },
  medium:   { color: '#eab308', bg: 'rgba(234,179,8,0.12)', icon: Info, label: 'Medium' },
  low:      { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', icon: CheckCircle2, label: 'Low' },
  unknown:  { color: '#94a3b8', bg: 'rgba(148,163,184,0.12)', icon: Bug, label: 'Unknown' },
};
function sev(s: string) { return SEV[s as keyof typeof SEV] || SEV.unknown; }

// ── Stat card ──────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, color, icon: Icon }:
  { label: string; value: number; sub?: string; color: string; icon: any }) {
  return (
    <div className="rounded-xl border p-4 flex items-start gap-3"
      style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border)' }}>
      <div className="rounded-lg p-2" style={{ background: color + '22' }}>
        <Icon className="h-5 w-5" style={{ color }} />
      </div>
      <div>
        <p className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{value}</p>
        <p className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{label}</p>
        {sub && <p className="text-xs mt-0.5" style={{ color }}>{sub}</p>}
      </div>
    </div>
  );
}

// ── Severity badge ─────────────────────────────────────────────────────────
function SevBadge({ severity }: { severity: string }) {
  const s = sev(severity);
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: s.bg, color: s.color }}>
      <s.icon className="h-3 w-3" />
      {s.label}
    </span>
  );
}

// ── Status badge ───────────────────────────────────────────────────────────
function StatusBadge({ status, resolved }: { status: string; resolved: boolean }) {
  if (resolved) return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>
      <CheckCheck className="h-3 w-3" /> Resolved
    </span>
  );
  if (status === 'analyzing') return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1' }}>
      <Cpu className="h-3 w-3 animate-spin" /> Analyzing…
    </span>
  );
  if (status === 'complete') return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: 'rgba(34,197,94,0.08)', color: '#4ade80' }}>
      <Zap className="h-3 w-3" /> AI Ready
    </span>
  );
  return (
    <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
      style={{ background: 'rgba(148,163,184,0.12)', color: '#94a3b8' }}>
      <Clock className="h-3 w-3" /> Pending
    </span>
  );
}

// ── Detail panel ───────────────────────────────────────────────────────────
function DetailPanel({ error, onClose, onResolve, onReanalyze, onApplyFix, applyingFix }:
  { error: ErrorDetail; onClose: () => void;
    onResolve: (id: string) => void; onReanalyze: (id: string) => void;
    onApplyFix: (id: string, dryRun: boolean) => void; applyingFix: boolean }) {
  const [stackOpen, setStackOpen] = useState(false);
  const [diffOpen, setDiffOpen] = useState(false);
  const a = error.ai_analysis;

  return (
    <div className="fixed inset-y-0 right-0 w-[520px] z-50 flex flex-col shadow-2xl"
      style={{ background: 'var(--bg-secondary)', borderLeft: '1px solid var(--border)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b shrink-0"
        style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2">
          <SevBadge severity={error.severity} />
          <StatusBadge status={error.analysis_status} resolved={error.resolved} />
          {error.patch_applied && (
            <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>
              <Wrench className="h-3 w-3" /> Patched
            </span>
          )}
        </div>
        <button onClick={onClose} className="rounded-lg p-1.5 hover:bg-[var(--bg-tertiary)]">
          <X className="h-4 w-4" style={{ color: 'var(--text-muted)' }} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {/* Error summary */}
        <div>
          <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{error.error_type}</p>
          <p className="text-xs mt-1 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            {error.message}
          </p>
        </div>

        {/* Meta */}
        <div className="grid grid-cols-2 gap-2 text-xs">
          {error.request_method && error.request_path && (
            <div className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <Globe className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate font-mono">{error.request_method} {error.request_path}</span>
            </div>
          )}
          {error.status_code && (
            <div className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <Layers className="h-3.5 w-3.5 shrink-0" />
              <span>HTTP {error.status_code}</span>
            </div>
          )}
          {error.user_id && (
            <div className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <User className="h-3.5 w-3.5 shrink-0" />
              <span className="font-mono truncate">{error.user_id.slice(0, 8)}…</span>
            </div>
          )}
          <div className="flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
            <Clock className="h-3.5 w-3.5 shrink-0" />
            <span>{new Date(error.created_at).toLocaleString()}</span>
          </div>
          {error.occurrence_count > 1 && (
            <div className="flex items-center gap-1.5 col-span-2" style={{ color: '#f97316' }}>
              <RefreshCw className="h-3.5 w-3.5 shrink-0" />
              <span>Occurred {error.occurrence_count}× total</span>
            </div>
          )}
        </div>

        {/* AI Analysis */}
        {a ? (
          <div className="rounded-xl border p-4 space-y-3"
            style={{ background: 'var(--bg-primary)', borderColor: 'var(--border)' }}>
            <div className="flex items-center gap-2">
              <Cpu className="h-4 w-4" style={{ color: '#6366f1' }} />
              <p className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>AI Analysis</p>
              <span className="ml-auto text-xs px-1.5 py-0.5 rounded"
                style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1' }}>
                {a.confidence} confidence
              </span>
            </div>

            {/* Root cause */}
            <div>
              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>ROOT CAUSE</p>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>{a.root_cause}</p>
            </div>

            {/* Impact */}
            <div>
              <p className="text-xs font-semibold mb-1" style={{ color: 'var(--text-muted)' }}>IMPACT</p>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>{a.estimated_impact}</p>
            </div>

            {/* Suggested fix */}
            <div className="rounded-lg p-3" style={{ background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)' }}>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Lightbulb className="h-3.5 w-3.5" style={{ color: '#4ade80' }} />
                <p className="text-xs font-semibold" style={{ color: '#4ade80' }}>SUGGESTED FIX</p>
              </div>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--text-primary)' }}>{a.suggested_fix}</p>
            </div>

            {/* Debug steps */}
            {a.debug_steps?.length > 0 && (
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <ListChecks className="h-3.5 w-3.5" style={{ color: 'var(--text-muted)' }} />
                  <p className="text-xs font-semibold" style={{ color: 'var(--text-muted)' }}>DEBUG STEPS</p>
                </div>
                <ol className="space-y-1.5">
                  {a.debug_steps.map((step, i) => (
                    <li key={i} className="flex gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                      <span className="rounded-full bg-[var(--bg-tertiary)] h-5 w-5 flex items-center justify-center text-xs shrink-0 font-bold"
                        style={{ color: '#6366f1' }}>{i + 1}</span>
                      <span className="leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            )}

            {/* Security flag */}
            {a.is_security_related && (
              <div className="flex items-center gap-2 rounded-lg p-2.5"
                style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
                <ShieldAlert className="h-4 w-4 shrink-0" style={{ color: '#ef4444' }} />
                <p className="text-xs font-semibold" style={{ color: '#ef4444' }}>
                  Security-related — escalate immediately
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-xl border p-4 text-center" style={{ background: 'var(--bg-primary)', borderColor: 'var(--border)' }}>
            {error.analysis_status === 'analyzing' ? (
              <>
                <Cpu className="h-6 w-6 mx-auto mb-2 animate-spin" style={{ color: '#6366f1' }} />
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>AI is analyzing this error…</p>
              </>
            ) : (
              <>
                <Bug className="h-6 w-6 mx-auto mb-2" style={{ color: 'var(--text-subtle)' }} />
                <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No analysis yet.</p>
              </>
            )}
          </div>
        )}

        {/* Patch result section */}
        {(error.patch_applied || error.patch_error) && (
          <div className="rounded-xl border overflow-hidden"
            style={{ borderColor: error.patch_applied ? 'rgba(99,102,241,0.3)' : 'rgba(239,68,68,0.3)' }}>
            <div className="px-4 py-3 flex items-center gap-2"
              style={{ background: error.patch_applied ? 'rgba(99,102,241,0.08)' : 'rgba(239,68,68,0.08)' }}>
              <Wrench className="h-4 w-4 shrink-0"
                style={{ color: error.patch_applied ? '#818cf8' : '#ef4444' }} />
              <p className="text-xs font-semibold"
                style={{ color: error.patch_applied ? '#818cf8' : '#ef4444' }}>
                {error.patch_applied ? 'AUTO-PATCH APPLIED' : 'AUTO-PATCH FAILED'}
              </p>
              {error.patch_applied_at && (
                <span className="ml-auto text-xs" style={{ color: 'var(--text-muted)' }}>
                  {new Date(error.patch_applied_at).toLocaleString()}
                </span>
              )}
            </div>

            <div className="px-4 py-3 space-y-2"
              style={{ background: 'var(--bg-primary)' }}>
              {error.patch_error && (
                <p className="text-xs font-mono leading-relaxed" style={{ color: '#ef4444' }}>
                  {error.patch_error}
                </p>
              )}
              {error.patch_backup_path && (
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  Backup: <span className="font-mono">{error.patch_backup_path}</span>
                </p>
              )}

              {/* Collapsible diff viewer */}
              {error.patch_diff && (
                <>
                  <button
                    className="flex items-center gap-2 text-xs font-semibold w-full text-left"
                    style={{ color: 'var(--text-muted)' }}
                    onClick={() => setDiffOpen(o => !o)}
                  >
                    {diffOpen
                      ? <ChevronDown className="h-3.5 w-3.5" />
                      : <ChevronRight className="h-3.5 w-3.5" />}
                    VIEW DIFF
                  </button>
                  {diffOpen && (
                    <pre
                      className="text-xs overflow-x-auto leading-relaxed rounded-lg p-3"
                      style={{ background: '#0f172a', color: '#94a3b8', maxHeight: 280 }}
                    >
                      {error.patch_diff.split('\n').map((line, i) => {
                        let color = '#94a3b8';
                        if (line.startsWith('+') && !line.startsWith('+++')) color = '#4ade80';
                        else if (line.startsWith('-') && !line.startsWith('---')) color = '#f87171';
                        else if (line.startsWith('@@')) color = '#818cf8';
                        return <span key={i} style={{ color, display: 'block' }}>{line}</span>;
                      })}
                    </pre>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* Stack trace */}
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
          <button
            className="flex items-center gap-2 w-full px-4 py-3 text-xs font-semibold"
            style={{ background: 'var(--bg-tertiary)', color: 'var(--text-muted)' }}
            onClick={() => setStackOpen(o => !o)}
          >
            {stackOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            STACK TRACE
          </button>
          {stackOpen && (
            <pre className="p-4 text-xs overflow-x-auto leading-relaxed"
              style={{ color: '#94a3b8', background: '#0f172a', maxHeight: 300 }}>
              {error.stack_trace || 'No stack trace available.'}
            </pre>
          )}
        </div>
      </div>

      {/* Actions */}
      {!error.resolved && (
        <div className="p-4 border-t space-y-2 shrink-0" style={{ borderColor: 'var(--border)' }}>
          {/* Apply Fix row — only shown when AI analysis is complete and non-security */}
          {a && !a.is_security_related && (
            <div className="flex gap-2">
              <button
                onClick={() => onApplyFix(error.id, true)}
                disabled={applyingFix}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border disabled:opacity-50"
                style={{ borderColor: 'rgba(99,102,241,0.4)', color: '#818cf8', background: 'rgba(99,102,241,0.08)' }}>
                <Wrench className="h-3.5 w-3.5" />
                Dry Run
              </button>
              <button
                onClick={() => onApplyFix(error.id, false)}
                disabled={applyingFix}
                className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold text-white disabled:opacity-50"
                style={{ background: applyingFix ? '#6366f1aa' : 'linear-gradient(135deg, #6366f1, #4f46e5)' }}>
                {applyingFix
                  ? <><Cpu className="h-3.5 w-3.5 animate-spin" /> Patching…</>
                  : <><Wrench className="h-4 w-4" /> Apply AI Fix</>
                }
              </button>
            </div>
          )}

          {/* Resolve / Re-analyze row */}
          <div className="flex gap-2">
            <button
              onClick={() => onReanalyze(error.id)}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border"
              style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-tertiary)' }}>
              <RotateCcw className="h-3.5 w-3.5" /> Re-analyze
            </button>
            <button
              onClick={() => onResolve(error.id)}
              className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm font-semibold text-white"
              style={{ background: 'linear-gradient(135deg, #22c55e, #16a34a)' }}>
              <CheckCheck className="h-4 w-4" /> Mark Resolved
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────
export function ErrorIntelligencePage() {
  const [stats, setStats] = useState<ErrorStats | null>(null);
  const [errors, setErrors] = useState<ErrorSummary[]>([]);
  const [selected, setSelected] = useState<ErrorDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [applyingFix, setApplyingFix] = useState(false);

  // Filters
  const [filterSeverity, setFilterSeverity] = useState('');
  const [filterResolved, setFilterResolved] = useState<'' | 'false' | 'true'>('false');
  const [search, setSearch] = useState('');

  async function load(showRefresh = false) {
    if (showRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (filterSeverity) params.severity = filterSeverity;
      if (filterResolved !== '') params.resolved = filterResolved;

      const [statsRes, errorsRes] = await Promise.all([
        api.get('/errors/stats'),
        api.get('/errors', { params }),
      ]);
      setStats(statsRes.data);
      setErrors(errorsRes.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  async function loadDetail(id: string) {
    try {
      const { data } = await api.get(`/errors/${id}`);
      setSelected(data);
    } catch (e) { console.error(e); }
  }

  async function handleResolve(id: string) {
    await api.patch(`/errors/${id}/resolve`, {});
    setSelected(null);
    load(true);
  }

  async function handleReanalyze(id: string) {
    await api.post(`/errors/${id}/reanalyze`);
    loadDetail(id);
    load(true);
  }

  async function handleApplyFix(id: string, dryRun: boolean) {
    setApplyingFix(true);
    try {
      await api.post(`/errors/${id}/apply-fix`, null, { params: { dry_run: dryRun } });
      // Refresh detail to show patch result
      await loadDetail(id);
      load(true);
    } catch (e) {
      console.error('apply-fix failed', e);
    } finally {
      setApplyingFix(false);
    }
  }

  useEffect(() => { load(); }, [filterSeverity, filterResolved]);

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const t = setInterval(() => load(true), 30_000);
    return () => clearInterval(t);
  }, [filterSeverity, filterResolved]);

  const filtered = search
    ? errors.filter(e =>
        e.error_type.toLowerCase().includes(search.toLowerCase()) ||
        e.message.toLowerCase().includes(search.toLowerCase()) ||
        e.request_path?.toLowerCase().includes(search.toLowerCase()))
    : errors;

  if (loading) return (
    <div className="flex items-center justify-center h-64" style={{ color: 'var(--text-muted)' }}>
      <Cpu className="h-6 w-6 animate-spin mr-2" /> Loading Error Intelligence…
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
            Error Intelligence
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-muted)' }}>
            AI-powered automatic error diagnosis — every unhandled exception analyzed in real time
          </p>
        </div>
        <button
          onClick={() => load(true)}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium border"
          style={{ borderColor: 'var(--border)', color: 'var(--text-muted)', background: 'var(--bg-secondary)' }}>
          <RefreshCw className={['h-3.5 w-3.5', refreshing ? 'animate-spin' : ''].join(' ')} />
          Refresh
        </button>
      </div>

      {/* Stat cards — 5 cards including Auto Patched */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <StatCard label="Unresolved" value={stats.unresolved}
            sub={`of ${stats.total} total`} color="#6366f1" icon={Bug} />
          <StatCard label="Critical / High" value={stats.critical + stats.high}
            sub="needs immediate attention" color="#ef4444" icon={AlertOctagon} />
          <StatCard label="Last 24 hours" value={stats.last_24h}
            sub="new errors" color="#f97316" icon={Clock} />
          <StatCard label="Security Flags" value={stats.security_related}
            sub={stats.security_related > 0 ? 'escalate now' : 'none detected'} color="#eab308" icon={ShieldAlert} />
          <StatCard label="Auto Patched" value={stats.auto_patched}
            sub="by AI patcher" color="#818cf8" icon={Wrench} />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-2.5 h-3.5 w-3.5" style={{ color: 'var(--text-subtle)' }} />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search errors…"
            className="w-full rounded-lg border pl-8 pr-3 py-2 text-sm"
            style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)', outline: 'none' }}
          />
        </div>

        <select value={filterSeverity} onChange={e => setFilterSeverity(e.target.value)}
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        <select value={filterResolved} onChange={e => setFilterResolved(e.target.value as any)}
          className="rounded-lg border px-3 py-2 text-sm"
          style={{ background: 'var(--bg-secondary)', borderColor: 'var(--border)', color: 'var(--text-primary)' }}>
          <option value="false">Open only</option>
          <option value="true">Resolved only</option>
          <option value="">All</option>
        </select>
      </div>

      {/* Error list */}
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border)' }}>
        {filtered.length === 0 ? (
          <div className="py-16 text-center">
            <CheckCircle2 className="h-8 w-8 mx-auto mb-3" style={{ color: '#22c55e' }} />
            <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
              No errors match the current filters
            </p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b" style={{ background: 'var(--bg-tertiary)', borderColor: 'var(--border)' }}>
                {['Severity', 'Error', 'Endpoint', 'AI Diagnosis', 'Status', 'Patch', 'When'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-subtle)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((err, i) => (
                <tr
                  key={err.id}
                  onClick={() => loadDetail(err.id)}
                  className="border-b cursor-pointer hover:bg-[var(--bg-tertiary)] transition-colors"
                  style={{
                    borderColor: 'var(--border)',
                    opacity: err.resolved ? 0.6 : 1,
                    background: i % 2 === 0 ? 'var(--bg-secondary)' : 'var(--bg-primary)',
                  }}>
                  <td className="px-4 py-3"><SevBadge severity={err.severity} /></td>
                  <td className="px-4 py-3 max-w-xs">
                    <p className="font-mono font-semibold text-xs truncate" style={{ color: 'var(--text-primary)' }}>
                      {err.error_type}
                    </p>
                    <p className="text-xs truncate mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      {err.message}
                    </p>
                  </td>
                  <td className="px-4 py-3">
                    {err.request_path ? (
                      <span className="font-mono text-xs" style={{ color: 'var(--text-muted)' }}>
                        {err.request_method} {err.request_path}
                      </span>
                    ) : <span style={{ color: 'var(--text-subtle)' }}>—</span>}
                  </td>
                  <td className="px-4 py-3 max-w-xs">
                    {err.root_cause ? (
                      <p className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{err.root_cause}</p>
                    ) : (
                      <span className="text-xs" style={{ color: 'var(--text-subtle)' }}>
                        {err.analysis_status === 'analyzing' ? 'Analyzing…' : 'Pending'}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={err.analysis_status} resolved={err.resolved} />
                  </td>
                  <td className="px-4 py-3">
                    {err.patch_applied ? (
                      <span className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold"
                        style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>
                        <Wrench className="h-3 w-3" /> Patched
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-subtle)', fontSize: '0.75rem' }}>—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs whitespace-nowrap" style={{ color: 'var(--text-subtle)' }}>
                    {new Date(err.created_at).toLocaleDateString()}{' '}
                    {new Date(err.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Detail panel */}
      {selected && (
        <>
          <div className="fixed inset-0 z-40 bg-black/40" onClick={() => setSelected(null)} />
          <DetailPanel
            error={selected}
            onClose={() => setSelected(null)}
            onResolve={handleResolve}
            onReanalyze={handleReanalyze}
            onApplyFix={handleApplyFix}
            applyingFix={applyingFix}
          />
        </>
      )}
    </div>
  );
}
