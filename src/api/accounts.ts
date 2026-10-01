import api from './axiosInstance';

export interface Expense {
  id: number;
  date: string;
  category: string;
  vendor: string;
  description: string;
  amount: string;
  gst_amount: string;
  itc_eligible: boolean;
  bill_number: string;
  payment_mode: string;
}

export type ExpensePayload = Partial<Omit<Expense, 'id'>>;

export interface BooksSummary {
  from: string;
  to: string;
  is_estimate: boolean;
  sales: { invoiced_total: string; credit_notes_total: string; net_sales_ex_gst: string };
  cash: { online_received: string; cod_received: string; refunds_paid: string; cod_outstanding_now: string };
  costs: {
    gateway_fees_ex_gst: string;
    gateway_fee_coverage: { recorded: number; total: number };
    courier_cost: string;
    courier_cost_coverage: { recorded: number; total: number };
    expenses_by_category: { category: string; label: string; cost: string }[];
    expenses_total: string;
  };
  profit: { estimated_profit: string };
  gst: {
    output_tax: string;
    credit_note_tax: string;
    input_tax_expenses: string;
    input_tax_gateway: string;
    estimated_net_gst: string;
  };
}

export const getExpenses = (params?: { from?: string; to?: string; category?: string }) =>
  api.get<Expense[]>('/expenses/', { params }).then(r => r.data);

export const createExpense = (data: ExpensePayload) =>
  api.post<Expense>('/expenses/', data);

export const updateExpense = (id: number, data: ExpensePayload) =>
  api.patch<Expense>(`/expenses/${id}/`, data);

export const deleteExpense = (id: number) =>
  api.delete(`/expenses/${id}/`);

export const getBooksSummary = (from: string, to: string) =>
  api.get<BooksSummary>('/admin/books/summary/', { params: { from, to } }).then(r => r.data);

export const exportExpensesCsv = async () => {
  const res = await api.get('/expenses/export/', { responseType: 'blob' });
  const objectUrl = window.URL.createObjectURL(res.data as Blob);
  const a = document.createElement('a');
  a.href = objectUrl;
  a.download = 'expenses.csv';
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(objectUrl);
};
