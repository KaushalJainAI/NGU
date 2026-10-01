import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot, User, Send, Mic, MicOff, X, Loader2,
  ArrowRight, ShoppingCart, ShoppingBasket, Plus, Minus, ChevronLeft, Shield, AlertTriangle,
  Volume2, VolumeX,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  assistantAPI, AssistantReply, ProposedAction, ProposalLine, ConversationSummary, ChatMessage,
} from "@/lib/api/assistant";
import { cartAPI } from "@/lib/api/cart";
import { trackEvent } from "@/lib/api/analytics";
import { MAX_ITEM_QUANTITY } from "@/config/limits";
import { useAuth } from "@/context/AuthContext";
import { useCart } from "@/context/CartContext";
import { useVoiceInput } from "@/hooks/useVoiceInput";
import ChatMarkdown from "@/components/ChatMarkdown";
import { useTranslation } from "react-i18next";

// ─── Types ────────────────────────────────────────────────────────────────────

interface LocalTurn {
  role: "user" | "assistant" | "admin";
  text: string;
  senderName?: string;
  action?: ProposedAction | null;
  // AP10: once tapped, the button stays disabled — one tap can no longer
  // repeat (the confirm call runs exactly once).
  actionUsed?: boolean;
}

const stripMarkdown = (s: string) =>
  s.replace(/[*_`#]/g, "").replace(/^\s*[-•]\s+/gm, "");

// ─── Cart proposal card (AP10) ──────────────────────────────────────────────
// One editable card for the whole shopping list: per-line quantity steppers
// (cart_proposal) and a SINGLE confirm. edit_cart proposals render as a plain
// list with the same single confirm.

const ProposalCard = ({
  action, disabled, onConfirm,
}: {
  action: ProposedAction;
  disabled: boolean;
  onConfirm: (action: ProposedAction) => void;
}) => {
  const { t } = useTranslation();
  const lines: ProposalLine[] = action.lines || [];
  const editable = action.type === "cart_proposal";
  const [qtys, setQtys] = useState<number[]>(() =>
    lines.map((l) => Math.max(1, Math.min(MAX_ITEM_QUANTITY, l.quantity || 1)))
  );
  const setQty = (i: number, q: number) =>
    setQtys((prev) => prev.map((v, j) => (j === i ? Math.max(1, Math.min(MAX_ITEM_QUANTITY, q)) : v)));
  const confirm = () =>
    onConfirm({
      ...action,
      lines: lines.map((l, i) => ({ ...l, quantity: editable ? qtys[i] : l.quantity })),
    });

  return (
    <div className="rounded-lg border border-border bg-card p-2 space-y-1.5">
      {action.note ? (
        <p className="text-xs text-muted-foreground px-1">{action.note}</p>
      ) : null}
      {lines.map((l, i) => (
        <div key={i} className="flex items-center gap-2 text-sm">
          <span className="flex-1 truncate px-1">{l.label || `#${l.product_id}`}</span>
          {editable ? (
            <span className="flex items-center gap-1 shrink-0">
              <Button
                type="button" size="icon" variant="outline" className="h-6 w-6"
                disabled={disabled || qtys[i] <= 1}
                onClick={() => setQty(i, qtys[i] - 1)}
                aria-label={t('assistant.proposalLess', 'Less')}
              >
                <Minus className="h-3 w-3" />
              </Button>
              <span className="w-6 text-center font-medium">{qtys[i]}</span>
              <Button
                type="button" size="icon" variant="outline" className="h-6 w-6"
                disabled={disabled || qtys[i] >= MAX_ITEM_QUANTITY}
                onClick={() => setQty(i, qtys[i] + 1)}
                aria-label={t('assistant.proposalMore', 'More')}
              >
                <Plus className="h-3 w-3" />
              </Button>
            </span>
          ) : (
            <span className="text-xs text-muted-foreground shrink-0 px-1">
              × {l.quantity}
            </span>
          )}
        </div>
      ))}
      <Button
        type="button" size="sm" className="w-full gap-1.5"
        disabled={disabled}
        onClick={confirm}
      >
        <ShoppingBasket className="h-4 w-4" />
        {action.type === "edit_cart"
          ? t('assistant.proposalEditConfirm', 'Update cart')
          : t('assistant.proposalConfirm', 'Add all to cart')}
      </Button>
    </div>
  );
};

