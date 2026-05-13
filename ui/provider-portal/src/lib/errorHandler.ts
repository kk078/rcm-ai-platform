/**
 * Extracts a human-readable error message from any error thrown by API calls.
 * Handles all error response formats the backend can return:
 *   - {"detail": "string"}
 *   - {"detail": [{msg, loc, type, input}]}
 *   - Network errors
 *   - Unknown objects
 */
export function getErrorMessage(error: any): string {
  if (!error) return 'An unknown error occurred.';
  if (typeof error === 'string') return error;

  // Network errors (no response at all)
  if (!error.response) return 'Network error. Please check your connection.';

  const data = error.response?.data;
  if (!data) return `Error ${error.response.status}`;

  // Our API format: {"detail": "string"}
  if (typeof data.detail === 'string') return data.detail;

  // FastAPI validation: {"detail": [{msg, loc, type, input}]}
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((e: any) => {
        if (typeof e === 'string') return e;
        if (e.msg) {
          const field = e.loc ? e.loc.filter((l: any) => l !== 'body').join(' → ') : '';
          return field ? `${field}: ${e.msg}` : e.msg;
        }
        return JSON.stringify(e);
      })
      .join('. ');
  }

  // Any other object
  if (typeof data.detail === 'object') return JSON.stringify(data.detail);
  if (data.message) return data.message;
  if (data.error) return data.error;

  return `Error ${error.response.status}. Please try again.`;
}