import { useQuery } from '@tanstack/react-query';
import {
  FileText, DollarSign, AlertTriangle, TrendingUp,
  ArrowUpRight, ArrowDownRight, Clock, CheckCircle2, ChevronRight,
} from 'lucide-react';
import api from '../lib/api';
import { safeNumber } from '../lib/apiHelpers';

interface DashboardData {
  practice_name: string;
  total_claims: number;
  claims_submitted_this_month: number;
  total_collected: number;
  collection_rate: number;
  open_denials: number;
  denial_rate: number;
  avg_days_in_ar: number;
  recent_claims: { id: string; claim_number: string; patient_name: string; status: string; amount: number }[];
}

const STATUS: Record<string, { label: string; bg: string; color: string; dot: string }> = {
  submitted:  { label: 'Submitted',  bg: 'rgba(37,99,235,0.08)',  color: '#1d4ed8', dot: '#3b82f6' },
  accepted:   { label: 'Accepted',   bg: 'rgba(5,150,105,0.08)',  color: '#065f46', dot: '#10b981' },
  paid:       { label: 'Paid',       bg: 'rgba(5,150,105,0.10)',  color: '#047857', dot: '#059669' },
  denied:     { label: 'Denied',     bg: 'rgba(220,38,38,0.08)',  color: '#b91c1c', dot: '#ef4444' },
  in_process: { label: 'In Process', bg: 'rgba(217,119,6,0.08)',  color: '#92400e', dot: '#f59e0b' },
};
function statusCfg(s: string) {
  return STATUS[s] ?? { label: s, bg: 'rgba(82,114,164,0.08)', color: '#1a3872', dot: '#7e95ba' };
}

interface StatCardProps {
  icon: React.ElementType;
  iconBg: string; iconColor: string;
  accentColor: string;
  label: string; value: string;
  sub?: string; trend?: number; loading?: boolean;
}

function StatCard({ icon: Icon, iconBg, iconColor, accentColor, label, value, sub, trend, loading }: StatCardProps) {
  if (loading) {
    return (
      <div className="card p-5 h-[110px] animate-pulse" style={{ background: 'var(--bg-secondary)', position: 'relative', overflow: 'hidden' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: 'var(--border)', borderRadius: '4px 0 0 4px' }} />
        <div className="h-4 w-24 rounded mb-3" style={{ background: 'var(--bg-tertiary)' }} />
        <div className="h-7 w-16 rounded" style={{ background: 'var(--bg-tertiary)' }} />
      </div>
    );
  }
  return (
    <div className="card p-5 transition-shadow duration-150 hover:shadow-card-md" style={{ background: 'var(--bg-secondary)', position: 'relative', overflow: 'hidden' }}>
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: 3, background: accentColor, borderRadius: '4px 0 0 4px' }} />
      <div className="flex items-start justify-between mb-3">
        <div className="rounded-lg p-2" style={{ background: iconBg }}>
          <Icon className="h-4 w-4" style={{ color: iconColor }} />
        </div>
        {trend !== undefined && (
          <div className="flex items-center gap-0.5 text-xs font-medium rounded-full px-2 py-0.5"
            style={{ background: trend >= 0 ? 'rgba(5,150,105,0.08)' : 'rgba(220,38,38,0.08)', color: trend >= 0 ? '#059669' : '#dc2626' }}>
            {trend >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
            {Math.abs(trend)}%
          </div>
        )}
      </div>
      <p className="text-xs font-medium mb-1" style={{ color: 'var(--text-subtle)' }}>{label}</p>
      <p className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{value}</p>
      {sub && <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-subtle)' }}>{sub}</p>}
    </div>
  );
}

function SkeletonRow() {
  return (
    <tr>
      {[80, 120, 60, 72].map((w, i) => (
        <td key={i} className="px-5 py-3">
          <div className="h-3 rounded animate-pulse" style={{ background: 'var(--bg-tertiary)', width: w }} />
        </td>
      ))}
    </tr>
  );
}

