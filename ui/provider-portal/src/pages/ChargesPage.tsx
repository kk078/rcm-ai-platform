import { FilePlus } from 'lucide-react';

export function ChargesPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Charges</h1>
        <p className="mt-1 text-sm text-gray-500">Submit and manage charge entries</p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-12 text-center">
        <FilePlus className="mx-auto mb-4 h-12 w-12 text-gray-300" />
        <h3 className="text-lg font-medium text-gray-900">Charge Entry</h3>
        <p className="mt-2 text-sm text-gray-500">
          Charge entry functionality will be available in a future update.
          Please contact your billing company to submit charges.
        </p>
      </div>
    </div>
  );
}