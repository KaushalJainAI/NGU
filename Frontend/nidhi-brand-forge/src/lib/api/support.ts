import { API_BASE_URL, publicFetch } from "./config";

// Contact Submission types
export interface ContactSubmission {
  id: number;
  name: string;
  email: string;
  phone?: string;
  subject: string;
  message: string;
  status: 'new' | 'read' | 'replied' | 'closed';
  created_at: string;
}

export interface ContactSubmissionCreate {
  name: string;
  email: string;
  phone?: string;
  subject: string;
  message: string;
}

// Contact API (public - anyone can submit)
export const contactAPI = {
  submit: async (data: ContactSubmissionCreate): Promise<ContactSubmission> => {
    const response = await publicFetch<ContactSubmission>(`${API_BASE_URL}/contact/`, {
      method: "POST",
      body: JSON.stringify(data),
    });
    return response;
  },
};
