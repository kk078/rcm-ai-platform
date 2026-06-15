import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { FileText, Upload, X, Trash2, Download, Filter } from 'lucide-react';
import api from '../lib/api';
import { normalizeListResponse } from '../lib/apiHelpers';

interface Document {
  id: string;
  file_name: string;
  entity_type: string;
  entity_id: string;
  document_type: string;
  uploaded_by: string;
  uploaded_at: string;
  file_size: number | null;
}

const ENTITY_TYPES = ['all', 'claim', 'denial', 'appeal', 'encounter'] as const;
const DOC_TYPES = ['EOB', 'Appeal Letter', 'Clinical Note', 'Authorization', 'Other'];

function formatBytes(bytes: number | null) {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const emptyForm = { entity_type: 'claim', entity_id: '', document_type: 'EOB', description: '' };

export function DocumentsPage() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [filterType, setFilterType] = useState('all');
  const [showModal, setShowModal] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [entityFilter, setEntityFilter] = useState({ type: '', id: '' });

  const { data: rawDocs, isLoading } = useQuery({
    queryKey: ['documents', filterType, entityFilter],
    queryFn: () => {
      if (entityFilter.type && entityFilter.id) {
        return api.get(`/documents/entity/${entityFilter.type}/${entityFilter.id}`).then((r) => r.data);
      }
      return api.get('/documents/', { params: { entity_type: filterType !== 'all' ? filterType : undefined } }).then((r) => r.data);
    },
  });
  const docs = normalizeListResponse<Document>(rawDocs);

  const upload = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      if (selectedFile) fd.append('file', selectedFile);
      fd.append('entity_type', form.entity_type);
      fd.append('entity_id', form.entity_id);
      fd.append('document_type', form.document_type);
      fd.append('description', form.description);
      return api.post('/documents/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['documents'] }); setShowModal(false); setForm(emptyForm); setSelectedFile(null); },
  });

  const deleteDoc = useMutation({
    mutationFn: (id: string) => api.delete(`/documents/${id}`).then((r) => r.data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['documents'] }),
  });

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="mt-1 text-sm text-gray-500">{docs.total} documents on file</p>
        </div>
        <button
          onClick={() => { setShowModal(true); setForm(emptyForm); setSelectedFile(null); }}
          className="inline-flex items-center gap-2 rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 transition-colors"
        >
          <Upload className="h-4 w-4" /> Upload Document
        </button>
      </div>

      {/* Filter bar */}
      <div className="mb-4 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-400" />
          <div className="flex gap-1 rounded-lg bg-gray-100 p-1">
            {ENTITY_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => { setFilterType(t); setEntityFilter({ type: '', id: '' }); }}
                className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                  filterType === t ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={entityFilter.type}
            onChange={(e) => setEntityFilter((f) => ({ ...f, type: e.target.value }))}
            className="rounded-lg border border-gray-300 px-2 py-1.5 text-xs"
          >
            <option value="">Entity Type</option>
            {ENTITY_TYPES.filter((t) => t !== 'all').map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <input
            type="text"
            placeholder="Entity ID"
            value={entityFilter.id}
            onChange={(e) => setEntityFilter((f) => ({ ...f, id: e.target.value }))}
            className="w-32 rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-gray-200" />
          ))}
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
          <table className="w-full">
            <thead className="bg-gray-50 text-left">
              <tr>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">File Name</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Entity Type</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Entity ID</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Document Type</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Uploaded By</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Upload Date</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Size</th>
                <th className="px-4 py-3 text-xs font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {docs.items.map((doc) => (
                <tr key={doc.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900 flex items-center gap-2">
                    <FileText className="h-3.5 w-3.5 text-gray-400 shrink-0" />
                    {doc.file_name ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-sm capitalize text-gray-600">{doc.entity_type ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-aethera-600 font-medium">{doc.entity_id ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{doc.document_type ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{doc.uploaded_by ?? '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString() : '—'}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{formatBytes(doc.file_size ?? null)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <button className="rounded p-1 text-gray-400 hover:text-aethera-600 hover:bg-aethera-50" title="Download">
                        <Download className="h-3.5 w-3.5" />
                      </button>
                      <button
                        onClick={() => deleteDoc.mutate(doc.id)}
                        className="rounded p-1 text-gray-400 hover:text-red-600 hover:bg-red-50"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {docs.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">
                    <FileText className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                    No documents found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Upload Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-gray-900">Upload Document</h2>
              <button onClick={() => setShowModal(false)} className="rounded-lg p-1.5 hover:bg-gray-100">
                <X className="h-4 w-4 text-gray-500" />
              </button>
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Entity Type</label>
                  <select
                    value={form.entity_type}
                    onChange={(e) => setForm((f) => ({ ...f, entity_type: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  >
                    {ENTITY_TYPES.filter((t) => t !== 'all').map((t) => <option key={t} value={t} className="capitalize">{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Entity ID</label>
                  <input
                    type="text"
                    value={form.entity_id}
                    onChange={(e) => setForm((f) => ({ ...f, entity_id: e.target.value }))}
                    placeholder="Claim ID, Appeal ID..."
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Document Type</label>
                  <select
                    value={form.document_type}
                    onChange={(e) => setForm((f) => ({ ...f, document_type: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  >
                    {DOC_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">Description</label>
                  <input
                    type="text"
                    value={form.description}
                    onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
                    placeholder="Brief description..."
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-aethera-500 focus:outline-none focus:ring-1 focus:ring-aethera-500"
                  />
                </div>
              </div>

              {/* Drag-and-drop zone */}
              <div
                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
                onClick={() => fileRef.current?.click()}
                className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-8 transition-colors ${
                  dragOver ? 'border-aethera-500 bg-aethera-50' : 'border-gray-300 bg-gray-50 hover:bg-gray-100'
                }`}
              >
                <Upload className="h-6 w-6 text-gray-400" />
                {selectedFile ? (
                  <p className="text-sm font-medium text-aethera-600">{selectedFile.name}</p>
                ) : (
                  <>
                    <p className="text-sm font-medium text-gray-700">Drop file here or click to browse</p>
                    <p className="text-xs text-gray-500">PDF, PNG, JPG, DOCX up to 25MB</p>
                  </>
                )}
                <input ref={fileRef} type="file" className="hidden" onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)} />
              </div>

              {upload.isError && <p className="text-xs text-red-600">Error uploading document. Please try again.</p>}
              <div className="flex justify-end gap-3">
                <button onClick={() => setShowModal(false)} className="rounded-lg px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">Cancel</button>
                <button
                  onClick={() => upload.mutate()}
                  disabled={upload.isPending || !selectedFile}
                  className="rounded-lg bg-aethera-600 px-4 py-2 text-sm font-semibold text-white hover:bg-aethera-700 disabled:opacity-50"
                >
                  {upload.isPending ? 'Uploading...' : 'Upload'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
