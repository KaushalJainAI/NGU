import { useCallback } from 'react';

const escape = (v: unknown) => {
  const s = v === null || v === undefined ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/**
 * Client-side CSV export. Turns an array of header columns + row arrays into a
 * downloadable file — no backend round-trip, works on data already fetched.
 */
export const useCsvExport = () =>
  useCallback((filename: string, cols: string[], rows: (string | number)[][]) => {
    if (rows.length === 0) return;
    const csv = [cols, ...rows].map((r) => r.map(escape).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, []);
