import { useState } from 'react';
import { UserPlus, Plus, Trash2, Upload, CheckCircle2, Loader2 } from 'lucide-react';
import api from '../lib/api';

interface ProviderRow {
  npi: string; first_name: string; last_name: string;
  credential: string; taxonomy_code: string; specialty: string;
}

const emptyProvider = (): ProviderRow => ({
  npi: '', first_name: '', last_name: '', credential: '', taxonomy_code: '', specialty: '',
});

export function OnboardingPage() {
  const [practice, setPractice] = useState({
    practice_name: '', legal_name: '', tin: '', group_npi: '', specialty_primary: '',
    address_line_1: '', city: '', state: '', zip_code: '', phone: '', email: '',
    contact_name: '', contact_email: '',
  });
  const [providers, setProviders] = useState<ProviderRow[]>([emptyProvider()]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<any>(null);

  // open-AR import (enabled once the practice exists)
  const [arFile, setArFile] = useState<File | null>(null);
  const [arBusy, setArBusy] = useState(false);
  const [arResult, setArResult] = useState<any>(null);
  const [arError, setArError] = useState('');
  const [billingGuidelines, setBillingGuidelines] = useState('');
  // client-info workbook upload (auto-fills billing guidelines)
  const [ciBusy, setCiBusy] = useState(false);
  const [ciMsg, setCiMsg] = useState('');

  const setP = (k: string, v: string) => setPractice((s) => ({ ...s, [k]: v }));
  const setProv = (i: number, k: string, v: string) =>
    setProviders((rows) => rows.map((r, idx) => (idx === i ? { ...r, [k]: v } : r)));

  async function submit() {
    setError(''); setResult(null);
    if (!practice.practice_name.trim()) { setError('Practice name is required.'); return; }
    if (!/^\d{2}-\d{7}$/.test(practice.tin)) { setError('TIN must be in EIN format XX-XXXXXXX.'); return; }
    const filled = providers.filter((p) => p.npi.trim() || p.first_name.trim() || p.last_name.trim());
    if (filled.length === 0) { setError('Add at least one provider with an NPI.'); return; }
    for (const p of filled) {
      if (!/^\d{10}$/.test(p.npi.trim())) { setError('Each provider needs a valid 10-digit NPI.'); return; }
      if (!p.last_name.trim()) { setError('Each provider needs a last name.'); return; }
    }
    setSubmitting(true);
    try {
      const cleanProviders = filled.map((p) => ({
        npi: p.npi.trim(), first_name: p.first_name.trim(), last_name: p.last_name.trim(),
        credential: p.credential || null, taxonomy_code: p.taxonomy_code || null,
        specialty: p.specialty || null,
      }));
      const body = {
        practice: Object.fromEntries(Object.entries(practice).map(([k, v]) => [k, v === '' ? null : v])),
        providers: cleanProviders,
        payers: [],
        billing_guidelines: billingGuidelines.trim() || null,
      };
      // practice_name and tin must stay set (not null)
      (body.practice as any).practice_name = practice.practice_name;
      (body.practice as any).tin = practice.tin;
      const { data } = await api.post('/clients/practices/onboard', body);
      setResult(data);
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Onboarding failed.');
    } finally {
      setSubmitting(false);
    }
  }

  async function importAr() {
    if (!arFile || !result?.practice_id) return;
    setArBusy(true); setArError(''); setArResult(null);
    try {
      const fd = new FormData();
      fd.append('file', arFile);
      const { data } = await api.post(`/clients/practices/${result.practice_id}/migrate/open-ar`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setArResult(data);
    } catch (e: any) {
      setArError(e?.response?.data?.detail || 'AR import failed.');
    } finally {
      setArBusy(false);
    }
  }

  async function importClientInfo(f: File) {
    if (!result?.practice_id) return;
    setCiBusy(true); setCiMsg('');
    try {
      const fd = new FormData();
      fd.append('file', f);
      const { data } = await api.post(`/clients/practices/${result.practice_id}/client-info`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      setCiMsg(`Imported ${data.chars?.toLocaleString()} characters of billing guidelines — now auto-applied to this client's agents.`);
    } catch (e: any) {
      setCiMsg(e?.response?.data?.detail || 'Could not read the workbook.');
    } finally {
      setCiBusy(false);
    }
  }

  const input = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none';
  const lbl = 'block text-xs font-medium text-gray-600 mb-1';

  return (
    <div className="max-w-4xl">
      <div className="mb-6 flex items-center gap-3">
        <UserPlus className="w-6 h-6 text-blue-600" />
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Onboard a Provider</h1>
          <p className="text-sm text-gray-500">Set up the practice, its providers, and import open AR — all in one place.</p>
        </div>
      </div>

      {!result ? (
        <div className="space-y-6">
          {/* Practice */}
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="font-semibold text-gray-900 mb-4">Practice</h2>
            <div className="grid grid-cols-2 gap-4">
              <div><label className={lbl}>Practice name *</label><input className={input} value={practice.practice_name} onChange={(e) => setP('practice_name', e.target.value)} /></div>
              <div><label className={lbl}>Legal name</label><input className={input} value={practice.legal_name} onChange={(e) => setP('legal_name', e.target.value)} /></div>
              <div><label className={lbl}>TIN / EIN * (XX-XXXXXXX)</label><input className={input} placeholder="12-3456789" value={practice.tin} onChange={(e) => setP('tin', e.target.value)} /></div>
              <div><label className={lbl}>Group NPI (10 digits)</label><input className={input} value={practice.group_npi} onChange={(e) => setP('group_npi', e.target.value)} /></div>
              <div><label className={lbl}>Primary specialty</label><input className={input} value={practice.specialty_primary} onChange={(e) => setP('specialty_primary', e.target.value)} /></div>
              <div><label className={lbl}>Phone</label><input className={input} value={practice.phone} onChange={(e) => setP('phone', e.target.value)} /></div>
              <div className="col-span-2"><label className={lbl}>Address</label><input className={input} value={practice.address_line_1} onChange={(e) => setP('address_line_1', e.target.value)} /></div>
              <div><label className={lbl}>City</label><input className={input} value={practice.city} onChange={(e) => setP('city', e.target.value)} /></div>
              <div className="grid grid-cols-2 gap-4">
                <div><label className={lbl}>State</label><input className={input} maxLength={2} value={practice.state} onChange={(e) => setP('state', e.target.value.toUpperCase())} /></div>
                <div><label className={lbl}>ZIP</label><input className={input} value={practice.zip_code} onChange={(e) => setP('zip_code', e.target.value)} /></div>
              </div>
              <div><label className={lbl}>Contact name</label><input className={input} value={practice.contact_name} onChange={(e) => setP('contact_name', e.target.value)} /></div>
              <div><label className={lbl}>Contact email</label><input className={input} value={practice.contact_email} onChange={(e) => setP('contact_email', e.target.value)} /></div>
            </div>
          </section>

          {/* Providers */}
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="font-semibold text-gray-900">Providers</h2>
              <button onClick={() => setProviders((r) => [...r, emptyProvider()])} className="text-sm text-blue-600 flex items-center gap-1 hover:text-blue-700"><Plus className="w-4 h-4" /> Add provider</button>
            </div>
            <div className="space-y-3">
              {providers.map((p, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-3"><label className={lbl}>NPI *</label><input className={input} placeholder="10 digits" value={p.npi} onChange={(e) => setProv(i, 'npi', e.target.value)} /></div>
                  <div className="col-span-2"><label className={lbl}>First</label><input className={input} value={p.first_name} onChange={(e) => setProv(i, 'first_name', e.target.value)} /></div>
                  <div className="col-span-2"><label className={lbl}>Last</label><input className={input} value={p.last_name} onChange={(e) => setProv(i, 'last_name', e.target.value)} /></div>
                  <div className="col-span-2"><label className={lbl}>Cred.</label><input className={input} placeholder="MD" value={p.credential} onChange={(e) => setProv(i, 'credential', e.target.value)} /></div>
                  <div className="col-span-2"><label className={lbl}>Taxonomy</label><input className={input} placeholder="207R00000X" value={p.taxonomy_code} onChange={(e) => setProv(i, 'taxonomy_code', e.target.value)} /></div>
                  <div className="col-span-1 flex justify-center pb-1">
                    {providers.length > 1 && <button onClick={() => setProviders((r) => r.filter((_, idx) => idx !== i))} className="text-gray-400 hover:text-red-500"><Trash2 className="w-4 h-4" /></button>}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-gray-400 mt-3">NPI is required for each provider. Payer enrollments can be added after setup from the Clients page.</p>
          </section>

          {/* Billing guidelines */}
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="font-semibold text-gray-900 mb-1">Client billing guidelines</h2>
            <p className="text-sm text-gray-500 mb-3">Paste this client's billing rules (HEDIS codes, modifiers, POS rules, payer specifics). They are <span className="font-medium">automatically applied to this client's coding &amp; billing agents</span>. You can also upload the client-info workbook after setup.</p>
            <textarea className={`${input} h-32 font-mono text-xs`} placeholder={'e.g.\nFor Televisit add modifier 95; POS 02\nAlways bill more specific ICD codes\nBill HEDIS codes for Medication, BP, BMI...'} value={billingGuidelines} onChange={(e) => setBillingGuidelines(e.target.value)} />
          </section>

          {error && <div className="bg-red-50 text-red-700 text-sm rounded-lg px-4 py-3 border border-red-200">{error}</div>}
          <button onClick={submit} disabled={submitting} className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-xl px-5 py-2.5 font-medium text-sm flex items-center gap-2">
            {submitting && <Loader2 className="w-4 h-4 animate-spin" />} Create practice & providers
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="bg-green-50 border border-green-200 rounded-xl p-5 flex items-start gap-3">
            <CheckCircle2 className="w-5 h-5 text-green-600 mt-0.5" />
            <div className="text-sm text-green-800">
              <div className="font-semibold">Practice onboarded.</div>
              <div>{result.providers_added} provider(s) added{result.payers_enrolled ? `, ${result.payers_enrolled} payer(s) enrolled` : ''}. Practice ID: <code className="text-xs">{result.practice_id}</code></div>
            </div>
          </div>

          {/* Open-AR import */}
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="font-semibold text-gray-900 mb-1">Import open AR (optional)</h2>
            <p className="text-sm text-gray-500 mb-4">Upload the provider's payer-claim-aging export (CSV/TSV) to load their open balances into the follow-up queue, prioritized by aging bucket.</p>
            <div className="flex items-center gap-3">
              <input type="file" accept=".csv,.tsv,.txt" onChange={(e) => setArFile(e.target.files?.[0] || null)} className="text-sm" />
              <button onClick={importAr} disabled={!arFile || arBusy} className="bg-gray-900 hover:bg-black disabled:bg-gray-300 text-white rounded-lg px-4 py-2 text-sm flex items-center gap-2">
                {arBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />} Import aging file
              </button>
            </div>
            {arError && <div className="mt-3 bg-red-50 text-red-700 text-sm rounded-lg px-4 py-2 border border-red-200">{arError}</div>}
            {arResult && (
              <div className="mt-4 text-sm bg-gray-50 rounded-lg p-4 border border-gray-200">
                <div className="font-medium text-gray-900 mb-2">Imported {arResult.rows_imported?.toLocaleString()} claims · open AR ${arResult.open_ar_total?.toLocaleString()}</div>
                <div className="grid grid-cols-5 gap-2 text-center">
                  {['>120', '91-120', '61-90', '31-60', '0-30'].map((b) => (
                    <div key={b} className="bg-white rounded-lg border border-gray-200 py-2">
                      <div className="text-xs text-gray-500">{b}d</div>
                      <div className="font-semibold text-gray-900">{arResult.aging_buckets?.[b] ?? 0}</div>
                    </div>
                  ))}
                </div>
                <div className="text-xs text-gray-500 mt-2">{arResult.duplicates_skipped} duplicates skipped · {arResult.credit_balances} credit balances · {arResult.zero_balance_skipped} zero-balance skipped</div>
              </div>
            )}
          </section>

          {/* Client-info workbook -> guidelines */}
          <section className="bg-white rounded-xl border border-gray-200 p-5">
            <h2 className="font-semibold text-gray-900 mb-1">Apply billing guidelines from workbook (optional)</h2>
            <p className="text-sm text-gray-500 mb-4">Upload the client-info workbook (.xlsx) — its <span className="font-medium">Billing Guidelines</span> sheet is extracted and auto-applied to this client's agents.</p>
            <div className="flex items-center gap-3">
              <input type="file" accept=".xlsx" onChange={(e) => e.target.files?.[0] && importClientInfo(e.target.files[0])} className="text-sm" disabled={ciBusy} />
              {ciBusy && <Loader2 className="w-4 h-4 animate-spin text-gray-400" />}
            </div>
            {ciMsg && <div className="mt-3 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-lg px-4 py-2">{ciMsg}</div>}
          </section>

          <button onClick={() => { setResult(null); setProviders([emptyProvider()]); setArResult(null); setArFile(null); setBillingGuidelines(''); setCiMsg(''); }} className="text-sm text-blue-600 hover:text-blue-700">Onboard another provider</button>
        </div>
      )}
    </div>
  );
}