// ─── Component ────────────────────────────────────────────────────────────────

const AssistantWidget = () => {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { addToCart, updateQuantity, removeFromCart, fetchCartFromBackend } = useCart();
  const queryClient = useQueryClient();
  const { t } = useTranslation();

  const LANGUAGES = [
    { code: "auto", label: t('assistant.langAuto') },
    { code: "en",   label: "English" },
    { code: "hi",   label: "हिन्दी" },
    { code: "hinglish", label: "Hinglish" },
    { code: "gu",   label: "ગુજરાતી" },
    { code: "mr",   label: "मराठी" },
    { code: "pa",   label: "ਪੰਜਾਬੀ" },
  ];

  const GREETING: LocalTurn = {
    role: "assistant",
    text: t('assistant.greeting'),
  };

  const relativeTime = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return t('assistant.justNow');
    if (m < 60) return t('assistant.minutesAgo', { count: m });
    const h = Math.floor(m / 60);
    if (h < 24) return t('assistant.hoursAgo', { count: h });
    return t('assistant.daysAgo', { count: Math.floor(h / 24) });
  };

  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"threads" | "chat">("chat");
  const [voiceMode, setVoiceMode] = useState(false);
  // AP11: read-aloud is an EXPLICIT toggle, default OFF (using the mic once
  // must not narrate every later typed reply). Persisted per device.
  const [readAloud, setReadAloud] = useState(
    () => localStorage.getItem("assistant_read_aloud") === "1"
  );
  const [input, setInput] = useState("");
  const [turns, setTurns] = useState<LocalTurn[]>([GREETING]);
  const [activeConvId, setActiveConvId] = useState<string | null>(
    () => localStorage.getItem("assistant_conversation_id")
  );
  // Set once the backend reports the thread outgrew the model's context window
  // (its oldest turns are no longer in the prompt) — we nudge a fresh chat.
  const [contextFull, setContextFull] = useState(false);
  // Set when the backend reports a team member has taken this thread over — the
  // AI deliberately stays silent, so the customer must be told why.
  const [handoff, setHandoff] = useState<{ name: string } | null>(null);
  const [language, setLanguage] = useState<string>(
    () => localStorage.getItem("assistant_lang") || localStorage.getItem("site_lang") || "auto"
  );

  const endRef = useRef<HTMLDivElement>(null);
  const didLoadOnOpen = useRef(false);

  // Refs let the voice hook's onTranscript reach the latest `send`/`voiceMode`
  // without re-creating the hook (which would churn the external-open effect).
  const voiceModeRef = useRef(voiceMode);
  voiceModeRef.current = voiceMode;
  const sendRef = useRef<(text: string, viaVoice?: boolean) => void>(() => {});
  // True while the pending turn came from the mic — a later proposal confirm
  // then counts as a voice confirmation (AP11 funnel event).
  const voiceTurnRef = useRef(false);

  const { supported: voiceSupported, recording, transcribing, error: voiceError, clearError: clearVoiceError, start, stop } = useVoiceInput(
    (text) => {
      setInput(text);
      if (voiceModeRef.current) {
        setVoiceMode(false); // one-shot per utterance: mic tap re-arms
        trackEvent({ event_type: "voice_used" });
        sendRef.current(text, true);
      }
    },
    () => language
  );

  // AP11: mic/transcription failures are visible (the hook never swallows).
  useEffect(() => {
    if (!voiceError) return;
    const key =
      voiceError === "mic-denied"
        ? "assistant.voiceMicDenied"
        : voiceError === "transcribe-failed"
          ? "assistant.voiceTranscribeFailed"
          : "assistant.voiceNothingHeard";
    const fallback =
      voiceError === "mic-denied"
        ? "Microphone blocked — allow mic access to use voice."
        : voiceError === "transcribe-failed"
          ? "Could not transcribe that — please try again."
          : "Didn't catch that — please try again.";
    toast.error(t(key, fallback));
    clearVoiceError();
  }, [voiceError, t, clearVoiceError]);

  // AP11: read-aloud speaks in the thread's language (browser default would
  // mangle Hindi/Gujarati/Marathi/Punjabi). Never runs unless toggled on.
  const speak = useCallback(
    (text: string) => {
      if (!readAloud || !("speechSynthesis" in window) || !text) return;
      const langMap: Record<string, string> = {
        hi: "hi-IN", hinglish: "hi-IN", gu: "gu-IN", mr: "mr-IN", pa: "pa-IN",
      };
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(stripMarkdown(text));
        utterance.lang = langMap[language] ?? "en-IN";
        window.speechSynthesis.speak(utterance);
      } catch { /* noop */ }
    },
    [readAloud, language]
  );

  const toggleReadAloud = useCallback(() => {
    setReadAloud((prev) => {
      const next = !prev;
      localStorage.setItem("assistant_read_aloud", next ? "1" : "0");
      if (!next && "speechSynthesis" in window) {
        try { window.speechSynthesis.cancel(); } catch { /* noop */ }
      }
      return next;
    });
  }, []);

  // AP11: speech never leaks past the widget — closing stops it cold.
  useEffect(() => {
    if (!open && "speechSynthesis" in window) {
      try { window.speechSynthesis.cancel(); } catch { /* noop */ }
    }
  }, [open]);

  // ── Thread list (only when logged in) ─────────────────────────────────────
  const { data: threads = [] } = useQuery<ConversationSummary[]>({
    queryKey: ["assistant-threads"],
    queryFn: assistantAPI.listConversations,
    enabled: !!user && open,
    refetchInterval: open ? 8000 : false,
  });

  // ── Open widget from outside (MobileFooter, WhatsApp, etc.) ───────────────
  useEffect(() => {
    const handler = (e: Event) => {
      // The assistant is login-only (the backend rejects anonymous chat), so an
      // external trigger from a logged-out user must route to login, not open.
      if (!user) {
        navigate("/login");
        return;
      }
      setOpen(true);
      const detail = (e as CustomEvent).detail;
      if (detail?.voice && voiceSupported) {
        setVoiceMode(true);
        setTimeout(() => start(), 300);
      }
      // Pre-seed the input (e.g. opened from an order's "Chat Support" button).
      if (detail?.seed) {
        setView("chat");
        setInput(detail.seed);
      }
    };
    window.addEventListener("assistant:open", handler);
    return () => window.removeEventListener("assistant:open", handler);
  }, [voiceSupported, start, user, navigate]);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, open, view]);

  // ── Load a thread's history from the server ────────────────────────────────
  const loadThread = useCallback(async (convId: string) => {
    try {
      const msgs: ChatMessage[] = await assistantAPI.getMessages(convId);
      const loaded: LocalTurn[] = msgs
        .filter((m) => m.role !== "tool" && m.role !== "system" && m.content)
        .map((m) => ({
          role: m.role as LocalTurn["role"],
          text: m.content,
          senderName: m.sender_name || undefined,
          // AP10: saved proposals travel with history so buttons survive
          // reload (fresh again — the server does not track taps).
          action: m.proposed_action || null,
        }));
      setTurns(loaded.length ? loaded : [GREETING]);
    } catch {
      setTurns([GREETING]);
    }
  }, []);

  // ── Restore the active thread's history when the widget is (re)opened ──────
  // Without this, reopening shows only the greeting while messages silently
  // continue appending to the existing server-side thread.
  useEffect(() => {
    if (!open) {
      didLoadOnOpen.current = false;
      return;
    }
    if (user && activeConvId && !didLoadOnOpen.current) {
      didLoadOnOpen.current = true;
      loadThread(activeConvId);
    }
  }, [open, user, activeConvId, loadThread]);

  // ── Switch to a thread ─────────────────────────────────────────────────────
  const switchThread = useCallback(
    (convId: string) => {
      setActiveConvId(convId);
      localStorage.setItem("assistant_conversation_id", convId);
      // Both notices describe a thread, not the widget.
      setContextFull(false);
      setHandoff(null);
      setView("chat");
      loadThread(convId);
    },
    [loadThread]
  );

  // ── New thread ─────────────────────────────────────────────────────────────
  const newThreadMutation = useMutation({
    mutationFn: assistantAPI.createConversation,
    onSuccess: (convo) => {
      queryClient.invalidateQueries({ queryKey: ["assistant-threads"] });
      setActiveConvId(convo.conversation_id);
      localStorage.setItem("assistant_conversation_id", convo.conversation_id);
      setTurns([GREETING]);
      setContextFull(false);
      setHandoff(null);
      setView("chat");
    },
  });

  // ── Chat send ──────────────────────────────────────────────────────────────
  const mutation = useMutation({
    mutationFn: (message: string) =>
      assistantAPI.chat(message, activeConvId, language),
    onSuccess: (data: AssistantReply) => {
      setActiveConvId(data.conversation_id);
      localStorage.setItem("assistant_conversation_id", data.conversation_id);
      if (data.history_truncated) setContextFull(true);

      // A team member owns this thread: there is no AI turn to append, and the
      // admin's own replies arrive via the poll below.
      if (data.ai_paused) {
        setHandoff({ name: data.handled_by || "" });
        queryClient.invalidateQueries({ queryKey: ["assistant-threads"] });
        return;
      }
      setHandoff(null);

      setTurns((prev) => [
        ...prev,
        { role: "assistant", text: data.reply, action: data.proposed_action },
      ]);
      queryClient.invalidateQueries({ queryKey: ["assistant-threads"] });
      speak(data.reply);
    },
    onError: () => {
      setTurns((prev) => [
        ...prev,
        { role: "assistant", text: t('assistant.error') },
      ]);
    },
  });

  const send = useCallback(
    (raw: string, viaVoice = false) => {
      const message = raw.trim();
      if (!message || mutation.isPending) return;
      voiceTurnRef.current = viaVoice;
      setTurns((prev) => [...prev, { role: "user", text: message }]);
      setInput("");
      mutation.mutate(message);
    },
    [mutation]
  );

  // Expose the latest `send` to the voice hook's onTranscript callback.
  sendRef.current = send;

  // ── Handoff detection on open ─────────────────────────────────────────────
  // Reopening a thread a team member already took over must show the notice
  // without the customer having to send a message first. Set-only, never
  // cleared here: a stale list must not flicker the banner off. It is cleared
  // by an explicit signal — switching threads, a new thread, or a chat reply
  // that comes back un-paused (i.e. the AI is answering again).
  useEffect(() => {
    if (!open || !activeConvId) return;
    const thread = threads.find((th) => th.conversation_id === activeConvId);
    if (thread?.ai_paused) setHandoff({ name: thread.ai_paused_by || "" });
  }, [open, activeConvId, threads]);

  // ── Poll the open thread while a human is handling it ─────────────────────
  // The AI produces no turns during a handoff, so without this the chat looks
  // dead until the customer closes and reopens the widget. Only runs while
  // paused, so it can't clobber an in-flight optimistic turn in normal use.
  useEffect(() => {
    if (!open || view !== "chat" || !handoff || !activeConvId) return;
    const id = window.setInterval(() => {
      if (!mutation.isPending) loadThread(activeConvId);
    }, 8000);
    return () => window.clearInterval(id);
  }, [open, view, handoff, activeConvId, loadThread, mutation.isPending]);

  // AP10: mark the tapped button used BEFORE running, so one tap can never
  // repeat (double-tap, reload-while-pending). The confirm itself runs once.
  const markActionUsed = (index: number) => {
    setTurns((prev) => prev.map((turn, i) =>
      i === index ? { ...turn, actionUsed: true } : turn
    ));
  };

  const handleAction = async (action: ProposedAction, turnIndex: number) => {
    markActionUsed(turnIndex);
    // AP11 funnel: a proposal confirm that completes a voice-originated turn.
    const fromVoice = voiceTurnRef.current;
    voiceTurnRef.current = false;
    try {
      switch (action.type) {
        case "add_to_cart": {
          const res = await addToCart({
            id: action.product_id!,
            itemType: action.item_type || "product",
            name: action.label, image: "",
            price: action.price ?? 0,
            variantId: action.variant_id ?? null,
            quantity: action.quantity || 1,
          });
          if (res.requiresLogin) navigate("/login");
          else if (fromVoice) trackEvent({ event_type: "voice_confirmed" });
          break;
        }
        case "cart_proposal": {
          // ONE cart-add call for the whole list (AP10) — never one per line.
          await cartAPI.sync((action.lines || []).map((l) => ({
            product_id: l.product_id,
            item_type: l.item_type || "product",
            quantity: Math.max(1, Math.min(MAX_ITEM_QUANTITY, l.quantity || 1)),
            variant_id: l.variant_id ?? null,
          })));
          await fetchCartFromBackend();
          toast.success(t('assistant.proposalAdded', 'Added to cart'));
          if (fromVoice) trackEvent({ event_type: "voice_confirmed" });
          break;
        }
        case "edit_cart": {
          for (const l of action.lines || []) {
            if ((l.quantity || 0) <= 0) {
              await removeFromCart(l.product_id, l.item_type || "product", l.variant_id ?? null);
            } else {
              await updateQuantity(l.product_id, l.quantity, l.item_type || "product", l.variant_id ?? null);
            }
          }
          toast.success(t('assistant.proposalUpdated', 'Cart updated'));
          if (fromVoice) trackEvent({ event_type: "voice_confirmed" });
          break;
        }
        case "checkout":
        case "navigate":
          if (action.route) { setOpen(false); navigate(action.route); }
          break;
        case "escalate_to_human":
          toast.info(t('assistant.escalated'));
          break;
      }
    } catch {
      toast.error(t('assistant.proposalFailed', 'Could not update the cart — please try again'));
    }
  };

  const toggleMic = () => {
    if (!voiceSupported) {
      toast.error(t('assistant.voiceUnsupported'));
      return;
    }
    if (recording) { stop(); } else { setVoiceMode(true); start(); }
  };

  // ── Launcher button ───────────────────────────────────────────────────────
  // Desktop only — on mobile the bottom nav's "Chat" button opens the assistant
  // (via the `assistant:open` event), so a second floating launcher is hidden to
  // avoid duplicate chat buttons.
  if (!open) {
    return (
      <Button
        onClick={() => (user ? setOpen(true) : navigate("/login"))}
        className="hidden md:flex fixed right-6 bottom-6 h-16 w-16 rounded-full shadow-lg hover:shadow-xl
                   transition-all duration-300 z-50 text-3xl leading-none
                   animate-pulse-subtle hover:scale-110 active:scale-95 hover-glow"
        aria-label={t('assistant.openAria')}
      >
        <span aria-hidden>💬</span>
      </Button>
    );
  }

  // ── Panel ──────────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed right-4 z-50 md:bottom-6 bottom-52 w-[calc(100vw-2rem)] sm:w-96
                 h-[72vh] sm:h-[36rem] max-h-[640px] flex flex-col
                 bg-card border border-border rounded-2xl shadow-2xl overflow-hidden
                 animate-page-enter"
    >
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-4 py-3 border-b bg-primary text-primary-foreground shrink-0">
        {view === "chat" && user && (
          <button
            onClick={() => setView("threads")}
            aria-label={t('assistant.threadListAria')}
            className="opacity-80 hover:opacity-100 mr-1"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
        )}
        <Bot className="h-5 w-5 shrink-0" />
        <span className="font-semibold text-sm flex-1 truncate">
          {view === "threads" ? t('assistant.yourConversations') : t('assistant.title')}
        </span>

        {view === "chat" && (
          <button
            onClick={toggleReadAloud}
            aria-label={t('assistant.readAloudAria', 'Read replies aloud')}
            title={readAloud
              ? t('assistant.readAloudOn', 'Read-aloud on')
              : t('assistant.readAloudOff', 'Read-aloud off')}
            className="opacity-80 hover:opacity-100"
          >
            {readAloud ? <Volume2 className="h-5 w-5" /> : <VolumeX className="h-5 w-5" />}
          </button>
        )}

        {view === "chat" && (
          <Select
            value={language}
            onValueChange={(v) => {
              setLanguage(v);
              localStorage.setItem("assistant_lang", v);
            }}
          >
            <SelectTrigger
              aria-label={t('assistant.replyLanguageAria')}
              className="h-7 w-[104px] text-xs bg-primary-foreground/10 border-primary-foreground/25 text-primary-foreground focus:ring-primary-foreground/40"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGES.map((l) => (
                <SelectItem key={l.code} value={l.code}>{l.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {view === "chat" && user && (
          <button
            onClick={() => newThreadMutation.mutate()}
            aria-label={t('assistant.newConversation')}
            className="opacity-80 hover:opacity-100"
            title={t('assistant.newChat')}
          >
            <Plus className="h-5 w-5" />
          </button>
        )}

        <button onClick={() => setOpen(false)} aria-label={t('assistant.close')} className="opacity-80 hover:opacity-100">
          <X className="h-5 w-5" />
        </button>
      </div>

      {/* ── Thread list view ────────────────────────────────────────────────── */}
      {view === "threads" && (
        <div className="flex-1 overflow-y-auto">
          <button
            onClick={() => newThreadMutation.mutate()}
            className="w-full flex items-center gap-3 px-4 py-3 border-b hover:bg-accent transition-colors text-sm font-medium text-primary"
          >
            <Plus className="h-4 w-4" />
            {t('assistant.newConversation')}
          </button>

          {threads.length === 0 && (
            <p className="text-center text-muted-foreground text-sm mt-8 px-4">
              {t('assistant.noConversations')}
            </p>
          )}

          {threads.map((thread) => (
            <button
              key={thread.conversation_id}
              onClick={() => switchThread(thread.conversation_id)}
              className={`w-full text-left px-4 py-3 border-b hover:bg-accent transition-colors
                ${activeConvId === thread.conversation_id ? "bg-accent" : ""}`}
            >
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium truncate flex-1">
                  {thread.title || t('assistant.newConversation')}
                </span>
                <div className="flex items-center gap-1 shrink-0">
                  {thread.needs_human && (
                    <span className="h-2 w-2 rounded-full bg-orange-500" title={t('assistant.needsAttention')} />
                  )}
                  <span className="text-xs text-muted-foreground">{relativeTime(thread.updated_at)}</span>
                </div>
              </div>
              {thread.last_message && (
                <p className="text-xs text-muted-foreground truncate mt-0.5">{thread.last_message}</p>
              )}
            </button>
          ))}
        </div>
      )}

      {/* ── Chat view ───────────────────────────────────────────────────────── */}
      {view === "chat" && (
        <>
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {turns.map((turn, i) => {
              const isUser = turn.role === "user";
              const isAdmin = turn.role === "admin";

              return (
                <div key={i} className={`flex items-start gap-2 ${isUser ? "flex-row-reverse" : ""}`}>
                  {/* Avatar */}
                  <div className={`p-1.5 rounded-full shrink-0 ${
                    isUser
                      ? "bg-primary text-primary-foreground"
                      : isAdmin
                        ? "bg-orange-500 text-white"
                        : "bg-accent text-accent-foreground"
                  }`}>
                    {isUser
                      ? <User className="h-4 w-4" />
                      : isAdmin
                        ? <Shield className="h-4 w-4" />
                        : <Bot className="h-4 w-4" />
                    }
                  </div>

                  {/* Bubble */}
                  <div className="max-w-[80%] space-y-2">
                    {isAdmin && turn.senderName && (
                      <p className="text-xs text-orange-600 font-medium px-1">
                        {t('assistant.teamMember', { name: turn.senderName })}
                      </p>
                    )}
                    <div className={`px-3 py-2 rounded-lg text-sm ${
                      isUser
                        ? "bg-primary text-primary-foreground whitespace-pre-wrap"
                        : isAdmin
                          ? "bg-orange-50 border border-orange-200 text-foreground"
                          : "bg-muted"
                    }`}>
                      {isUser
                        ? turn.text
                        : <ChatMarkdown text={turn.text} />
                      }
                    </div>
                    {turn.action && !turn.actionUsed &&
                      (turn.action.type === "cart_proposal" || turn.action.type === "edit_cart") && (
                      <ProposalCard
                        action={turn.action}
                        disabled={false}
                        onConfirm={(a) => handleAction(a, i)}
                      />
                    )}
                    {turn.action && !turn.actionUsed &&
                      turn.action.type !== "cart_proposal" && turn.action.type !== "edit_cart" && (
                      <Button
                        size="sm"
                        variant="secondary"
                        className="gap-1.5"
                        onClick={() => handleAction(turn.action!, i)}
                      >
                        {turn.action.type === "add_to_cart"
                          ? <ShoppingCart className="h-4 w-4" />
                          : <ArrowRight className="h-4 w-4" />
                        }
                        {turn.action.label}
                      </Button>
                    )}
                    {turn.action && turn.actionUsed && (
                      <p className="text-xs text-muted-foreground px-1">
                        {t('assistant.proposalDone', 'Done ✓')}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}

            {mutation.isPending && (
              <div className="flex items-center gap-2 text-muted-foreground text-sm">
                <Bot className="h-4 w-4" />
                <Loader2 className="h-4 w-4 animate-spin" />
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* Human handoff: a team member owns this thread, so the AI is quiet.
              Without this the missing AI reply just reads as broken. */}
          {handoff && (
            <div className="mx-3 mb-2 p-2 rounded-md border border-orange-200 bg-orange-50 text-xs text-orange-900 flex items-start gap-2">
              <Shield className="h-4 w-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium">
                  {handoff.name
                    ? t('assistant.humanHandoffNamed', { name: handoff.name })
                    : t('assistant.humanHandoff')}
                </p>
                <p className="opacity-80">{t('assistant.humanHandoffWait')}</p>
              </div>
            </div>
          )}

          {/* Context-window notice: the thread no longer fits, so the earliest
              turns are gone from the prompt. Offer a one-click fresh thread. */}
          {contextFull && (
            <div className="mx-3 mb-2 p-2 rounded-md border border-amber-300 bg-amber-50 text-xs text-amber-900 flex items-start gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p>{t('assistant.contextFull')}</p>
                {user && (
                  <button
                    type="button"
                    onClick={() => newThreadMutation.mutate()}
                    className="font-medium underline underline-offset-2"
                  >
                    {t('assistant.contextFullCta')}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Input */}
          <form
            onSubmit={(e) => { e.preventDefault(); send(input); }}
            className="p-3 border-t flex items-center gap-2 shrink-0"
          >
            {voiceSupported && (
              <Button
                type="button"
                size="icon"
                variant={recording ? "default" : "outline"}
                onClick={toggleMic}
                disabled={transcribing}
                aria-label={recording ? t('assistant.stopListening') : t('assistant.speak')}
                className={recording ? "animate-pulse" : ""}
              >
                {transcribing
                  ? <Loader2 className="h-4 w-4 animate-spin" />
                  : recording
                    ? <MicOff className="h-4 w-4" />
                    : <Mic className="h-4 w-4" />}
              </Button>
            )}
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={
                recording ? t('assistant.listening') : transcribing ? t('assistant.transcribing') : t('assistant.inputPlaceholder')
              }
              className="flex-1"
            />
            <Button type="submit" size="icon" disabled={!input.trim() || mutation.isPending}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </>
      )}
    </div>
  );
};

export default AssistantWidget;
