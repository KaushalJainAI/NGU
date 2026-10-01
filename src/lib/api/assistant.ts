import { API_BASE_URL, authFetch, authFetchForm } from "./config";

export interface ProposalLine {
  product_id: number;
  variant_id?: number | null;
  item_type?: "product" | "combo";
  quantity: number;
  label?: string;
  price?: number;
}

export interface ProposedAction {
  type: "add_to_cart" | "cart_proposal" | "edit_cart" | "checkout" | "navigate" | "escalate_to_human";
  label: string;
  route?: string;
  product_id?: number;
  variant_id?: number | null;
  item_type?: "product" | "combo";
  quantity?: number;
  price?: number;
  lines?: ProposalLine[];
  note?: string;
  reason?: string;
}

export interface AssistantReply {
  conversation_id: string;
  reply: string;
  proposed_action: ProposedAction | null;
  sources?: { tool: string; args: Record<string, unknown> }[];
  /** True when the thread outgrew the model's context window and its oldest
   *  turns were dropped from the prompt — prompt the user to start a new chat. */
  history_truncated?: boolean;
  /** True when a team member has taken over this thread — the AI deliberately
   *  did not reply. `reply` is empty in that case. */
  ai_paused?: boolean;
  /** Display name of the admin handling the thread ('' if unknown). */
  handled_by?: string;
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  status: "active" | "resolved" | "archived";
  needs_human: boolean;
  ai_paused: boolean;
  ai_paused_by: string;
  last_message: string;
  user_email: string | null;
  updated_at: string;
  created_at: string;
}

export interface TranscriptResult {
  transcript: string;
  language: string;
}

export interface ChatMessage {
  id: number;
  // Mirrors the backend ChatMessage.ROLE_CHOICES.
  role: "user" | "assistant" | "tool" | "system" | "admin";
  content: string;
  sender_name: string;
  created_at: string;
  // AP10: the saved proposal travels with history so action buttons survive
  // reload (the widget disables them again once tapped — one tap per button).
  proposed_action?: ProposedAction | null;
}

export const assistantAPI = {
  chat: async (
    message: string,
    conversationId?: string | null,
    language?: string
  ): Promise<AssistantReply> => {
    return authFetch(`${API_BASE_URL}/assistant/chat/`, {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: conversationId || undefined,
        language: language || undefined,
      }),
    });
  },

  listConversations: async (): Promise<ConversationSummary[]> => {
    return authFetch(`${API_BASE_URL}/assistant/conversations/`);
  },

  createConversation: async (): Promise<ConversationSummary> => {
    return authFetch(`${API_BASE_URL}/assistant/conversations/`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  },

  getMessages: async (conversationId: string): Promise<ChatMessage[]> => {
    return authFetch(`${API_BASE_URL}/assistant/conversations/${conversationId}/messages/`);
  },

  // Upload recorded audio (16 kHz mono WAV) for self-hosted transcription.
  transcribe: async (audio: Blob, language?: string): Promise<TranscriptResult> => {
    const form = new FormData();
    form.append("audio", audio, "voice.wav");
    if (language && language !== "auto") form.append("language", language);
    return authFetchForm(`${API_BASE_URL}/assistant/transcribe/`, form);
  },
};