export function DashboardPage() {
  const { data, isLoading } = useQuery<DashboardData>({
    queryKey: ['provider-dashboard'],
    queryFn: () => api.get('/portal/dashboard').then(r => r.data),
  });

  const collectionPct = (safeNumber(data?.collection_rate) * 100).toFixed(1);
  const denialPct     = (safeNumber(data?.denial_rate) * 100).toFixed(1);

  return (
    <div className="space-y-6">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>
            {data?.practice_name ?? 'Dashboard'}
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--text-subtle)' }}>
            Revenue cycle overview · Updated just now
          </p>
        </div>
        <div className="hidden sm:flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium"
          style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
          <Clock className="h-3.5 w-3.5" />
          Last 30 days
          <ChevronRight className="h-3 w-3" />
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard icon={FileText}      iconBg="rgba(26,56,114,0.08)"  iconColor="#1a3872" accentColor="#1a3872" label="Total Claims"     value={safeNumber(data?.total_claims).toLocaleString()}                    sub={`${safeNumber(data?.claims_submitted_this_month)} this month`} trend={4}  loading={isLoading} />
        <StatCard icon={DollarSign}    iconBg="rgba(201,168,76,0.10)" iconColor="#aa8a38" accentColor="#c9a84c" label="Total Collected"  value={`$${(safeNumber(data?.total_collected)/1000).toFixed(0)}k`}          sub="Net collections YTD"                                           trend={7}  loading={isLoading} />
        <StatCard icon={TrendingUp}    iconBg="rgba(5,150,105,0.08)"  iconColor="#059669" accentColor="#059669" label="Collection Rate" value={`${collectionPct}%`}                                                  sub="Industry avg: 95.1%"                                           trend={1}  loading={isLoading} />
        <StatCard icon={AlertTriangle} iconBg="rgba(220,38,38,0.08)"  iconColor="#dc2626" accentColor="#dc2626" label="Open Denials"    value={safeNumber(data?.open_denials).toLocaleString()}                     sub={`${denialPct}% denial rate`}                                   trend={-3} loading={isLoading} />
      </div>

      {/* AR Days banner */}
      {!isLoading && (
        <div className="rounded-xl p-4 flex items-center justify-between"
          style={{ background: 'linear-gradient(135deg, rgba(10,26,60,0.95) 0%, rgba(26,56,114,0.95) 100%)', border: '1px solid rgba(201,168,76,0.20)' }}>
          <div className="flex items-center gap-4">
            <div className="h-10 w-10 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: 'rgba(201,168,76,0.15)', border: '1px solid rgba(201,168,76,0.25)' }}>
              <Clock className="h-5 w-5" style={{ color: '#c9a84c' }} />
            </div>
            <div>
              <p className="text-xs font-medium" style={{ color: 'rgba(255,255,255,0.5)' }}>Average Days in A/R</p>
              <div className="flex items-baseline gap-2">
                <p className="text-2xl font-bold text-white">{safeNumber(data?.avg_days_in_ar).toFixed(0)}</p>
                <span className="text-sm" style={{ color: 'rgba(255,255,255,0.4)' }}>days</span>
              </div>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-6">
            <div className="text-center">
              <p className="text-lg font-bold text-white">0–30</p>
              <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.4)' }}>Target range</p>
            </div>
            <div className="h-10 w-px" style={{ background: 'rgba(255,255,255,0.08)' }} />
            <div className="text-center">
              <p className="text-lg font-bold text-emerald-400">Healthy</p>
              <p className="text-[10px]" style={{ color: 'rgba(255,255,255,0.4)' }}>AR status</p>
            </div>
          </div>
        </div>
      )}

      {/* Recent Claims */}
      <div className="card overflow-hidden" style={{ background: 'var(--bg-secondary)' }}>
        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-4 w-4" style={{ color: '#c9a84c' }} />
            <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Recent Claims</h2>
          </div>
          <button className="text-xs font-medium flex items-center gap-1" style={{ color: '#c9a84c' }}>
            View all <ChevronRight className="h-3 w-3" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                {['Claim #', 'Patient', 'Amount', 'Status'].map(h => (
                  <th key={h} className="px-5 py-3 text-left text-[10px] font-bold uppercase tracking-wider" style={{ color: 'var(--text-subtle)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading
                ? Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} />)
                : (Array.isArray(data?.recent_claims) ? data!.recent_claims : []).map(claim => {
                    const s = statusCfg(claim.status ?? '');
                    return (
                      <tr key={claim.id} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}
                        onMouseEnter={e => { (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-tertiary)'; }}
                        onMouseLeave={e => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}
                      >
                        <td className="px-5 py-3.5"><span className="text-xs font-semibold" style={{ color: '#1a3872' }}>{claim.claim_number ?? '—'}</span></td>
                        <td className="px-5 py-3.5 text-xs" style={{ color: 'var(--text-primary)' }}>{claim.patient_name ?? '—'}</td>
                        <td className="px-5 py-3.5 text-xs font-medium" style={{ color: 'var(--text-primary)' }}>${safeNumber(claim.amount).toLocaleString()}</td>
                        <td className="px-5 py-3.5">
                          <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold" style={{ background: s.bg, color: s.color }}>
                            <span className="h-1.5 w-1.5 rounded-full flex-shrink-0" style={{ background: s.dot }} />
                            {s.label}
                          </span>
                        </td>
                      </tr>
                    );
                  })
              }
            </tbody>
          </table>
        </div>

        {!isLoading && !(data?.recent_claims?.length) && (
          <div className="flex flex-col items-center justify-center py-12" style={{ color: 'var(--text-subtle)' }}>
            <FileText className="h-8 w-8 mb-3 opacity-30" />
            <p className="text-sm">No recent claims found</p>
          </div>
        )}
      </div>
    </div>
  );
}
