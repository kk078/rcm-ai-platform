import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Download } from 'lucide-react';
import api from '../lib/api';
import { safeNumber } from '../lib/apiHelpers';

type ReportType = 'monthly-collection' | 'ar-aging' | 'denial-summary' | 'payer-performance';

const REPORT_TYPES: { value: ReportType; label: string }[] = [
  { value: 'monthly-collection', label: 'Monthly Collection Report' },
  { value: 'ar-aging', label: 'AR Aging Report' },
  { value: 'denial-summary', label: 'Denial Summary' },
  { value: 'payer-performance', label: 'Payer Performance' },
];

function getCurrentPeriod(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

const CURRENCY_KEY_FRAGMENTS = ['charge', 'collect', 'adjust', 'days', 'outstanding', 'paid', 'amount', 'billed', 'total_col', 'total_adj'];

function formatSummaryValue(key: string, value: unknown): string {
  if (typeof value === 'number') {
    if (key.includes('rate')) return `${(value * 100).toFixed(1)}%`;
    const isCurrency = CURRENCY_KEY_FRAGMENTS.some((f) => key.toLowerCase().includes(f)) || value > 100;
    if (isCurrency) return `$${safeNumber(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    return value.toString();
  }
  return String(value ?? '—');
}

function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/(\d+) (\d+)/g, '$1-$2')   // "0 30" → "0-30", "31 60" → "31-60"
    .replace(/\bplus\b/gi, '+')           // "120 plus" → "120+"
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ReportsPage() {
  const [selectedReport, setSelectedReport] = useState<ReportType>('monthly-collection');
  const period = getCurrentPeriod();

  const needsPeriod = selectedReport === 'monthly-collection' || selectedReport === 'denial-summary';

  const { data: reportData, isLoading: dataLoading, isError } = useQuery({
    queryKey: ['provider-report', selectedReport, period],
    queryFn: () =>
      api
        .get(`/portal/reports/${selectedReport}${needsPeriod ? `?period=${period}` : ''}`)
        .then((r) => r.data),
  });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-1 text-sm text-gray-500">Monthly reports and practice analytics</p>
      </div>

      <div className="mb-6 flex gap-2 flex-wrap">
        {REPORT_TYPES.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setSelectedReport(value)}
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
              selectedReport === value
                ? 'bg-brand-600 text-white'
                : 'bg-white border border-gray-200 text-gray-700 hover:bg-gray-50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {dataLoading ? (
        <div className="h-64 animate-pulse rounded-xl bg-gray-200" />
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white p-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              {REPORT_TYPES.find((r) => r.value === selectedReport)?.label}
              {needsPeriod && (
                <span className="ml-2 text-sm font-normal text-gray-400">({period})</span>
              )}
            </h2>
            <button className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors">
              <Download className="h-4 w-4" />
              Download
            </button>
          </div>

          {isError ? (
            <div className="py-12 text-center">
              <BarChart3 className="mx-auto mb-2 h-8 w-8 text-red-300" />
              <p className="text-sm text-red-500">Failed to load report data.</p>
            </div>
          ) : reportData ? (
            <div className="space-y-6">
              {/* Summary cards */}
              {reportData.summary && Object.keys(reportData.summary).length > 0 && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {Object.entries(reportData.summary as Record<string, unknown>).map(([key, value]) => (
                    <div key={key} className="rounded-lg border border-gray-100 bg-gray-50 p-4">
                      <p className="text-xs text-gray-500">{formatLabel(key)}</p>
                      <p className="mt-1 text-lg font-semibold text-gray-900">
                        {formatSummaryValue(key, value)}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              {/* Details table */}
              {reportData.details && Array.isArray(reportData.details) && reportData.details.length > 0 && (
                <div className="overflow-x-auto rounded-lg border border-gray-100">
                  <table className="w-full">
                    <thead className="bg-gray-50 text-left">
                      <tr>
                        {Object.keys(reportData.details[0] || {}).map((key) => (
                          <th key={key} className="px-4 py-2 text-xs font-medium text-gray-500">
                            {formatLabel(key)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {(reportData.details as Record<string, unknown>[]).map((row, i) => (
                        <tr key={i} className="hover:bg-gray-50">
                          {Object.entries(row).map(([key, val], j) => (
                            <td key={j} className="px-4 py-2 text-sm text-gray-700">
                              {formatSummaryValue(key, val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* No details fallback */}
              {reportData.details && Array.isArray(reportData.details) && reportData.details.length === 0 && (
                <p className="text-sm text-gray-400 text-center py-4">No detail rows for this period.</p>
              )}
            </div>
          ) : (
            <div className="py-12 text-center">
              <BarChart3 className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              <p className="text-sm text-gray-500">No data available for this report.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
