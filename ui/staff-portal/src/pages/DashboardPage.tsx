import { useQuery } from '@tanstack/react-query';
import {
  FileText, TrendingUp, DollarSign, Banknote, AlertTriangle,
  BarChart2, Clock, CheckCircle2, ArrowUpRight, ArrowDownRight,
  RefreshCw, Inbox, Users, Layers, ChevronRight,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import api from '../lib/api';
import { safeNumber } from '../lib/apiHelpers';
import { useAuth } from '../hooks/useAuth';

interface DashboardData {
  total_claims: number;
  claims_submitted_today: number;
  total_payments: number;
  payments_posted_today: number;
  open_denials: number;
  denial_rate: number;
  avg_days_in_ar: number;
  clean_claim_rate: number;
  my_queue_count: number;
  team_queue_count: number;
  unassigned_count: number;
}

interface KpiCardConfig {
  label: string;
  value: string;
  icon: React.ElementType;
  iconBg: string;
  iconColor: string;
  trend?: { label: string; up: boolean };
}

function buildCards(kpi: DashboardData): KpiCardConfig[] {
  return [
    { label: 'Total Claims',      value: safeNumber(kpi.total_claims).toLocaleString(),                      icon: FileText,     iconBg: 'bg-blue-500/10',     iconColor: 'text-blue-500',     trend: { label: 'vs last month', up: true } },
    { label: 'Submitted Today',   value: safeNumber(kpi.claims_submitted_today).toLocaleString(),             icon: TrendingUp,   iconBg: 'bg-aethera-600/10',  iconColor: 'text-aethera-600',  trend: { label: 'vs yesterday', up: true } },
    { label: 'Total Payments',    value: `$${safeNumber(kpi.total_payments).toLocaleString()}`,               icon: DollarSign,   iconBg: 'bg-emerald-500/10',  iconColor: 'text-emerald-500',  trend: { label: 'vs last month', up: true } },
    { label: 'Posted Today',      value: `$${safeNumber(kpi.payments_posted_today).toLocaleString()}`,        icon: Banknote,     iconBg: 'bg-emerald-500/10',  iconColor: 'text-emerald-500',  trend: { label: 'vs yesterday', up: true } },
    { label: 'Open Denials',      value: safeNumber(kpi.open_denials).toLocaleString(),                      icon: AlertTriangle,iconBg: 'bg-amber-500/10',    iconColor: 'text-amber-500',    trend: { label: 'vs last week', up: false } },
    { label: 'Denial Rate',       value: `${(safeNumber(kpi.denial_rate) * 100).toFixed(1)}%`,               icon: BarChart2,    iconBg: 'bg-red-500/10',      iconColor: 'text-red-500',      trend: { label: 'vs last month', up: false } },
    { label: 'Avg Days in A/R',   value: `${safeNumber(kpi.avg_days_in_ar).toFixed(1)}d`,                   icon: Clock,        iconBg: 'bg-violet-500/10',   iconColor: 'text-violet-500',   trend: { label: 'vs last month', up: false } },
    { label: 'Clean Claim Rate',  value: `${(safeNumber(kpi.clean_claim_rate) * 100).toFixed(1)}%`,          icon: CheckCircle2, iconBg: 'bg-aethera-600/10',  iconColor: 'text-aethera-600',  trend: { label: 'vs last month', up: true } },
  ];
}

function KpiSkeleton() {
  return (
    <div className="rounded-xl border p-5 animate-pulse" style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)' }}>
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-lg" style={{ backgroundColor: 'var(--bg-tertiary)' }} />
        <div className="flex-1 space-y-2 pt-1">
          <div className="h-3 w-24 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }} />
          <div className="h-6 w-16 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }} />
          <div className="h-2.5 w-20 rounded" style={{ backgroundColor: 'var(--bg-tertiary)' }} />
        </div>
      </div>
    </div>
  );
}

