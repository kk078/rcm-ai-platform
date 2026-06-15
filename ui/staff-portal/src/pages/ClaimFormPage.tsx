import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, FileText, Wand2, Save, CheckCircle2, AlertTriangle, Building2 } from 'lucide-react';
import api from '../lib/api';

type FormType = 'cms1500' | 'ub04';

interface Field { key: string; label: string; value: string }
interface Section { title: string; fields: Field[] }
interface Dx { pointer: string; code: string; description: string }
interface FormPayload { form_type: string; sections: Section[]; diagnoses: Dx[]; service_lines: Record<string, string>[] }
interface Edit { code: string; severity: string; field: string; message: string }
interface ClaimForm {
  id: string; claim_id: string; form_type: string; status: string;
  fields: FormPayload; edits: Edit[]; enrichment: Record<string, any>; updated_at: string | null;
}

const FORM_LABELS: Record<FormType, string> = { cms1500: 'CMS-1500 (Professional)', ub04: 'UB-04 (Institutional)' };

export function ClaimFormPage() {
  const { claimId } = useParams<{ claimId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [formType, setFormType] = useState<FormType>('cms1500');
  const [form, setForm] = useState<ClaimForm | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  async function load(ft: FormType) {
    setLoading(true); setErr(null);
    try {
      const { data } = await api.get(`/claim-forms/${claimId}?form_type=${ft}`);
      setForm(data);
    } catch (e: any) {
      if (e?.response?.status === 404) setForm(null);
      else setErr(e?.response?.data?.detail || 'Failed to load form');
    } finally { setLoading(false); }
  }
  useEffect(() => { if (claimId) load(formType); /* eslint-disable-next-line */ }, [claimId, formType]);

  const buildMut = useMutation({
    mutationFn: () => api.post(`/claim-forms/${claimId}/build?form_type=${formType}`).then((r) => r.data),
    onSuccess: (data) => { setForm(data); qc.invalidateQueries({ queryKey: ['claim', claimId] }); },
    onError: (e: any) => setErr(e?.response?.data?.detail || 'Build failed'),
  });
  const saveMut = useMutation({
    mutationFn: () => api.put(`/claim-forms/${claimId}`, { form_type: formType, fields: form!.fields }).then((r) => r.data),
    onSuccess: (data) => setForm(data),
    onError: (e: any) => setErr(e?.response?.data?.detail || 'Save failed'),
  });
  const approveMut = useMutation({
    mutationFn: () => api.post(`/claim-forms/${claimId}/approve?form_type=${formType}`).then((r) => r.data),
    onSuccess: (data) => setForm(data),
    onError: (e: any) => setErr(e?.response?.data?.detail || 'Approve failed'),
  });

  function setField(si: number, fi: number, v: string) {
    if (!form) return;
    const f = structuredClone(form);
    f.fields.sections[si].fields[fi].value = v;
    setForm(f);
  }
  function setDx(i: number, k: keyof Dx, v: string) {
    if (!form) return; const f = structuredClone(form); (f.fields.diagnoses[i] as any)[k] = v; setForm(f);
  }
  function setLine(i: number, k: string, v: string) {
    if (!form) return; const f = structuredClone(form); f.fields.service_lines[i][k] = v; setForm(f);
  }

  const errors = (form?.edits || []).filter((e) => e.severity === 'error');
  const warnings = (form?.edits || []).filter((e) => e.severity !== 'error');
  const lineCols = form?.fields.service_lines?.[0] ? Object.keys(form.fields.service_lines[0]) : [];

  return (
    <div>
      <button onClick={() => navigate(`/claims/${claimId}`)} className="mb-4 flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800">
        <ArrowLeft className="h-4 w-4" /> Back to Claim
      </button>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <FileText className="h-6 w-6 text-brand-600" />
          <h1 className="text-2xl font-bold text-gray-900">Claim Form</h1>
          {form && (
            <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${form.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-700'}`}>
              {form.status}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-gray-200 bg-white p-0.5">
            {(['cms1500', 'ub04'] as FormType[]).map((ft) => (
              <button key={ft} onClick={() => setFormType(ft)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium ${formType === ft ? 'bg-brand-600 text-white' : 'text-gray-600 hover:bg-gray-50'}`}>
                {FORM_LABELS[ft]}
              </button>
            ))}
          </div>
          <button onClick={() => buildMut.mutate()} disabled={buildMut.isPending}
            className="flex items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
            <Wand2 className="h-4 w-4" /> {buildMut.isPending ? 'Building…' : form ? 'Rebuild & Enrich' : 'Build & Enrich'}
          </button>
        </div>
      </div>

      {err && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{err}</div>}

      {loading && <div className="h-40 animate-pulse rounded-lg bg-gray-200" />}

      {!loading && !form && (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 py-20 text-center">
          <FileText className="mb-3 h-10 w-10 text-gray-300" />
          <p className="text-lg font-medium text-gray-800">No {FORM_LABELS[formType]} built yet</p>
          <p className="mt-1 text-sm text-gray-500">Click “Build &amp; Enrich” to assemble the form from this claim and auto-fill provider/payer data from NPPES &amp; CMS.</p>
        </div>
      )}

      {!loading && form && (
        <div className="space-y-6">
          {/* Enrichment banner */}
          {form.enrichment && Object.keys(form.enrichment).length > 0 && (
            <div className="rounded-lg border border-blue-200 bg-blue-50 p-4">
              <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-blue-800"><Building2 className="h-4 w-4" /> Auto-enriched from NPPES / CMS</div>
              <ul className="text-sm text-blue-700">
                {Object.entries(form.enrichment).map(([k, v]: [string, any]) => (
                  <li key={k}>• <b>{k.replace(/_/g, ' ')}</b>: {typeof v === 'object' ? Object.entries(v).map(([kk, vv]) => `${kk}=${vv}`).join(', ') : String(v)}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Scrub edits */}
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-900">
              {errors.length === 0 ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <AlertTriangle className="h-4 w-4 text-red-500" />}
              Claim Scrub — {errors.length} error{errors.length !== 1 && 's'}, {warnings.length} warning{warnings.length !== 1 && 's'}
            </div>
            {form.edits.length === 0 ? (
              <p className="text-sm text-green-700">All checks passed — ready to approve.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {form.edits.map((e, i) => (
                  <li key={i} className={e.severity === 'error' ? 'text-red-700' : 'text-yellow-700'}>
                    <span className="font-mono text-xs">[{e.code}]</span> {e.message}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Editable sections */}
          {form.fields.sections.map((sec, si) => (
            <div key={si} className="rounded-lg border border-gray-200 bg-white p-5">
              <h2 className="mb-3 font-semibold text-gray-900">{sec.title}</h2>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {sec.fields.map((fld, fi) => (
                  <label key={fld.key} className="block">
                    <span className="mb-1 block text-xs text-gray-500">{fld.label}</span>
                    <input value={fld.value} onChange={(e) => setField(si, fi, e.target.value)}
                      className="w-full rounded-md border border-gray-300 px-2 py-1.5 text-sm focus:border-brand-500 focus:outline-none" />
                  </label>
                ))}
              </div>
            </div>
          ))}

          {/* Diagnoses */}
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="mb-3 font-semibold text-gray-900">{formType === 'ub04' ? 'Diagnoses (FL67)' : 'Diagnoses (Box 21, A–L)'}</h2>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-gray-500"><th className="pb-2 pr-3">Ptr</th><th className="pb-2 pr-3">ICD-10</th><th className="pb-2">Description</th></tr></thead>
              <tbody>
                {form.fields.diagnoses.map((d, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    <td className="py-1.5 pr-3 font-mono">{d.pointer}</td>
                    <td className="py-1.5 pr-3"><input value={d.code} onChange={(e) => setDx(i, 'code', e.target.value)} className="w-24 rounded border border-gray-300 px-2 py-1" /></td>
                    <td className="py-1.5"><input value={d.description} onChange={(e) => setDx(i, 'description', e.target.value)} className="w-full rounded border border-gray-300 px-2 py-1" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Service lines */}
          <div className="rounded-lg border border-gray-200 bg-white p-5 overflow-x-auto">
            <h2 className="mb-3 font-semibold text-gray-900">{formType === 'ub04' ? 'Revenue Lines (FL42–47)' : 'Service Lines (Box 24)'}</h2>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-gray-500">{lineCols.map((c) => <th key={c} className="pb-2 pr-2">{c.replace(/_/g, ' ')}</th>)}</tr></thead>
              <tbody>
                {form.fields.service_lines.map((ln, i) => (
                  <tr key={i} className="border-t border-gray-100">
                    {lineCols.map((c) => (
                      <td key={c} className="py-1.5 pr-2"><input value={ln[c] ?? ''} onChange={(e) => setLine(i, c, e.target.value)} className="w-28 rounded border border-gray-300 px-2 py-1" /></td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-3">
            <button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}
              className="flex items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50">
              <Save className="h-4 w-4" /> {saveMut.isPending ? 'Saving…' : 'Save Changes'}
            </button>
            <button onClick={() => approveMut.mutate()} disabled={approveMut.isPending || errors.length > 0}
              title={errors.length > 0 ? 'Resolve all errors before approving' : ''}
              className="flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
              <CheckCircle2 className="h-4 w-4" /> {approveMut.isPending ? 'Approving…' : 'Approve Form'}
            </button>
            {form.updated_at && <span className="text-xs text-gray-400">Last saved {new Date(form.updated_at).toLocaleString()}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
