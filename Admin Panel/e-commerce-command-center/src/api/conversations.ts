import api from './axiosInstance';

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  status: 'active' | 'resolved' | 'archived';
  needs_human: boolean;
  /** True while this thread is handed off to a human and the AI is staying
   *  silent. Set by any admin reply; auto-releases after an idle window. */
  ai_paused: boolean;
  /** Display name of the admin who took the thread ('' if unknown). */
  ai_paused_by: string;
  last_message: string;
  user_email: string | null;
  updated_at: string;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant' | 'admin';
  content: string;
  sender_name: string;
  created_at: string;
}

export const getConversations = async (params?: {
  needs_human?: boolean;
  status?: string;
}): Promise<ConversationSummary[]> => {
  const { data } = await api.get('/assistant/conversations/admin/', {
    params: { limit: 100, ...params },
  });
  return data;
};

export const getConversationMessages = async (
  conversationId: string
): Promise<ChatMessage[]> => {
  const { data } = await api.get(
    `/assistant/conversations/${conversationId}/messages/`
  );
  return data;
};

export const adminReply = async (
  conversationId: string,
  message: string
): Promise<void> => {
  await api.post(`/assistant/conversations/${conversationId}/admin-reply/`, { message });
};

export const patchConversation = async (
  conversationId: string,
  payload: { status?: string; needs_human?: boolean; ai_paused?: false }
): Promise<ConversationSummary> => {
  const { data } = await api.patch(
    `/assistant/conversations/${conversationId}/`,
    payload
  );
  return data;
};