function KpiCard({ label, value, icon: Icon, iconBg, iconColor, trend }: KpiCardConfig) {
  return (
    <div className="rounded-xl border p-5 transition-shadow hover:shadow-md" style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
      <div className="flex items-start justify-between">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${iconBg}`}>
          <Icon className={`h-5 w-5 ${iconColor}`} />
        </div>
        {trend && (
          <span className={`flex items-center gap-0.5 text-xs font-medium ${trend.up ? 'text-emerald-500' : 'text-red-500'}`}>
            {trend.up ? <ArrowUpRight className="h-3.5 w-3.5" /> : <ArrowDownRight className="h-3.5 w-3.5" />}
          </span>
        )}
      </div>
      <div className="mt-3">
        <p className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{value}</p>
        <p className="mt-0.5 text-xs font-medium" style={{ color: 'var(--text-muted)' }}>{label}</p>
      </div>
      {trend && <p className="mt-2 text-[10px]" style={{ color: 'var(--text-subtle)' }}>{trend.label}</p>}
    </div>
  );
}

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data: dashboard, isLoading, isError, refetch } = useQuery<DashboardData>({
    queryKey: ['dashboard-kpi'],
    queryFn: () => api.get('/queues/dashboard').then((r) => r.data),
  });

  const firstName = user?.full_name?.split(' ')[0] ?? 'there';
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
  const cards = dashboard ? buildCards(dashboard) : [];

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{greeting}, {firstName}.</h1>
        <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>Here&apos;s your RCM overview for today.</p>
      </div>

      {isError ? (
        <div className="rounded-xl border p-8 text-center" style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)' }}>
          <AlertTriangle className="mx-auto mb-3 h-10 w-10 text-amber-500" />
          <p className="font-semibold" style={{ color: 'var(--text-primary)' }}>Failed to load dashboard data</p>
          <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>The API may be unavailable. Your other work queues are unaffected.</p>
          <button onClick={() => refetch()} className="mt-4 inline-flex items-center gap-2 rounded-lg bg-aethera-600 px-4 py-2 text-sm font-medium text-white hover:bg-aethera-700 transition-colors">
            <RefreshCw className="h-4 w-4" /> Retry
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {isLoading ? Array.from({ length: 8 }).map((_, i) => <KpiSkeleton key={i} />) : cards.map((card) => <KpiCard key={card.label} {...card} />)}
        </div>
      )}

      {!isLoading && !isError && dashboard && (
        <div className="rounded-xl border p-5" style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>My Queue</h2>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Work items assigned to you, your team, and unassigned</p>
            </div>
            <button onClick={() => navigate('/queues')} className="flex items-center gap-1.5 rounded-lg bg-aethera-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-aethera-700 transition-colors">
              Go to Queues <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'My Items',    value: safeNumber(dashboard.my_queue_count),    icon: Inbox,  color: 'text-aethera-600', bg: 'bg-aethera-600/10' },
              { label: 'Team Items',  value: safeNumber(dashboard.team_queue_count),  icon: Users,  color: 'text-violet-600',  bg: 'bg-violet-600/10' },
              { label: 'Unassigned',  value: safeNumber(dashboard.unassigned_count),  icon: Layers, color: 'text-amber-600',   bg: 'bg-amber-500/10' },
            ].map(({ label, value, icon: Icon, color, bg }) => (
              <div key={label} className="flex items-center gap-3 rounded-lg p-3" style={{ backgroundColor: 'var(--bg-secondary)' }}>
                <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${bg}`}>
                  <Icon className={`h-4 w-4 ${color}`} />
                </div>
                <div>
                  <p className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{value.toLocaleString()}</p>
                  <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-xl border p-5" style={{ backgroundColor: 'var(--card-bg)', borderColor: 'var(--border)', boxShadow: 'var(--shadow-sm)' }}>
        <h2 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>Recent Activity</h2>
        <div className="space-y-3">
          {[
            { text: 'Claim #CLM-00412 submitted to Aetna', time: '2 min ago', dot: 'bg-aethera-600' },
            { text: 'Payment of $1,240 posted — Medicare Part B', time: '14 min ago', dot: 'bg-emerald-500' },
            { text: 'Denial on Claim #CLM-00389 — CO-4 code', time: '37 min ago', dot: 'bg-amber-500' },
            { text: 'Coding review completed for 8 encounters', time: '1 hr ago', dot: 'bg-violet-500' },
            { text: 'ERA file processed — 42 remittances', time: '2 hr ago', dot: 'bg-blue-500' },
          ].map(({ text, time, dot }) => (
            <div key={text} className="flex items-start gap-3">
              <div className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${dot}`} />
              <div className="flex-1 flex items-baseline justify-between gap-4">
                <p className="text-sm" style={{ color: 'var(--text-primary)' }}>{text}</p>
                <span className="shrink-0 text-xs" style={{ color: 'var(--text-subtle)' }}>{time}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
