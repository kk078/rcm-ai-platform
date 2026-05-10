import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Download } from 'lucide-react';
import api from '../lib/api';

type ReportType = 'monthly_collection' | 'ar_aging' | 'denial_summary' | 'payer_performance';

const REPORT_TYPES: { value: ReportType; label: string }[] = [
  { value: 'monthly_collection', label: 'Monthly Collection Report' },
  { value: 'ar_aging', label: 'AR Aging Report' },
  { value: 'denial_summary', label: 'Denial Summary' },
  { value: 'payer_performance', label: 'Payer Performance' },
];

export function ReportsPage() {
  const [selectedReport, setSelectedReport] = useState<ReportType>('monthly_collection');

  const { data: reportData, isLoading: dataLoading } = useQuery({
    queryKey: ['provider-report', selectedReport],
    queryFn: () => api.get(`/portal/reports/${selectedReport}`).then((r) => r.data),
  });

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Reports</h1>
        <p className="mt-1 text-sm text-gray-500">Monthly reports and practice analytics</p>
      </div>

      <div className="mb-6 flex gap-2">
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
            </h2>
            <button className="inline-flex items-center gap-2 rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 transition-colors">
              <Download className="h-4 w-4" />
              Download
            </button>
          </div>

          {reportData ? (
            <div className="space-y-4">
              {reportData.summary && (
                <div className="grid grid-cols-3 gap-4">
                  {Object.entries(reportData.summary).map(([key, value]) => (
                    <div key={key} className="rounded-lg border border-gray-100 bg-gray-50 p-4">
                      <p className="text-xs text-gray-500 capitalize">{key.replace(/_/g, ' ')}</p>
                      <p className="mt-1 text-lg font-semibold text-gray-900">
                        {typeof value === 'number'
                          ? value > 1000
                            ? `$${value.toLocaleString()}`
                            : value.toString()
                          : String(value)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
              {reportData.details && (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50 text-left">
                      <tr>
                        {Object.keys(reportData.details[0] || {}).map((key) => (
                          <th key={key} className="px-4 py-2 text-xs font-medium text-gray-500 capitalize">
                            {key.replace(/_/g, ' ')}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {reportData.details.map((row: Record<string, unknown>, i: number) => (
                        <tr key={i} className="hover:bg-gray-50">
                          {Object.values(row).map((val, j) => (
                            <td key={j} className="px-4 py-2 text-sm text-gray-700">
                              {typeof val === 'number' && val > 1000 ? `$${val.toLocaleString()}` : String(val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
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