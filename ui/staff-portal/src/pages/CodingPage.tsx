import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Code, Search } from 'lucide-react';
import api from '../lib/api';

interface CodingSession {
  id: string;
  encounter_id: string;
  patient_name: string;
  status: string;
  suggested_codes: string[];
  coder_codes: string[];
  confidence: number;
  created_at: string;
  completed_at: string | null;
}

interface SessionsResponse {
  items: CodingSession[];
  total: number;
  page: number;
  page_size: number;
}

export function CodingPage() {
  const [search, setSearch] = useState('');

  const { data, isLoading } = useQuery<SessionsResponse>({
    queryKey: ['coding-sessions'],
    queryFn: () =>
      api
        .get('/coding/sessions/', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const statusBadge = (s: string) => {
    const colors: Record<string, string> = {
      pending: 'bg-gray-100 text-gray-700',
      in_progress: 'bg-blue-100 text-blue-700',
      completed: 'bg-green-100 text-green-700',
      reviewed: 'bg-purple-100 text-purple-700',
    };
    return colors[s] || 'bg-gray-100 text-gray-700';
  };

  const filtered = data?.items.filter(
    (s) => !search || s.patient_name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Medical Coding</h1>
        <p className="mt-1 text-sm text-gray-500">AI-assisted coding sessions</p>
      </div>

      <div className="mb-4">
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search sessions..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-300 py-2 pl-10 pr-4 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="space-y-3">
          {filtered?.map((session) => (
            <div key={session.id} className="rounded-lg border border-gray-200 bg-white p-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <Code className="h-4 w-4 text-brand-600" />
                    <span className="font-medium text-gray-900">{session.patient_name}</span>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge(session.status)}`}>
                      {session.status.replace('_', ' ')}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-gray-500">
                    Encounter: {session.encounter_id} · Created: {session.created_at}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm text-gray-500">Confidence</p>
                  <p className="text-lg font-semibold text-gray-900">{(session.confidence * 100).toFixed(0)}%</p>
                </div>
              </div>
              <div className="mt-3 flex gap-4">
                <div>
                  <p className="text-xs text-gray-500">Suggested Codes</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {session.suggested_codes.map((code) => (
                      <span key={code} className="rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700">{code}</span>
                    ))}
                  </div>
                </div>
                {session.coder_codes.length > 0 && (
                  <div>
                    <p className="text-xs text-gray-500">Coder Codes</p>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {session.coder_codes.map((code) => (
                        <span key={code} className="rounded bg-green-50 px-2 py-0.5 text-xs text-green-700">{code}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          {(!filtered?.length) && (
            <div className="py-12 text-center text-sm text-gray-500">
              <Code className="mx-auto mb-2 h-8 w-8 text-gray-300" />
              No coding sessions found
            </div>
          )}
        </div>
      )}
    </div>
  );
}