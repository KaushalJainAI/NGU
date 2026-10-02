import React from "react";
import i18next from "i18next";
import { AlertTriangle, RefreshCw, Home, Phone, Mail, MessageCircle, Copy, Check } from "lucide-react";

/**
 * Support channels shown on the crash screen. Kept as literals rather than
 * translation keys because a broken i18n bundle is itself a plausible cause of
 * the crash — the phone number must survive that.
 */
const SUPPORT_PHONE = "+91 93000 05040";
const SUPPORT_PHONE_TEL = "+919300005040";
const SUPPORT_WHATSAPP = "https://wa.me/919300005040";
const SUPPORT_EMAIL = "nidhispicesandfood@gmail.com";

/**
 * `i18next.t` from the singleton rather than the `useTranslation` hook: this is
 * a class component (only class components can be error boundaries), and the
 * singleton keeps working even if the React i18n provider is part of what
 * failed. Every call carries a `defaultValue` so an uninitialised i18next
 * renders English copy instead of raw key names.
 */
const tr = (key: string, defaultValue: string): string => {
  try {
    return i18next.t(key, { defaultValue });
  } catch {
    return defaultValue;
  }
};

/**
 * A crash reference the user can read out over the phone. It is not unique
 * across users — it is a timestamp plus a short random suffix — but it is
 * enough to line a support call up against a log entry from the same minute.
 */
const makeErrorRef = (): string => {
  const stamp = new Date().toISOString().replace(/[-:.TZ]/g, "").slice(2, 12);
  const suffix = Math.random().toString(36).slice(2, 6).toUpperCase();
  return `NGU-${stamp}-${suffix}`;
};

interface Props {
  children: React.ReactNode;
  /** Shown instead of the full-page layout when the boundary wraps a widget. */
  compact?: boolean;
  /**
   * Rendered in place of the default fallback. Pass `null` for non-essential
   * chrome (floating widgets) that should simply disappear on failure rather
   * than draw attention to itself while the rest of the page still works.
   */
  fallback?: React.ReactNode;
}

interface State {
  error: Error | null;
  errorRef: string;
  componentStack: string;
  copied: boolean;
}

class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, errorRef: "", componentStack: "", copied: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error, errorRef: makeErrorRef() };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Console is the only sink today. When the client-error endpoint lands
    // (see MONITORING_PLAN.md), report it from here as well.
    console.error("[ErrorBoundary]", this.state.errorRef, error, info.componentStack);
    this.setState({ componentStack: info.componentStack || "" });
  }

  /** Everything support would need, in one clipboard paste. */
  private diagnostics(): string {
    const { error, errorRef } = this.state;
    return [
      `Reference: ${errorRef}`,
      `Page: ${window.location.href}`,
      `Time: ${new Date().toISOString()}`,
      `Error: ${error?.name}: ${error?.message}`,
      `Browser: ${navigator.userAgent}`,
    ].join("\n");
  }

  private handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(this.diagnostics());
      this.setState({ copied: true });
      setTimeout(() => this.setState({ copied: false }), 2000);
    } catch {
      /* clipboard blocked (insecure context / permission) — the reference is
         still printed on screen for the user to read out. */
    }
  };

  /**
   * A hard reload rather than clearing the error state: the failed render left
   * context providers in an unknown state, and a stale JS chunk after a deploy
   * is a common cause that only a fresh document fetch can fix.
   */
  private handleReload = () => window.location.reload();

  private handleHome = () => {
    window.location.href = "/";
  };

  render() {
    const { error, errorRef, copied } = this.state;
    const { children, compact, fallback } = this.props;

    if (!error) return children;
    if (fallback !== undefined) return <>{fallback}</>;

    const title = tr("errorBoundary.title", "Something went wrong on our end");
    const body = tr(
      "errorBoundary.message",
      "We hit a technical issue while loading this page. It is not something you did. Please try reloading — and if it keeps happening, contact us and we will sort it out for you.",
    );

    if (compact) {
      return (
        <div className="rounded-xl border border-destructive/20 bg-destructive/5 p-4 text-center">
          <AlertTriangle className="mx-auto h-5 w-5 text-destructive" aria-hidden />
          <p className="mt-2 text-sm text-muted-foreground">{body}</p>
          <button
            onClick={this.handleReload}
            className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            {tr("errorBoundary.reload", "Reload")}
          </button>
        </div>
      );
    }

    return (
      <div role="alert" className="flex min-h-screen items-center justify-center bg-background px-4 py-12">
        <div className="w-full max-w-lg text-center">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="h-7 w-7 text-destructive" aria-hidden />
          </div>

          <h1 className="mt-5 text-2xl font-bold text-foreground sm:text-3xl">{title}</h1>
          <p className="mt-3 text-sm leading-relaxed text-muted-foreground sm:text-base">{body}</p>

          <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
            <button
              onClick={this.handleReload}
              className="inline-flex items-center justify-center gap-2 rounded-full bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <RefreshCw className="h-4 w-4" aria-hidden />
              {tr("errorBoundary.reload", "Reload page")}
            </button>
            <button
              onClick={this.handleHome}
              className="inline-flex items-center justify-center gap-2 rounded-full border border-border px-6 py-2.5 text-sm font-semibold text-foreground transition-colors hover:bg-muted"
            >
              <Home className="h-4 w-4" aria-hidden />
              {tr("errorBoundary.home", "Back to home")}
            </button>
          </div>

          <div className="mt-8 rounded-2xl border border-border bg-card p-5 text-left">
            <p className="text-sm font-bold text-foreground">
              {tr("errorBoundary.contactTitle", "Still stuck? Contact us")}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {tr(
                "errorBoundary.contactHint",
                "Quote the reference below and we can trace exactly what happened.",
              )}
            </p>

            <div className="mt-4 flex flex-col gap-2.5 text-sm">
              <a
                href={SUPPORT_WHATSAPP}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2.5 text-foreground transition-colors hover:text-primary"
              >
                <MessageCircle className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span className="notranslate">{tr("errorBoundary.whatsapp", "WhatsApp")} {SUPPORT_PHONE}</span>
              </a>
              <a
                href={`tel:${SUPPORT_PHONE_TEL}`}
                className="inline-flex items-center gap-2.5 text-foreground transition-colors hover:text-primary"
              >
                <Phone className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span className="notranslate">{SUPPORT_PHONE}</span>
              </a>
              <a
                href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(`Technical issue (${errorRef})`)}`}
                className="inline-flex items-center gap-2.5 break-all text-foreground transition-colors hover:text-primary"
              >
                <Mail className="h-4 w-4 shrink-0 text-primary" aria-hidden />
                <span className="notranslate">{SUPPORT_EMAIL}</span>
              </a>
            </div>

            <div className="mt-4 flex items-center justify-between gap-3 rounded-lg bg-muted px-3 py-2">
              <code className="notranslate text-xs text-muted-foreground">{errorRef}</code>
              <button
                onClick={this.handleCopy}
                className="inline-flex shrink-0 items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
              >
                {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                {copied
                  ? tr("errorBoundary.copied", "Copied")
                  : tr("errorBoundary.copy", "Copy details")}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
