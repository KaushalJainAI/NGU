import api from './axiosInstance';

// Contact Submission types
export interface ContactSubmission {
  id: number;
  name: string;
  email: string;
  phone: string;
  subject: string;
  message: string;
  status: 'new' | 'read' | 'replied' | 'closed';
  user_email?: string;
  admin_notes: string;
  replied_at: string | null;
  created_at: string;
  updated_at: string;
}

// Contact Submissions API
export const getContactSubmissions = () => 
  api.get<ContactSubmission[]>('/contact/');

export const getContactSubmission = (id: number) => 
  api.get<ContactSubmission>(`/contact/${id}/`);

export const updateContactSubmission = (id: number, data: Partial<ContactSubmission>) => 
  api.patch<ContactSubmission>(`/contact/${id}/`, data);

export const markContactAsRead = (id: number) => 
  api.post(`/contact/${id}/mark_read/`);

export const replyToContact = (id: number, notes: string) => 
  api.post(`/contact/${id}/reply/`, { notes });

export const deleteContactSubmission = (id: number) =>
  api.delete(`/contact/${id}/`);
