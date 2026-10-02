import { useEffect, useRef, useState } from 'react';
import { askAdminAssistant, AdminChatMessage } from '@/api/assistant';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Sparkles, X, Send, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

// Starter questions so a non-technical admin knows what they can ask. Keys, not
// literals: the suggestion is also the text SENT to the assistant, so it must be
// phrased in the language the admin is reading — the agent answers in kind.
const SUGGESTION_KEYS = [
  'assistant.suggestions.unshipped',
  'assistant.suggestions.bestSellers',
  'assistant.suggestions.lowStock',
  'assistant.suggestions.lastWeekSales',
];

/** A floating "Ask" chat panel available on every admin page. Read-only Q&A
 *  over the store's own data (sales, orders, stock, customers). */
export const AskAssistant = () => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<AdminChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || loading) return;
    const history = messages.slice(-20);
    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setInput('');
    setLoading(true);
    try {
      const res = await askAdminAssistant(question, history);
      setMessages(prev => [...prev, { role: 'assistant', content: res.data.reply || t('assistant.noAnswer') }]);
    } catch {
      setMessages(prev => [...prev, { role: 'assistant', content: t('assistant.failed') }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Floating trigger button */}
      {!open && (
        <Button
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-40 h-14 rounded-full shadow-lg px-5"
        >
          <Sparkles className="mr-2 h-5 w-5" /> {t('assistant.trigger')}
        </Button>
      )}

      {/* Panel */}
      {open && (
        <div className="fixed bottom-5 right-5 z-40 flex h-[70vh] max-h-[560px] w-[92vw] max-w-sm flex-col rounded-xl border bg-background shadow-2xl">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              <span className="font-semibold">{t('assistant.title')}</span>
            </div>
            <Button variant="ghost" size="icon" onClick={() => setOpen(false)}>
              <X className="h-4 w-4" />
            </Button>
          </div>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">{t('assistant.intro')}</p>
                <div className="space-y-2">
                  {SUGGESTION_KEYS.map(key => (
                    <button
                      key={key}
                      onClick={() => send(t(key))}
                      className="block w-full rounded-lg border p-2 text-left text-sm hover:bg-accent"
                    >
                      {t(key)}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={m.role === 'user' ? 'flex justify-end' : 'flex justify-start'}>
                <div className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
                  m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted'
                }`}>
                  {m.content}
                </div>
              </div>
            ))}
            {loading && (
              <div className="flex justify-start">
                <div className="rounded-2xl bg-muted px-3 py-2">
                  <Loader2 className="h-4 w-4 animate-spin" />
                </div>
              </div>
            )}
          </div>

          <form
            onSubmit={(e) => { e.preventDefault(); send(input); }}
            className="flex gap-2 border-t p-3"
          >
            <Input
              placeholder={t('assistant.inputPlaceholder')}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={loading}
            />
            <Button type="submit" size="icon" disabled={loading || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      )}
    </>
  );
};
