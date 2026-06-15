import { useEffect, useState } from 'react';
import api from '../lib/api';
import { useAuth } from '../hooks/useAuth';

interface Reference {
  id: string;
  title: string;
  url: string | null;
  source_type: string;
  char_count: number;
  status: string;
  tags: string[] | null;
  fetched_at: string | null;
  created_at: string | null;
}

export function ReferencesPage() {
  const { user } = useAuth();
  const isSuper = user?.internal_role === 'company_admin';

  const [refs, setRefs] = useState<Reference[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [openId, setOpenId] = useState<string | null>(null);
  const [content, setContent] = useState<string>('');

  async function load() {
    setLoading(true); setError(null);
    try { const { data } = await api.get('/knowledge/'); setRefs(data); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Failed to load references.'); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  async function runSearch() {
    if (!query.trim()) { load(); return; }
    setLoading(true);
    try { const { data } = await api.get('/knowledge/search', { params: { q: query, limit: 20 } }); setRefs(data); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Search failed.'); }
    finally { setLoading(false); }
  }

  async function view(id: string) {
    if (openId === id) { setOpenId(null); return; }
    try { const { data } = await api.get(`/knowledge/${id}`); setContent(data.content || '(no content field returned)'); setOpenId(id); }
    catch { setContent('Could not load content.'); setOpenId(id); }
  }
  async function refresh(id: string) {
    try { await api.post(`/knowledge/${id}/refresh`); await load(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Refresh failed.'); }
  }
  async function archive(id: string) {
    if (!confirm('Archive this reference? Agents and the assistant will stop using it.')) return;
    try { await api.delete(`/knowledge/${id}`); await load(); }
    catch (e: any) { setError(e?.response?.data?.detail || 'Archive failed.'); }
  }

  return (
    <div className="p-6">
      <div className="mb-2">
        <h1 className="text-xl font-semibold text-gray-900">Reference Library</h1>
        <p className="text-sm text-gray-500">Reference material the AI assistant and agents cite (CMS / payer / USA.gov guidance, coding rules).</p>
      </div>

      <div className="mb-4 rounded-md bg-blue-50 p-3 text-sm text-blue-800">
        To <strong>add</strong> a source, paste its URL or text to the <strong>AI Assistant</strong> chat
        {isSuper ? '' : ' (super admins only)'} — it is fetched and stored automatically. This page is for reviewing and managing the library.
      </div>

      <div className="mb-4 flex gap-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && runSearch()}
          placeholder="Search references…" className="w-full max-w-md rounded-md border px-3 py-2 text-sm" />
        <button onClick={runSearch} className="rounded-md bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700">Search</button>
        <button onClick={() => { setQuery(''); load(); }} className="rounded-md border px-3 py-2 text-sm text-gray-600">Reset</button>
      </div>

      {error && <div className="mb-3 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {loading ? <p className="text-sm text-gray-500">Loading…</p> : refs.length === 0 ? (
        <p className="text-sm text-gray-500">No references yet. Add one via the AI Assistant chat.</p>
      ) : (
        <div className="space-y-2">
          {refs.map((r) => (
            <div key={r.id} className="rounded-lg border border-gray-200 bg-white p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate font-medium text-gray-900">{r.title}</div>
                  {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="truncate text-xs text-blue-600 hover:underline">{r.url}</a>}
                  <div className="mt-1 text-xs text-gray-500">
                    {r.source_type} · {r.char_count.toLocaleString()} chars · {r.status}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2 text-xs">
                  <button onClick={() => view(r.id)} className="text-blue-600 hover:underline">{openId === r.id ? 'Hide' : 'View'}</button>
                  {isSuper && r.url && <button onClick={() => refresh(r.id)} className="text-gray-600 hover:underline">Refresh</button>}
                  {isSuper && <button onClick={() => archive(r.id)} className="text-red-600 hover:underline">Archive</button>}
                </div>
              </div>
              {openId === r.id && (
                <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-3 text-xs text-gray-700">{content}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
