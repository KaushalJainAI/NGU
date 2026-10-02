import api from './axiosInstance';

export interface AdminChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface AdminChatResponse {
  reply: string;
  sources: { tool: string; args: Record<string, unknown> }[];
}

// Stateless admin assistant: we send the recent history each turn (the panel
// keeps it in React state; nothing is stored on the server).
export const askAdminAssistant = (message: string, history: AdminChatMessage[]) =>
  api.post<AdminChatResponse>('/assistant/admin-chat/', { message, history });
