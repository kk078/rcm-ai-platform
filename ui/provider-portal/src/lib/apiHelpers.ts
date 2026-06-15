/**
 * Normalizes API list responses into a consistent shape.
 *
 * The backend may return:
 *   - A plain array: [...]
 *   - A paginated object: {items: [...], total: N, page: N, page_size: N}
 *   - A paginated object with "results" key: {results: [...], total: N, ...}
 *   - A nested response: {data: [...]}
 *   - null / undefined (network error, empty response)
 *
 * This function always returns {items: T[], total: number}, never crashing.
 */
export function normalizeListResponse<T>(data: unknown): { items: T[]; total: number } {
  if (data == null) return { items: [], total: 0 };
  if (Array.isArray(data)) return { items: data as T[], total: data.length };

  const obj = data as Record<string, unknown>;

  if (obj.items && Array.isArray(obj.items)) {
    return {
      items: obj.items as T[],
      total: typeof obj.total === 'number' ? obj.total : (obj.items as unknown[]).length,
    };
  }

  if (obj.results && Array.isArray(obj.results)) {
    return {
      items: obj.results as T[],
      total: typeof obj.total === 'number' ? obj.total : (obj.results as unknown[]).length,
    };
  }

  if (obj.data && Array.isArray(obj.data)) {
    return {
      items: obj.data as T[],
      total: typeof obj.total === 'number' ? obj.total : (obj.data as unknown[]).length,
    };
  }

  return { items: [], total: 0 };
}

/**
 * Safely extracts a numeric value from an API response object.
 * Returns `fallback` (default 0) if the value is null, undefined, or not a number.
 */
export function safeNumber(value: unknown, fallback: number = 0): number {
  return typeof value === 'number' && !isNaN(value) ? value : fallback;
}

/**
 * Safely extracts a string value from an API response object.
 * Returns `fallback` (default '') if the value is null, undefined, or not a string.
 */
export function safeString(value: unknown, fallback: string = ''): string {
  return typeof value === 'string' ? value : fallback;
}