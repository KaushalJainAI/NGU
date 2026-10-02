// src/api/gst.ts
//
// GST classification + reporting.
//
// The HSN reference is REFERENCE DATA, not policy: `gst_rate` is the statutory
// rate published for a code, shown next to the rate the product actually
// charges. Nothing in this file (or the backend behind it) ever writes a rate
// from the reference — classification and pricing are the owner's decisions and
// the UI's job is only to stop a mismatch being invisible.
import api from './axiosInstance';

export interface HsnCode {
  code: string;
  description: string;
  /** Statutory GST % published for this code, as of `rates_as_of`. */
  gst_rate: number;
  chapter: string;
  /** Caveats worth reading before choosing this code. May be ''. */
  note: string;
  keywords: string[];
}

export interface HsnReference {
  /** Date the rates were published from — always show it, never imply it's live. */
  rates_as_of: string;
  rates_source: string;
  chapters: Record<string, string>;
  codes: HsnCode[];
}

export interface HsnCoverage {
  rates_as_of: string;
  unclassified: { id: number; name: string; tax_rate: number }[];
  rate_mismatch: {
    id: number;
    name: string;
    hsn_code: string;
    tax_rate: number;
    expected_rate: number;
    description: string;
    note: string;
  }[];
  unclassified_count: number;
  rate_mismatch_count: number;
}

export interface HsnSummaryRow {
  hsn_code: string;
  description: string;
  rate: number;
  uqc: string;
  quantity: number;
  taxable_value: number;
  tax_amount: number;
  total_value: number;
  is_service: boolean;
  is_unclassified: boolean;
}

export interface HsnSummary {
  from: string;
  to: string;
  rates_as_of: string;
  order_count: number;
  shipping_sac: string;
  rows: HsnSummaryRow[];
  totals: {
    quantity: number;
    taxable_value: number;
    tax_amount: number;
    total_value: number;
  };
  unclassified_value: number;
  /** Credit notes raised in the window. Reported, NOT netted off the rows. */
  refunded_in_period: { amount: number; tax: number };
  unclassified_products: { id: number; name: string; tax_rate: number }[];
}

export const getHsnReference = () =>
  api.get<HsnReference>('/admin/hsn-reference/').then(r => r.data);

export const getHsnCoverage = () =>
  api.get<HsnCoverage>('/admin/hsn-coverage/').then(r => r.data);

export const getHsnSummary = (from?: string, to?: string) =>
  api.get<HsnSummary>('/admin/hsn-summary/', { params: { from, to } })
    .then(r => r.data);

export interface GstBlock {
  count: number;
  taxable_value: number;
  cgst: number;
  sgst: number;
  igst: number;
  tax: number;
  total: number;
}

export interface GstSummary {
  from: string;
  to: string;
  invoices: GstBlock;
  credit_notes: GstBlock;
  net: Omit<GstBlock, 'count'>;
  fallback_place_of_supply: { number: string; order_number: string; address: string }[];
}

export interface B2cRow {
  state_code: string;
  state_name: string;
  rate: number | null;
  rate_label: string;
  gross_taxable_value: number;
  gross_cgst: number;
  gross_sgst: number;
  gross_igst: number;
  credit_taxable_value: number;
  credit_cgst: number;
  credit_sgst: number;
  credit_igst: number;
  net_taxable_value: number;
  net_cgst: number;
  net_sgst: number;
  net_igst: number;
}

export interface DocRow {
  series: string;
  from_number: string;
  to_number: string;
  count: number;
  gap: number;
}

const blobDownload = async (url: string, filename: string) => {
  const res = await api.get(url, { responseType: 'blob' });
  const objectUrl = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(objectUrl);
};

export const getGstSummary = (from: string, to: string) =>
  api.get<GstSummary>('/admin/gst/summary/', { params: { from, to } }).then(r => r.data);

export const getGstB2c = (from: string, to: string) =>
  api.get<{ from: string; to: string; rows: B2cRow[] }>('/admin/gst/b2c/', { params: { from, to } })
    .then(r => r.data);

export const getGstDocuments = (from: string, to: string) =>
  api.get<{ from: string; to: string; invoices: DocRow[]; credit_notes: DocRow[] }>(
    '/admin/gst/documents/', { params: { from, to } }).then(r => r.data);

export const exportGstSummaryCsv = (from: string, to: string) =>
  blobDownload(`/admin/gst/summary/?from=${from}&to=${to}&download=csv`, `gst-summary-${from}-to-${to}.csv`);

export const exportGstB2cCsv = (from: string, to: string) =>
  blobDownload(`/admin/gst/b2c/?from=${from}&to=${to}&download=csv`, `gst-b2c-${from}-to-${to}.csv`);

export const exportGstDocumentsCsv = (from: string, to: string) =>
  blobDownload(`/admin/gst/documents/?from=${from}&to=${to}&download=csv`, `gst-documents-${from}-to-${to}.csv`);

export const exportInvoiceRegisterCsv = (from: string, to: string) =>
  blobDownload(`/admin/gst/invoices/?from=${from}&to=${to}&download=csv`, `invoice-register-${from}-to-${to}.csv`);

export const exportCreditNoteRegisterCsv = (from: string, to: string) =>
  blobDownload(`/admin/gst/credit-notes/?from=${from}&to=${to}&download=csv`, `credit-note-register-${from}-to-${to}.csv`);

/**
 * Download the CSV rendering of the same summary.
 *
 * `download=csv`, NOT `format=csv` — DRF reserves `format` for renderer
 * negotiation and 404s on an unknown value.
 */
export const exportHsnSummaryCsv = async (from: string, to: string) => {
  const res = await api.get(
    `/admin/hsn-summary/?from=${from}&to=${to}&download=csv`,
    { responseType: 'blob' });
  const objectUrl = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = `hsn-summary-${from}-to-${to}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(objectUrl);
};
