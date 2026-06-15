import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, TrendingUp, DollarSign, FileText, AlertTriangle } from 'lucide-react';
import api from '../lib/api';
import { safeNumber } from '../lib/apiHelpers';

interface AnalyticsSummary {
  total_claims: number;
  denial_rate: number;
  collection_rate: number;
  total_collected: number;
  ai_cpt_acceptance_rate: number | null;
  ai_dx_acceptance_rate: number | null;
}

interface DenialBreakdown {
  denial_code: string;
  denial_reason: string;
  count: number;
}

const PERIODS = [
  { label: '30 days', value: 30 },
  { label: '60 days', value: 60 },
  { label: '90 days', value: 90 },
  { label: '180 days', value: 180 },
  { label: '1 year', value: 365 },
];

function ProgressBar({ value, color = 'bg-teal-500' }: { value: number; color?: string }) {
  return (
    <div className="h-2 w-full rounded-full bg-gray-200">
      <div
        className={`h-2 rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
      />
    </div>
  );
}

export function AnalyticsPage() {
  const [period, setPeriod] = useState(30);

  const { data: summary, isLoading: summaryLoading, isError: summaryError } = useQuery<AnalyticsSummary>({
    queryKey: ['provider-analytics-summary', period],
    queryFn: () => api.get('/provider-analytics/summary', { params: { period_days: period } }).then((r) => r.data),
  });

  const { data: rawBreakdown, isLoading: breakdownLoading } = useQuery<DenialBreakdown[]>({
    queryKey: ['provider-analytics-denial-breakdown', period],
    queryFn: () => api.get('/provider-analytics/denial-breakdown', { params: { period_days: period } }).then((r) => r.data),
  });

  const breakdown = Array.isArray(rawBreakdown) ? rawBreakdown : [];
  const maxCount = breakdown.length > 0 ? Math.max(...breakdown.map((d) => d.count)) : 1;

  const statCards = [
    {
      label: 'Total Claims',
      value: safeNumber(summary?.total_claims).toLocaleString(),
      icon: FileText,
      iconBg: 'bg-blue-50',
      iconColor: 'text-blue-600',
    },
    {
      label: 'Denial Rate',
      value: `${(safeNumber(summary?.denial_rate) * 100).toFixed(1)}%`,
      icon: AlertTriangle,
      iconBg: 'bg-red-50',
      iconColor: 'text-red-600',
    },
    {
      label: 'Collection Rate',
      value: `${(safeNumber(summary?.collection_rate) * 100).toFixed(1)}%`,
      icon: TrendingUp,
      iconBg: 'bg-teal-50',
      iconColor: 'text-teal-600',
    },
    {
      label: 'Total Collected',
      value: `$${safeNumber(summary?.total_collected).toLocaleString()}`,
      icon: DollarSign,
      iconBg: 'bg-emerald-50',
      iconColor: 'text-emerald-600',
    },
  ];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">Practice Analytics</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Performance metrics for your practice</p>
        </div>
        {/* Period selector */}
        <div className="flex gap-1 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] p-1">
          {PERIODS.map(({ label, value }) => (
            <button
              key={value}
              onClick={() => setPeriod(value)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                period === value
                  ? 'bg-teal-600 text-white shadow-sm'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Stat Cards */}
      {summaryLoading ? (
        <div className="grid grid-cols-2 gap-4 mb-6 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-[var(--bg-tertiary)]" />
          ))}
        </div>
      ) : summaryError ? (
        <div className="mb-6 rounded-xl border border-[var(--border)] p-6 text-center bg-[var(--card-bg)]">
          <AlertTriangle className="mx-auto mb-2 h-8 w-8 text-amber-500" />
          <p className="text-sm text-[var(--text-muted)]">Could not load analytics data. Please try again later.</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 mb-6 lg:grid-cols-4">
          {statCards.map(({ label, value, icon: Icon, iconBg, iconColor }) => (
            <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-4">
              <div className="flex items-center gap-3">
                <div className={`rounded-lg ${iconBg} p-2`}>
                  <Icon className={`h-4 w-4 ${iconColor}`} />
                </div>
                <div>
                  <p className="text-xs text-[var(--text-muted)]">{label}</p>
                  <p className="text-xl font-semibold text-[var(--text-primary)]">{value}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Denial Breakdown Bar Chart */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-5">
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-teal-600" />
            <h2 className="text-base font-semibold text-[var(--text-primary)]">Top Denial Codes</h2>
          </div>
          {breakdownLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 animate-pulse rounded bg-[var(--bg-tertiary)]" />)}
            </div>
          ) : breakdown.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)] text-center py-6">No denial data for this period.</p>
          ) : (
            <div className="space-y-3">
              {breakdown.slice(0, 5).map((row) => (
                <div key={row.denial_code}>
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs font-mono font-semibold text-red-700">{row.denial_code}</span>
                      <span className="text-xs text-[var(--text-muted)] truncate max-w-[160px]" title={row.denial_reason}>{row.denial_reason}</span>
                    </div>
                    <span className="text-xs font-semibold text-[var(--text-primary)]">{row.count}</span>
                  </div>
                  <div className="h-2.5 w-full rounded-full bg-gray-200 dark:bg-gray-700">
                    <div
                      className="h-2.5 rounded-full bg-red-400 transition-all duration-500"
                      style={{ width: `${(row.count / maxCount) * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* AI Coding Accuracy */}
        <div className="rounded-xl border border-[var(--border)] bg-[var(--card-bg)] p-5">
          <div className="mb-4 flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-teal-600" />
            <h2 className="text-base font-semibold text-[var(--text-primary)]">AI Coding Accuracy</h2>
          </div>
          {summaryLoading ? (
            <div className="space-y-4">
              {Array.from({ length: 2 }).map((_, i) => <div key={i} className="h-10 animate-pulse rounded bg-[var(--bg-tertiary)]" />)}
            </div>
          ) : summary?.ai_cpt_acceptance_rate == null && summary?.ai_dx_acceptance_rate == null ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <BarChart3 className="mb-2 h-8 w-8 text-gray-300" />
              <p className="text-sm text-[var(--text-muted)]">AI coding accuracy data is not yet available.</p>
              <p className="mt-1 text-xs text-[var(--text-subtle)]">Data will appear once AI coding suggestions have been reviewed.</p>
            </div>
          ) : (
            <div className="space-y-5">
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium text-[var(--text-primary)]">CPT Code Acceptance</p>
                  <p className="text-sm font-bold text-teal-600">{((safeNumber(summary?.ai_cpt_acceptance_rate)) * 100).toFixed(1)}%</p>
                </div>
                <ProgressBar value={safeNumber(summary?.ai_cpt_acceptance_rate) * 100} color="bg-teal-500" />
                <p className="mt-1 text-xs text-[var(--text-muted)]">Percentage of AI-suggested CPT codes accepted without modification</p>
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-sm font-medium text-[var(--text-primary)]">Diagnosis Code Acceptance</p>
                  <p className="text-sm font-bold text-violet-600">{((safeNumber(summary?.ai_dx_acceptance_rate)) * 100).toFixed(1)}%</p>
                </div>
                <ProgressBar value={safeNumber(summary?.ai_dx_acceptance_rate) * 100} color="bg-violet-500" />
                <p className="mt-1 text-xs text-[var(--text-muted)]">Percentage of AI-suggested diagnosis codes accepted without modification</p>
              </div>
              <div className="mt-4 rounded-lg bg-[var(--bg-secondary)] border border-[var(--border)] p-3 text-xs text-[var(--text-muted)]">
                Based on last {period} days of AI-assisted coding reviews
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
