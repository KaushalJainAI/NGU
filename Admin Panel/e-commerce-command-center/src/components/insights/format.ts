export const PALETTE = ['#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#06b6d4', '#a855f7', '#ec4899'];

export const inr = (n: number) =>
  `₹${Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;

export const num = (n: number) =>
  Number(n || 0).toLocaleString('en-IN');

export const pct = (n: number | null | undefined) =>
  n === null || n === undefined ? '—' : `${n}%`;
