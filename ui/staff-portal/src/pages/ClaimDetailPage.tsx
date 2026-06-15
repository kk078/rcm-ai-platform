import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, FileText, DollarSign, Calendar, AlertTriangle } from 'lucide-react';
import api from '../lib/api';
import { safeNumber } from '../lib/apiHelpers';

interface ClaimDetail {
  id: string;
  claim_number: string;
  status: string;
  total_charge: number;
  total_paid: number;
  total_adjusted: number | null;
  patient_responsibility: number | null;
  scrub_score: number | null;
  denial_risk_score: number | null;
  submission_date: string | null;
  created_at: string;
  patient_name: string | null;
  practice_name: string | null;
  payer_name: string | null;
  date_of_service: string | null;
}

interface HistoryEvent {
  event_type: string;
  status?: string;
  timestamp: string;
  note?: string;
  amount?: number;
}

const STATUS_COLORS: Record<string, string> = {
  draft: 'bg-gray-100 text-gray-700',
  submitted: 'bg-blue-100 text-blue-700',
  accepted: 'bg-green-100 text-green-700',
  denied: 'bg-red-100 text-red-700',
  paid: 'bg-emerald-100 text-emerald-700',
  partially_paid: 'bg-yellow-100 text-yellow-700',
  partial_paid: 'bg-yellow-100 text-yellow-700',
  appealed: 'bg-purple-100 text-purple-700',
  closed: 'bg-gray-100 text-gray-500',
};

function fmt(dt: string | null) {
  if (!dt) return '—';
  return new Date(dt).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function money(n: number | null | undefined) {
  return `$${safeNumber(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function ClaimDetailPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();

  const { data: claim, isLoading, error } = useQuery<ClaimDetail>({
    queryKey: ['claim', claimId],
    queryFn: () => api.get(`/claims/${claimId}`).then((r) => r.data),
    enabled: !!claimId,
  });

  const { data: history } = useQuery<{ events: HistoryEvent[] }>({
    queryKey: ['claim-history', claimId],
    queryFn: () => api.get(`/claims/${claimId}/history`).then((r) => r.data),
    enabled: !!claimId,
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-gray-200" />
        <div className="h-40 animate-pulse rounded-lg bg-gray-200" />
        <div className="h-40 animate-pulse rounded-lg bg-gray-200" />
      </div>
    );
  }

  if (error || !claim) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <AlertTriangle className="mb-3 h-10 w-10 text-red-400" />
        <p className="text-lg font-medium text-gray-800">Claim not found</p>
        <p className="mt-1 text-sm text-gray-500">This claim may not exist or you don't have access.</p>
        <button
          onClick={() => navigate('/claims')}
          className="mt-4 rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          Back to Claims
        </button>
      </div>
    );
  }

  const riskPct = safeNumber(claim.denial_risk_score) * 100;
  const riskColor = riskPct > 60 ? 'text-red-600' : riskPct > 30 ? 'text-yellow-600' : 'text-green-600';

  return (
    <div>
      {/* Back nav */}
      <button
        onClick={() => navigate('/claims')}
        className="mb-4 flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Claims
      </button>

      {/* Header */}
      <div className="mb-6 flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <FileText className="h-6 w-6 text-brand-600" />
            <h1 className="text-2xl font-bold text-gray-900">{claim.claim_number}</h1>
            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[claim.status] ?? 'bg-gray-100 text-gray-700'}`}>
              {claim.status.replace('_', ' ')}
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            {claim.patient_name ?? '—'} · {claim.payer_name ?? '—'}
          </p>
        </div>
        <div className="text-right text-sm text-gray-500">
          <p>Created {fmt(claim.created_at)}</p>
          {claim.submission_date && <p>Submitted {fmt(claim.submission_date)}</p>}
          <button
            onClick={() => navigate(`/claims/${claimId}/form`)}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-brand-700"
          >
            <FileText className="h-3.5 w-3.5" /> Generate Claim Form (CMS-1500 / UB-04)
          </button>
        </div>
      </div>

      {/* KPI cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        {[
          { label: 'Total Charge', value: money(claim.total_charge), icon: DollarSign, color: 'text-blue-600' },
          { label: 'Total Paid', value: money(claim.total_paid), icon: DollarSign, color: 'text-green-600' },
          { label: 'Adjustment', value: money(claim.total_adjusted), icon: DollarSign, color: 'text-yellow-600' },
          { label: 'Patient Resp.', value: money(claim.patient_responsibility), icon: DollarSign, color: 'text-gray-600' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-center gap-2">
              <Icon className={`h-4 w-4 ${color}`} />
              <span className="text-xs text-gray-500">{label}</span>
            </div>
            <p className="mt-1 text-xl font-bold text-gray-900">{value}</p>
          </div>
        ))}
      </div>

      {/* Details grid */}
      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        {/* Claim info */}
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="mb-4 font-semibold text-gray-900">Claim Details</h2>
          <dl className="space-y-3">
            {[
              ['Patient', claim.patient_name ?? '—'],
              ['Practice', claim.practice_name ?? '—'],
              ['Payer', claim.payer_name ?? '—'],
              ['Date of Service', claim.date_of_service ?? '—'],
              ['Submitted', fmt(claim.submission_date)],
            ].map(([label, val]) => (
              <div key={label} className="flex justify-between text-sm">
                <dt className="text-gray-500">{label}</dt>
                <dd className="font-medium text-gray-900">{val}</dd>
              </div>
            ))}
          </dl>
        </div>

        {/* AI scores */}
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="mb-4 font-semibold text-gray-900">AI Quality Scores</h2>
          <dl className="space-y-4">
            <div>
              <div className="flex justify-between text-sm mb-1">
                <dt className="text-gray-500">Claim Scrub Score</dt>
                <dd className="font-medium text-gray-900">{claim.scrub_score ?? '—'} / 100</dd>
              </div>
              {claim.scrub_score != null && (
                <div className="h-2 w-full rounded-full bg-gray-100">
                  <div
                    className="h-2 rounded-full bg-brand-500"
                    style={{ width: `${Math.min(100, claim.scrub_score)}%` }}
                  />
                </div>
              )}
            </div>
            <div>
              <div className="flex justify-between text-sm mb-1">
                <dt className="text-gray-500">Denial Risk</dt>
                <dd className={`font-medium ${riskColor}`}>
                  {claim.denial_risk_score != null ? `${riskPct.toFixed(0)}%` : '—'}
                </dd>
              </div>
              {claim.denial_risk_score != null && (
                <div className="h-2 w-full rounded-full bg-gray-100">
                  <div
                    className={`h-2 rounded-full ${riskPct > 60 ? 'bg-red-500' : riskPct > 30 ? 'bg-yellow-500' : 'bg-green-500'}`}
                    style={{ width: `${Math.min(100, riskPct)}%` }}
                  />
                </div>
              )}
            </div>
          </dl>
        </div>
      </div>

      {/* History */}
      {Array.isArray(history?.events) && history.events.length > 0 && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <h2 className="mb-4 font-semibold text-gray-900">Claim History</h2>
          <ol className="relative border-l border-gray-200 pl-5 space-y-4">
            {history.events.map((ev, i) => (
              <li key={i} className="ml-2">
                <div className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-white bg-brand-400" />
                <div className="flex items-center gap-2 text-sm">
                  <Calendar className="h-3.5 w-3.5 text-gray-400" />
                  <time className="text-gray-400">{fmt(ev.timestamp)}</time>
                  <span className="font-medium text-gray-900 capitalize">{ev.event_type.replace('_', ' ')}</span>
                  {ev.status && (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[ev.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {ev.status}
                    </span>
                  )}
                  {ev.amount != null && (
                    <span className="text-green-700 font-medium">{money(ev.amount)}</span>
                  )}
                </div>
                {ev.note && <p className="mt-1 text-xs text-gray-500">{ev.note}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
